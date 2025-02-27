import requests
import time
import json
from typing import Dict, List
import random
import logging
import socket
from urllib.parse import urlparse
from requests.exceptions import RequestException
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
                extra={'extra_fields': {
                    'sleep_time': sleep_time,
                    'backoff_multiplier': self.backoff_multiplier,
                    'total_requests': self.total_requests,
                    'failed_requests': self.failed_requests
                }}
            )
            time.sleep(sleep_time)

        self.total_requests += 1
        self.last_request_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type and "429" in str(exc_val):
            self.consecutive_429s += 1
            self.failed_requests += 1
            self.backoff_multiplier = min(8.0, self.backoff_multiplier * 2)
            logger.warning(
                "Rate limit exceeded",
                extra={'extra_fields': {
                    'consecutive_429s': self.consecutive_429s,
                    'backoff_multiplier': self.backoff_multiplier,
                    'total_requests': self.total_requests,
                    'failed_requests': self.failed_requests
                }}
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
        self.failed_stores = {}  # Store URL -> {last_failure: timestamp, failures: count, backoff: seconds}
        self.store_stats = {}
        self.dns_cache = {}
        self.dns_cache_ttl = 300  # 5 minutes TTL for DNS cache

    def _validate_domain(self, url: str) -> bool:
        """Validate domain accessibility with DNS lookup and caching"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc

            # Check DNS cache first
            cache_entry = self.dns_cache.get(domain)
            current_time = time.time()

            if cache_entry and current_time - cache_entry['timestamp'] < self.dns_cache_ttl:
                return cache_entry['valid']

            # Perform new DNS lookup
            socket.gethostbyname(domain)
            self.dns_cache[domain] = {'valid': True, 'timestamp': current_time}
            return True

        except socket.gaierror as e:
            logger.error(f"DNS resolution failed for {url}: {e}")
            self.dns_cache[parsed.netloc] = {'valid': False, 'timestamp': current_time}
            return False
        except Exception as e:
            logger.error(f"Domain validation error for {url}: {e}")
            return False

    def _should_retry_store(self, store_url: str) -> bool:
        """Determine if we should retry a failed store based on exponential backoff"""
        if store_url not in self.failed_stores:
            return True

        store_data = self.failed_stores[store_url]
        current_time = time.time()
        time_since_failure = current_time - store_data['last_failure']

        if time_since_failure >= store_data['backoff']:
            return True

        logger.info(f"Skipping {store_url} - Cooling down for {store_data['backoff'] - time_since_failure:.1f}s")
        return False

    def _update_store_failure(self, store_url: str):
        """Update failure statistics for a store"""
        current_time = time.time()
        if store_url not in self.failed_stores:
            self.failed_stores[store_url] = {
                'failures': 1,
                'last_failure': current_time,
                'backoff': 60  # Start with 1 minute backoff
            }
        else:
            store_data = self.failed_stores[store_url]
            store_data['failures'] += 1
            store_data['last_failure'] = current_time
            # Exponential backoff with max of 1 hour
            store_data['backoff'] = min(3600, store_data['backoff'] * 2)

    def fetch_products(self, store_url: str, keywords: List[str]) -> List[Dict]:
        """Fetches products from a Shopify store with improved error handling"""
        if store_url not in self.store_stats:
            self._init_store_stats(store_url)

        stats = self.store_stats[store_url]
        stats['total_requests'] += 1

        # Check if we should skip this store due to recent failures
        if not self._should_retry_store(store_url):
            return []

        # Validate domain before making request
        if not self._validate_domain(store_url):
            self._update_store_failure(store_url)
            log_scraping_error(store_url, Exception("DNS resolution failed"), {
                'store_stats': stats,
                'failed_stores': self.failed_stores
            })
            return []

        try:
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

            # Reset failure data on success
            if store_url in self.failed_stores:
                del self.failed_stores[store_url]
                logger.info(f"Store {store_url} recovered from failure state")

            # Process matching products
            matching_products = []
            lowercase_keywords = [kw.lower() for kw in keywords]

            for product in data.get("products", []):
                try:
                    product_title_lower = product["title"].lower()
                    if any(keyword in product_title_lower for keyword in lowercase_keywords):
                        processed_product = self._process_product(store_url, product)
                        if processed_product:
                            matching_products.append(processed_product)
                except Exception as e:
                    log_scraping_error(store_url, e, {
                        'product_title': product.get('title', 'Unknown'),
                        'error_location': 'product_processing'
                    })

            stats['last_success'] = time.time()
            return matching_products

        except RequestException as e:
            self._update_store_failure(store_url)
            log_scraping_error(store_url, e, {
                'store_stats': stats,
                'failed_stores': self.failed_stores,
                'rate_limiter_stats': {
                    'total_requests': self.rate_limiter.total_requests,
                    'failed_requests': self.rate_limiter.failed_requests,
                    'backoff_multiplier': self.rate_limiter.backoff_multiplier
                }
            })
            return []

    def _process_product(self, store_url: str, product: Dict) -> Dict:
        """Process raw product data into formatted structure"""
        try:
            variants = product.get("variants", [])
            sizes = {}
            variant_ids = {}

            for variant in variants:
                if variant.get("available"):
                    size = str(variant.get("title"))
                    inventory = variant.get("inventory_quantity", 1)
                    sizes[size] = inventory
                    variant_ids[size] = str(variant.get("id", ""))

            return {
                "title": product["title"],
                "url": f"{store_url}/products/{product['handle']}",
                "price": variants[0].get("price") if variants else "N/A",
                "image_url": product.get("images", [{}])[0].get("src", ""),
                "sizes": sizes,
                "variants": variant_ids,
                "full_size_run": "Bot 1 FSR" if bool(sizes) else "OOS"
            }
        except Exception as e:
            log_scraping_error(store_url, e, {
                'product_title': product.get('title', 'Unknown'),
                'error_location': '_process_product'
            })
            return {}

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
            product_data = None  # Initialize product_data

            for attempt in range(max_retries):
                try:
                    with self.rate_limiter:
                        response = self.session.get(product_url, timeout=10)
                        response.raise_for_status()
                        response_data = response.json()
                        product_data = response_data.get('product', {})
                        if product_data:  # Only break if we got valid data
                            break
                        logger.warning(f"Empty product data received for {product_url}")
                except requests.exceptions.RequestException as e:
                    log_scraping_error(product_url, e, {
                        'attempt': attempt + 1,
                        'max_retries': max_retries
                    })
                    if attempt == max_retries - 1:
                        logger.error(f"Failed to fetch product data after {max_retries} attempts")
                        return {'variants': []}
                    time.sleep(1 * (attempt + 1))

            if not product_data:
                logger.warning(f"No valid product data found for {product_url}")
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