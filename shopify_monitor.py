import requests
import time
import json
from typing import Dict, List
import random
import logging
from config import USER_AGENT, SHOPIFY_RATE_LIMIT, MAX_PRODUCTS
from logger_config import scraper_logger, log_scraping_error

logger = scraper_logger

class RateLimiter:
    def __init__(self, rate_limit):
        self.rate_limit = rate_limit
        self.last_request_time = 0
        self.consecutive_429s = 0
        self.backoff_multiplier = 1.0
        self.total_requests = 0
        self.failed_requests = 0

    def __enter__(self):
        current_time = time.time()
        time_passed = current_time - self.last_request_time

        # Calculate delay based on rate limit and backoff
        base_delay = 1 / self.rate_limit
        actual_delay = base_delay * self.backoff_multiplier

        if time_passed < actual_delay:
            # Add small random jitter (0-100ms) to prevent synchronized requests
            jitter = random.uniform(0, 0.1)
            sleep_time = actual_delay - time_passed + jitter
            logger.debug(
                "Rate limiting",
                extra={
                    'extra_fields': {
                        'sleep_time': sleep_time,
                        'backoff_multiplier': self.backoff_multiplier,
                        'total_requests': self.total_requests,
                        'failed_requests': self.failed_requests
                    }
                }
            )
            time.sleep(sleep_time)

        self.total_requests += 1
        self.last_request_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Adjust backoff based on response
        if exc_type and "429" in str(exc_val):
            self.consecutive_429s += 1
            self.failed_requests += 1
            self.backoff_multiplier = min(8.0, self.backoff_multiplier * 2)
            logger.warning(
                "Rate limit exceeded",
                extra={
                    'extra_fields': {
                        'consecutive_429s': self.consecutive_429s,
                        'backoff_multiplier': self.backoff_multiplier,
                        'total_requests': self.total_requests,
                        'failed_requests': self.failed_requests
                    }
                }
            )
        else:
            self.consecutive_429s = max(0, self.consecutive_429s - 1)
            if self.consecutive_429s == 0:
                self.backoff_multiplier = max(1.0, self.backoff_multiplier * 0.75)

class ShopifyMonitor:
    def __init__(self, rate_limit=0.5):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'application/json',
            'Connection': 'keep-alive',
            'Accept-Encoding': 'gzip, deflate'
        })
        self.rate_limiter = RateLimiter(rate_limit)
        self.failed_stores = set()
        self.retry_counts = {}
        self.last_request_time = time.time()
        self.store_stats = {}

    def _init_store_stats(self, store_url: str):
        """Initialize or reset statistics for a store"""
        self.store_stats[store_url] = {
            'total_requests': 0,
            'failed_requests': 0,
            'last_success': None,
            'last_failure': None,
            'errors': {}
        }

    def get_product_variants(self, product_url):
        """Fetch specific product variants from a Shopify product URL"""
        try:
            # Convert product URL to JSON endpoint
            if not product_url.endswith('.json'):
                if product_url.endswith('/'):
                    product_url = product_url[:-1]
                product_url = product_url + '.json'

            # Fetch product data with retry logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with self.rate_limiter:
                        response = self.session.get(product_url, timeout=10)
                        response.raise_for_status()
                        product_data = response.json().get('product', {})
                        break
                except requests.exceptions.RequestException as e:
                    log_scraping_error(product_url, e, {
                        'attempt': attempt + 1,
                        'max_retries': max_retries
                    })
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(1 * (attempt + 1))

            if not product_data:
                return {'variants': []}

            # Extract variant information
            variants = []
            for variant in product_data.get('variants', []):
                variants.append({
                    'id': variant.get('id'),
                    'title': variant.get('title'),
                    'price': variant.get('price'),
                    'inventory_quantity': variant.get('inventory_quantity', 0),
                    'available': variant.get('available', False)
                })

            return {
                'product_title': product_data.get('title'),
                'product_handle': product_data.get('handle'),
                'variants': variants
            }

        except Exception as e:
            log_scraping_error(product_url, e)
            return {'variants': []}

    def fetch_products(self, store_url: str, keywords: List[str]) -> List[Dict]:
        """Fetches products from a Shopify store matching given keywords"""
        if store_url not in self.store_stats:
            self._init_store_stats(store_url)

        stats = self.store_stats[store_url]
        stats['total_requests'] += 1

        if store_url in self.failed_stores:
            retry_count = self.retry_counts.get(store_url, 0)
            backoff = min(300, 2 ** retry_count)  # Max 5 minutes backoff
            if time.time() - self.last_request_time < backoff:
                return []
            self.retry_counts[store_url] = retry_count + 1

        try:
            # Use a smaller initial limit for faster responses
            initial_limit = 50
            products_url = f"{store_url}/products.json?limit={initial_limit}"

            with self.rate_limiter:
                response = self.session.get(
                    products_url,
                    timeout=10,
                    headers={'Cache-Control': 'no-cache'}
                )
                response.raise_for_status()
                data = response.json()

            matching_products = []
            lowercase_keywords = [kw.lower() for kw in keywords]

            for product in data.get("products", []):
                product_title_lower = product["title"].lower()
                if any(keyword in product_title_lower for keyword in lowercase_keywords):
                    processed_product = self._process_product(store_url, product)
                    if processed_product:
                        matching_products.append(processed_product)

            # Update success statistics
            stats['last_success'] = time.time()
            self.failed_stores.discard(store_url)
            self.retry_counts.pop(store_url, None)
            return matching_products

        except requests.exceptions.RequestException as e:
            # Update failure statistics
            stats['failed_requests'] += 1
            stats['last_failure'] = time.time()
            error_type = type(e).__name__
            stats['errors'][error_type] = stats['errors'].get(error_type, 0) + 1

            log_scraping_error(store_url, e, {
                'store_stats': stats,
                'rate_limiter_stats': {
                    'total_requests': self.rate_limiter.total_requests,
                    'failed_requests': self.rate_limiter.failed_requests,
                    'backoff_multiplier': self.rate_limiter.backoff_multiplier
                }
            })

            if isinstance(e, (requests.exceptions.ConnectionError,
                            requests.exceptions.Timeout,
                            requests.exceptions.SSLError)):
                self.failed_stores.add(store_url)
            return []

    def _process_product(self, store_url: str, product: Dict) -> Dict:
        """Process raw product data into formatted structure"""
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
                "full_size_run": "Bot 1 FSR" if stock > 0 else "OOS"
            }
        except Exception as e:
            log_scraping_error(store_url, e, {
                'product_title': product.get('title', 'Unknown'),
                'error_location': '_process_product'
            })
            return {}