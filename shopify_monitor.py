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
        self.resolvers[1].nameservers = ['8.8.8.8', '8.8.4.4']

    def _resolve_domain(self, domain: str) -> str:
        if domain in self.dns_cache:
            if time.time() - self.dns_cache[domain]['timestamp'] < 3600:
                return self.dns_cache[domain]['ip']

        for resolver in self.resolvers:
            try:
                answers = resolver.resolve(domain, 'A')
                if answers:
                    ip = answers[0].address
                    self.dns_cache[domain] = {
                        'ip': ip,
                        'timestamp': time.time()
                    }
                    logging.info(f"Successfully resolved {domain} to {ip}")
                    return ip
            except Exception as e:
                logging.warning(f"DNS resolution failed for {domain} using resolver {resolver}: {e}")
                continue

        return None

    def _validate_store_url(self, store_url: str) -> bool:
        try:
            parsed_url = urlparse(store_url)
            domain = parsed_url.netloc
            ip = self._resolve_domain(domain)
            if not ip:
                logging.error(f"Failed to resolve domain {domain}")
                return False

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((ip, 443))
            sock.close()

            if result != 0:
                logging.error(f"Failed to connect to {domain} ({ip}:443)")
                return False

            return True
        except Exception as e:
            logging.error(f"Store validation error for {store_url}: {e}")
            return False

    def fetch_products(self, store_url: str, keywords: List[str]) -> List[Dict]:
        logging.info(f"Fetching products from {store_url} with keywords: {keywords}")

        if not self._validate_store_url(store_url):
            logging.error(f"Store validation failed for {store_url}")
            return []

        if store_url in self.failed_stores:
            retry_count = self.retry_counts.get(store_url, 0)
            backoff = min(300, 2 ** retry_count)
            if time.time() - self.last_request_time < backoff:
                logging.info(f"Skipping {store_url} due to recent failure (backoff: {backoff}s)")
                return []
            self.retry_counts[store_url] = retry_count + 1

        try:
            initial_limit = 150
            products_url = f"{store_url}/products.json?limit={initial_limit}"

            logging.info(f"Making initial request to {products_url}")

            max_retries = 3
            products_data = None

            for attempt in range(max_retries):
                try:
                    with self.rate_limiter:
                        response = self.session.get(
                            products_url,
                            timeout=5,
                            headers={
                                "Accept-Encoding": "gzip, deflate",
                                "Cache-Control": "no-cache"
                            }
                        )
                        response.raise_for_status()
                        products_data = response.json()
                        break
                except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                    if attempt == max_retries - 1:
                        logging.warning(f"API fetch failed, attempting fallback for {store_url}")
                        try:
                            downloaded = trafilatura.fetch_url(store_url)
                            if downloaded:
                                extracted = trafilatura.extract(downloaded, include_comments=False, 
                                                             include_tables=False, no_fallback=False)
                                if extracted:
                                    products_data = self._process_fallback_content(extracted, keywords)
                        except Exception as fallback_error:
                            logging.error(f"Fallback method failed for {store_url}: {fallback_error}")
                    else:
                        time.sleep(1 * (attempt + 1))

            if not products_data:
                logging.error(f"Failed to fetch products from {store_url} after all attempts")
                return []

            matching_products = []
            total_products = len(products_data.get("products", []))
            logging.info(f"Retrieved {total_products} products from initial request")

            lowercase_keywords = [kw.lower() for kw in keywords]
            for product in products_data.get("products", []):
                if self._matches_keywords(product, lowercase_keywords):
                    processed_product = self._process_product(store_url, product)
                    if processed_product:
                        matching_products.append(processed_product)
                        logging.info(f"Found matching product: {product['title']}")

            self.failed_stores.discard(store_url)
            self.retry_counts.pop(store_url, None)

            logging.info(f"Found total of {len(matching_products)} matching products")
            return matching_products

        except Exception as e:
            logging.error(f"Error fetching products from {store_url}: {e}")
            if isinstance(e, (requests.exceptions.ConnectionError, 
                            requests.exceptions.Timeout,
                            requests.exceptions.SSLError)):
                self.failed_stores.add(store_url)
                logging.warning(f"Added {store_url} to failed stores list")
            return []

    def _matches_keywords(self, product: Dict, lowercase_keywords: List[str]) -> bool:
        if not product:
            return False

        searchable_fields = [
            product.get("title", "").lower(),
            product.get("vendor", "").lower(),
            product.get("product_type", "").lower(),
        ]
        searchable_fields.extend([tag.lower() for tag in product.get("tags", [])])

        return any(
            any(keyword in field for keyword in lowercase_keywords)
            for field in searchable_fields
            if field
        )

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