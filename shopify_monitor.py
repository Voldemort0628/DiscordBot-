import requests
import time
import json
from typing import Dict, List
import random
from config import USER_AGENT, SHOPIFY_RATE_LIMIT, MAX_PRODUCTS
import logging
import socket
import dns.resolver
import trafilatura
from urllib.parse import urlparse
import aiohttp
import asyncio
from concurrent.futures import ThreadPoolExecutor
import re

class RateLimiter:
    def __init__(self, rate_limit):
        self.rate_limit = rate_limit
        self.last_request_time = 0

    def __enter__(self):
        current_time = time.time()
        time_passed = current_time - self.last_request_time
        if time_passed < 1 / self.rate_limit:
            jitter = random.uniform(0, 0.5)
            time.sleep(1/self.rate_limit - time_passed + jitter)
        self.last_request_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class ShopifyMonitor:
    def __init__(self, rate_limit=0.5):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "no-cache"
        })
        self.rate_limiter = RateLimiter(rate_limit)
        self.failed_stores = set()
        self.retry_counts = {}
        self.last_request_time = time.time()
        self.dns_cache = {}
        self.resolvers = [
            dns.resolver.Resolver(),
            dns.resolver.Resolver(configure=False)
        ]
        self.resolvers[1].nameservers = ['8.8.8.8', '8.8.4.4']  # Use Google DNS as backup

        # Connection pooling settings
        self.max_connections = 100  # Increased from default
        self.connector = aiohttp.TCPConnector(
            limit=self.max_connections,
            ttl_dns_cache=300,
            ssl=False,
            force_close=False,  # Allow connection reuse
            use_dns_cache=True
        )
        self.timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=10)
        self.session_pool = {}  # Store sessions per domain
        self.session_pool_lock = asyncio.Lock()
        self.thread_pool = ThreadPoolExecutor(max_workers=20)  # For CPU-bound tasks

    async def get_session(self, domain: str) -> aiohttp.ClientSession:
        """Get or create a session for a specific domain"""
        async with self.session_pool_lock:
            if domain not in self.session_pool:
                self.session_pool[domain] = aiohttp.ClientSession(
                    connector=self.connector,
                    timeout=self.timeout,
                    headers={
                        'User-Agent': USER_AGENT,
                        "Accept-Encoding": "gzip, deflate",
                        "Cache-Control": "no-cache"
                    }
                )
            return self.session_pool[domain]

    def _resolve_domain(self, domain: str) -> str:
        """Resolve domain with caching and multiple DNS servers"""
        if domain in self.dns_cache:
            if time.time() - self.dns_cache[domain]['timestamp'] < 3600:  # 1 hour cache
                return self.dns_cache[domain]['ip']
            else:
                # Clear expired cache entry
                del self.dns_cache[domain]

        # Try multiple DNS resolvers with fallback
        resolver_list = [
            dns.resolver.Resolver(),  # System default
            dns.resolver.Resolver(configure=False),  # Google DNS
            dns.resolver.Resolver(configure=False),  # Cloudflare DNS
            dns.resolver.Resolver(configure=False)   # OpenDNS
        ]

        resolver_list[1].nameservers = ['8.8.8.8', '8.8.4.4']
        resolver_list[2].nameservers = ['1.1.1.1', '1.0.0.1']
        resolver_list[3].nameservers = ['208.67.222.222', '208.67.220.220']

        errors = []
        for resolver in resolver_list:
            try:
                resolver.timeout = 2.0  # Reduced timeout for faster fallback
                resolver.lifetime = 4.0  # Overall query lifetime
                answers = resolver.resolve(domain, 'A')
                if answers:
                    ip = answers[0].address
                    self.dns_cache[domain] = {
                        'ip': ip,
                        'timestamp': time.time()
                    }
                    logging.info(f"Successfully resolved {domain} to {ip} using {resolver.nameservers}")
                    return ip
            except Exception as e:
                errors.append(f"DNS resolution failed for {domain} using {resolver.nameservers}: {e}")
                continue

        # If all resolvers fail, try a direct socket connection with a shorter timeout
        try:
            socket.setdefaulttimeout(3.0)  # Shorter timeout for direct resolution
            ip = socket.gethostbyname(domain)
            self.dns_cache[domain] = {
                'ip': ip,
                'timestamp': time.time()
            }
            logging.info(f"Resolved {domain} to {ip} using socket fallback")
            return ip
        except Exception as e:
            errors.append(f"Socket resolution failed for {domain}: {e}")
            logging.error(f"All DNS resolution methods failed for {domain}:\n" + "\n".join(errors))
            return None

    def _validate_store_url(self, store_url: str) -> bool:
        """Validate store URL with enhanced error handling and recovery"""
        try:
            parsed_url = urlparse(store_url)
            domain = parsed_url.netloc

            # Try multiple times with increasing timeouts
            for timeout in [3, 5, 10]:
                try:
                    ip = self._resolve_domain(domain)
                    if not ip:
                        continue

                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(timeout)
                    result = sock.connect_ex((ip, 443))
                    sock.close()

                    if result == 0:
                        return True

                    logging.warning(f"Connection attempt failed for {domain} ({ip}:443) with timeout {timeout}s")
                except socket.error as e:
                    logging.warning(f"Socket error for {domain} with timeout {timeout}s: {e}")
                    continue

            logging.error(f"Store validation failed for {store_url} after all attempts")
            return False

        except Exception as e:
            logging.error(f"Store validation error for {store_url}: {e}")
            return False

    async def async_fetch_products(self, store_url: str, keywords: List[str]) -> List[Dict]:
        logging.info(f"Fetching products from {store_url} with keywords: {keywords}")

        if not self._validate_store_url(store_url):
            logging.error(f"Store validation failed for {store_url}")
            return []

        if store_url in self.failed_stores:
            retry_count = self.retry_counts.get(store_url, 0)
            backoff = min(300, 2 ** retry_count)  # Cap at 5 minutes
            if time.time() - self.last_request_time < backoff:
                logging.info(f"Skipping {store_url} due to recent failure (backoff: {backoff}s)")
                return []
            self.retry_counts[store_url] = retry_count + 1

        domain = urlparse(store_url).netloc
        session = await self.get_session(domain)
        max_retries = 3
        products_data = None

        try:
            initial_limit = 150  # Increased from initial fetch
            products_url = f"{store_url}/products.json?limit={initial_limit}"

            logging.info(f"Making initial request to {products_url}")

            for attempt in range(max_retries):
                try:
                    with self.rate_limiter:
                        async with session.get(
                            products_url,
                            timeout=self.timeout,
                            headers={
                                "Accept-Encoding": "gzip, deflate",
                                "Cache-Control": "no-cache"
                            }
                        ) as response:
                            if response.status == 200:
                                products_data = await response.json()
                                break
                            elif response.status == 429:  # Rate limited
                                retry_after = int(response.headers.get('Retry-After', 5))
                                logging.warning(f"Rate limited by {domain}, waiting {retry_after}s")
                                await asyncio.sleep(retry_after)
                                continue
                            else:
                                logging.warning(f"Failed request: {response.status} - {await response.text()}")
                except Exception as e:
                    if attempt == max_retries - 1:
                        logging.warning(f"API fetch failed, attempting fallback for {store_url}")
                        try:
                            # Run CPU-intensive scraping in thread pool
                            downloaded = await asyncio.get_event_loop().run_in_executor(
                                self.thread_pool,
                                trafilatura.fetch_url,
                                store_url
                            )
                            if downloaded:
                                extracted = await asyncio.get_event_loop().run_in_executor(
                                    self.thread_pool,
                                    trafilatura.extract,
                                    downloaded,
                                    False,  # include_comments
                                    False,  # include_tables
                                    False   # no_fallback
                                )
                                if extracted:
                                    products_data = await asyncio.get_event_loop().run_in_executor(
                                        self.thread_pool,
                                        self._process_fallback_content,
                                        extracted,
                                        keywords
                                    )
                        except Exception as fallback_error:
                            logging.error(f"Fallback method failed for {store_url}: {fallback_error}")
                    else:
                        await asyncio.sleep(1 * (attempt + 1))

            if not products_data:
                logging.error(f"Failed to fetch products from {store_url} after all attempts")
                return []

            matching_products = []
            total_products = len(products_data.get("products", []))
            logging.info(f"Retrieved {total_products} products from initial request")

            lowercase_keywords = [kw.lower() for kw in keywords]

            # Process products in thread pool to avoid blocking
            def process_product_batch(products_batch):
                results = []
                for product in products_batch:
                    if self._matches_keywords(product, lowercase_keywords):
                        processed = self._process_product(store_url, product)
                        if processed:
                            results.append(processed)
                return results

            # Split products into batches for parallel processing
            batch_size = 50
            products = products_data.get("products", [])
            batches = [products[i:i + batch_size] for i in range(0, len(products), batch_size)]

            # Process batches in parallel
            tasks = []
            for batch in batches:
                task = asyncio.get_event_loop().run_in_executor(
                    self.thread_pool,
                    process_product_batch,
                    batch
                )
                tasks.append(task)

            # Gather results
            batch_results = await asyncio.gather(*tasks)
            for batch_result in batch_results:
                matching_products.extend(batch_result)

            self.failed_stores.discard(store_url)
            self.retry_counts.pop(store_url, None)

            logging.info(f"Found total of {len(matching_products)} matching products")
            return matching_products

        except Exception as e:
            logging.error(f"Error fetching products from {store_url}: {e}")
            if isinstance(e, (aiohttp.ClientError, asyncio.TimeoutError)):
                self.failed_stores.add(store_url)
                logging.warning(f"Added {store_url} to failed stores list")
            return []

    def _matches_keywords(self, product: Dict, keywords: List[str]) -> bool:
        """
        Enhanced keyword matching with stricter rules and exact phrase matching
        """
        if not product:
            return False

        # Convert product fields to lowercase for case-insensitive matching
        title = product.get("title", "").lower()
        vendor = product.get("vendor", "").lower()
        product_type = product.get("product_type", "").lower()
        tags = [tag.lower() for tag in product.get("tags", [])]

        # Combine all searchable text
        searchable_text = f"{title} {vendor} {product_type} {' '.join(tags)}"

        lowercase_keywords = [kw.lower() for kw in keywords]

        # For exact phrase matching (e.g., "Air Jordan 1")
        for keyword in lowercase_keywords:
            # Split multi-word keywords for more accurate matching
            keyword_parts = keyword.split()
            if len(keyword_parts) > 1:
                # For multi-word keywords, all parts must be present in order
                found_all = True
                current_pos = 0
                for part in keyword_parts:
                    pos = searchable_text.find(part, current_pos)
                    if pos == -1:
                        found_all = False
                        break
                    current_pos = pos + len(part)
                if found_all:
                    return True
            else:
                # For single-word keywords, require word boundary match
                word_pattern = f"\\b{re.escape(keyword)}\\b"
                if re.search(word_pattern, searchable_text):
                    return True

        return False

    def _process_fallback_content(self, content: str, keywords: List[str]) -> Dict:
        products = {"products": []}
        try:
            import re
            product_blocks = re.split(r'\n{2,}', content)

            for block in product_blocks:
                if any(keyword.lower() in block.lower() for keyword in keywords):
                    title_match = re.search(r'([\w\s-]+)', block)
                    price_match = re.search(r'\$(\d+\.?\d*)', block)

                    if title_match:
                        product = {
                            "title": title_match.group(1).strip(),
                            "price": price_match.group(1) if price_match else "N/A",
                            "available": True,
                            "variants": [{"title": "Default", "price": price_match.group(1) if price_match else "N/A"}]
                        }
                        products["products"].append(product)

        except Exception as e:
            logging.error(f"Error processing fallback content: {e}")

        return products

    def _process_product(self, store_url: str, product: Dict) -> Dict:
        try:
            variants = product.get("variants", [])
            sizes = {}
            variant_ids = {}
            stock = 0

            for variant in variants:
                if variant.get("available"):
                    size = str(variant.get("title"))
                    inventory = variant.get("inventory_quantity", 1)
                    stock += inventory
                    sizes[size] = inventory
                    variant_ids[size] = str(variant.get("id", ""))

            return {
                "title": product["title"],
                "url": f"{store_url}/products/{product['handle']}",
                "price": variants[0].get("price") if variants else "N/A",
                "image_url": product.get("images", [{}])[0].get("src", ""),
                "stock": stock,
                "sizes": sizes,
                "variants": variant_ids,
                "full_size_run": "Bot 1 FSR" if stock > 0 else "OOS",
                "variant_id": variants[0].get("id") if variants else None,
                "vendor": product.get("vendor"),
                "type": product.get("product_type"),
                "tags": product.get("tags", []),
                "retailer": store_url.split('/')[2]
            }
        except Exception as e:
            logging.error(f"Error processing product {product.get('title', 'Unknown')}: {e}")
            return {}

    def get_product_variants(self, product_url):
        try:
            if not product_url.endswith('.json'):
                if product_url.endswith('/'):
                    product_url = product_url[:-1]
                product_url = product_url + '.json'

            max_retries = 3
            retry_count = 0
            while retry_count < max_retries:
                try:
                    with self.rate_limiter:
                        response = self.session.get(product_url, timeout=10)
                        response.raise_for_status()
                        product_data = response.json().get('product', {})
                        break
                except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                    retry_count += 1
                    if retry_count == max_retries:
                        logging.error(f"Failed to fetch variants after {max_retries} retries: {e}")
                        return {'variants': []}
                    time.sleep(1 * retry_count)

            if not product_data:
                return {'variants': []}

            variants = []
            for variant in product_data.get('variants', []):
                variants.append({
                    'id': variant.get('id'),
                    'title': variant.get('title'),
                    'price': variant.get('price'),
                    'inventory_quantity': variant.get('inventory_quantity', 0),
                    'available': variant.get('available', False),
                    'sku': variant.get('sku', ''),
                    'option1': variant.get('option1'),
                    'option2': variant.get('option2'),
                    'option3': variant.get('option3'),
                })

            return {
                'product_title': product_data.get('title'),
                'product_handle': product_data.get('handle'),
                'variants': variants,
                'options': product_data.get('options', []),
                'vendor': product_data.get('vendor'),
                'type': product_data.get('type')
            }

        except Exception as e:
            logging.error(f"Error fetching variants from {product_url}: {e}")
            return {'variants': []}