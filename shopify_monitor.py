import requests
import time
import json
from typing import Dict, List
import random
import logging
import socket
import dns.resolver
from urllib.parse import urlparse
import aiohttp
import asyncio
from concurrent.futures import ThreadPoolExecutor
import re
import trafilatura
from aiohttp import TCPConnector, ClientTimeout
from aiohttp.client_exceptions import ClientError

class RateLimiter:
    def __init__(self, rate_limit):
        self.rate_limit = rate_limit
        self.last_request_time = 0
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        async with self._lock:
            current_time = time.time()
            time_passed = current_time - self.last_request_time
            if time_passed < 1 / self.rate_limit:
                jitter = random.uniform(0, 0.5)
                await asyncio.sleep(1/self.rate_limit - time_passed + jitter)
            self.last_request_time = time.time()
            return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class ShopifyMonitor:
    def __init__(self, rate_limit=0.5):
        self.rate_limiter = RateLimiter(rate_limit)
        self.failed_stores = set()
        self.retry_counts = {}
        self.last_request_time = time.time()
        self.dns_cache = {}

        # Enhanced connection pooling settings
        self.max_connections = 100  # Concurrent connection limit
        self.connector = TCPConnector(
            limit=self.max_connections,
            ttl_dns_cache=300,
            ssl=False,
            force_close=False,
            use_dns_cache=True,
            enable_cleanup_closed=True
        )

        # Timeout settings
        self.timeout = ClientTimeout(
            total=30,
            connect=10,
            sock_read=10,
            sock_connect=10
        )

        # Connection pools for different domains
        self._session_pools = {}
        self._session_pool_lock = asyncio.Lock()

        # Thread pool for CPU-bound tasks
        self.thread_pool = ThreadPoolExecutor(max_workers=20)

        # DNS resolvers with fallback
        self.resolvers = [
            dns.resolver.Resolver(),
            dns.resolver.Resolver(configure=False)
        ]
        self.resolvers[1].nameservers = ['8.8.8.8', '8.8.4.4']  # Google DNS backup

        # Initialize logging
        self.logger = logging.getLogger('ShopifyMonitor')

    async def get_session(self, domain: str) -> aiohttp.ClientSession:
        """Get or create a session for a specific domain with connection pooling"""
        async with self._session_pool_lock:
            if domain not in self._session_pools:
                self._session_pools[domain] = aiohttp.ClientSession(
                    connector=self.connector,
                    timeout=self.timeout,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                        'Accept-Encoding': 'gzip, deflate',
                        'Cache-Control': 'no-cache',
                        'Connection': 'keep-alive'
                    }
                )
            return self._session_pools[domain]

    async def _resolve_domain_async(self, domain: str) -> str:
        """Asynchronously resolve domain with caching and multiple DNS servers"""
        if domain in self.dns_cache:
            if time.time() - self.dns_cache[domain]['timestamp'] < 3600:  # 1 hour cache
                return self.dns_cache[domain]['ip']
            del self.dns_cache[domain]

        resolver_list = [
            (dns.resolver.Resolver(), "Default"),
            (dns.resolver.Resolver(configure=False), "Google"),
            (dns.resolver.Resolver(configure=False), "Cloudflare"),
            (dns.resolver.Resolver(configure=False), "OpenDNS")
        ]

        resolver_list[1][0].nameservers = ['8.8.8.8', '8.8.4.4']
        resolver_list[2][0].nameservers = ['1.1.1.1', '1.0.0.1']
        resolver_list[3][0].nameservers = ['208.67.222.222', '208.67.220.220']

        for resolver, name in resolver_list:
            try:
                resolver.timeout = 2.0
                resolver.lifetime = 4.0
                answers = await asyncio.get_event_loop().run_in_executor(
                    self.thread_pool,
                    resolver.resolve,
                    domain,
                    'A'
                )
                if answers:
                    ip = answers[0].address
                    self.dns_cache[domain] = {
                        'ip': ip,
                        'timestamp': time.time()
                    }
                    self.logger.info(f"Resolved {domain} to {ip} using {name} DNS")
                    return ip
            except Exception as e:
                self.logger.warning(f"DNS resolution failed for {domain} using {name}: {e}")
                continue

        self.logger.error(f"All DNS resolution methods failed for {domain}")
        return None

    async def _validate_store_url(self, store_url: str) -> bool:
        """Validate store URL with enhanced error handling"""
        try:
            parsed_url = urlparse(store_url)
            domain = parsed_url.netloc

            ip = await self._resolve_domain_async(domain)
            if not ip:
                return False

            try:
                reader, writer = await asyncio.open_connection(ip, 443)
                writer.close()
                await writer.wait_closed()
                return True
            except Exception as e:
                self.logger.error(f"Connection test failed for {domain} ({ip}:443): {e}")
                return False

        except Exception as e:
            self.logger.error(f"Store validation error for {store_url}: {e}")
            return False

    async def async_fetch_products(self, store_url: str, keywords: List[str]) -> List[Dict]:
        """Fetch products with improved concurrency and error handling"""
        self.logger.info(f"Fetching products from {store_url} with keywords: {keywords}")

        if not await self._validate_store_url(store_url):
            self.logger.error(f"Store validation failed for {store_url}")
            return []

        if store_url in self.failed_stores:
            retry_count = self.retry_counts.get(store_url, 0)
            backoff = min(300, 2 ** retry_count)  # Cap at 5 minutes
            if time.time() - self.last_request_time < backoff:
                self.logger.info(f"Skipping {store_url} due to recent failure (backoff: {backoff}s)")
                return []
            self.retry_counts[store_url] = retry_count + 1

        domain = urlparse(store_url).netloc
        session = await self.get_session(domain)

        try:
            initial_limit = 250  # Increased initial fetch
            products_url = f"{store_url}/products.json?limit={initial_limit}"

            self.logger.info(f"Making initial request to {products_url}")

            async with self.rate_limiter:
                async with session.get(products_url, timeout=self.timeout) as response:
                    if response.status == 200:
                        products_data = await response.json()
                    elif response.status == 429:  # Rate limited
                        retry_after = int(response.headers.get('Retry-After', 5))
                        self.logger.warning(f"Rate limited by {domain}, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        return await self.async_fetch_products(store_url, keywords)
                    else:
                        self.logger.error(f"Failed request: {response.status} - {await response.text()}")
                        return []

            if not products_data:
                return []

            matching_products = []
            total_products = len(products_data.get("products", []))
            self.logger.info(f"Retrieved {total_products} products from initial request")

            # Process products in parallel batches
            batch_size = 50
            products = products_data.get("products", [])
            batches = [products[i:i + batch_size] for i in range(0, len(products), batch_size)]

            async def process_batch(batch):
                results = []
                for product in batch:
                    if await self._matches_keywords(product, keywords):
                        processed = await self._process_product(store_url, product)
                        if processed:
                            results.append(processed)
                return results

            # Process batches concurrently
            tasks = [process_batch(batch) for batch in batches]
            batch_results = await asyncio.gather(*tasks)

            for batch_result in batch_results:
                matching_products.extend(batch_result)

            self.failed_stores.discard(store_url)
            self.retry_counts.pop(store_url, None)

            self.logger.info(f"Found {len(matching_products)} matching products")
            return matching_products

        except Exception as e:
            self.logger.error(f"Error fetching products from {store_url}: {e}", exc_info=True)
            if isinstance(e, (ClientError, asyncio.TimeoutError)):
                self.failed_stores.add(store_url)
            return []

    async def _matches_keywords(self, product: Dict, keywords: List[str]) -> bool:
        """Asynchronous keyword matching with improved accuracy"""
        if not product:
            return False

        # Prepare searchable text
        title = product.get("title", "").lower()
        vendor = product.get("vendor", "").lower()
        product_type = product.get("product_type", "").lower()
        tags = [tag.lower() for tag in product.get("tags", [])]
        searchable_text = f"{title} {vendor} {product_type} {' '.join(tags)}"

        # Convert keywords to lowercase once
        lowercase_keywords = [kw.lower() for kw in keywords]

        for keyword in lowercase_keywords:
            keyword_parts = keyword.split()
            if len(keyword_parts) > 1:
                # Multi-word keyword matching
                all_parts_found = True
                current_pos = 0
                for part in keyword_parts:
                    pos = searchable_text.find(part, current_pos)
                    if pos == -1:
                        all_parts_found = False
                        break
                    current_pos = pos + len(part)
                if all_parts_found:
                    return True
            else:
                # Single-word keyword matching with word boundaries
                pattern = f"\\b{re.escape(keyword)}\\b"
                if re.search(pattern, searchable_text):
                    return True

        return False

    async def _process_product(self, store_url: str, product: Dict) -> Dict:
        """Process product data asynchronously"""
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
            self.logger.error(f"Error processing product {product.get('title', 'Unknown')}: {e}")
            return None

    async def cleanup(self):
        """Cleanup resources"""
        for session in self._session_pools.values():
            await session.close()
        await self.connector.close()
        self.thread_pool.shutdown(wait=True)