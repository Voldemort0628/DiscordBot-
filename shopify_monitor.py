import asyncio
import aiohttp
import json
import time
import random
from typing import Dict, List, Optional, Set
from datetime import datetime
from collections import deque
import logging
import socket
from urllib.parse import urlparse
from requests.exceptions import RequestException
from config import USER_AGENT, SHOPIFY_RATE_LIMIT, MAX_PRODUCTS
from logger_config import scraper_logger, log_scraping_error
from proxy_manager import ProxyManager

logger = scraper_logger

class ProxyManager:
    def __init__(self):
        self.proxies: List[str] = []
        self.failed_proxies: Set[str] = set()
        self.proxy_stats: Dict[str, Dict] = {}
        self.current_proxy_index = 0


    def add_proxies_from_list(self, proxy_list: List[str]):
        self.proxies.extend(proxy_list)

    def get_next_proxy(self) -> Optional[str]:
        """Get next working proxy with stats tracking"""
        if not self.proxies:
            return None

        working_proxies = [p for p in self.proxies if p not in self.failed_proxies]
        if not working_proxies:
            # Reset failed proxies if all are failed
            self.failed_proxies.clear()
            working_proxies = self.proxies

        proxy = working_proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(working_proxies)
        if proxy not in self.proxy_stats:
            self.proxy_stats[proxy] = {'success': 0, 'failures': 0}
        return proxy

    def mark_proxy_failed(self, proxy: str):
        """Mark a proxy as failed"""
        if proxy:
            self.failed_proxies.add(proxy)
            if proxy in self.proxy_stats:
                self.proxy_stats[proxy]['failures'] += 1

    def mark_proxy_success(self, proxy: str):
        """Mark a proxy request as successful"""
        if proxy and proxy in self.proxy_stats:
            self.proxy_stats[proxy]['success'] += 1
            self.failed_proxies.discard(proxy)

    def get_stats(self):
        return self.proxy_stats


class SessionManager:
    def __init__(self, proxy_manager: Optional['ProxyManager'] = None):
        self.proxy_manager = proxy_manager
        self.sessions: Dict[str, aiohttp.ClientSession] = {}
        self._proxy_url: Optional[str] = None

    async def get_session(self, store_url: str) -> aiohttp.ClientSession:
        """Get or create a session for a store with proxy rotation"""
        if store_url not in self.sessions or self.sessions[store_url].closed:
            if self.proxy_manager:
                self._proxy_url = self.proxy_manager.get_next_proxy()

            timeout = aiohttp.ClientTimeout(total=10, connect=5)
            connector = aiohttp.TCPConnector(ssl=False)

            self.sessions[store_url] = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    'User-Agent': USER_AGENT,
                    'Accept': 'application/json',
                    'Accept-Encoding': 'gzip, deflate',
                },
                proxy=self._proxy_url
            )
        return self.sessions[store_url]

    def mark_proxy_failed(self):
        """Mark current proxy as failed"""
        if self.proxy_manager and self._proxy_url:
            self.proxy_manager.mark_proxy_failed(self._proxy_url)

    def mark_proxy_success(self):
        """Mark current proxy as successful"""
        if self.proxy_manager and self._proxy_url:
            self.proxy_manager.mark_proxy_success(self._proxy_url)

    async def close_all(self):
        """Close all sessions"""
        for session in self.sessions.values():
            if not session.closed:
                await session.close()
        self.sessions.clear()

class ProductTracker:
    def __init__(self, ttl: int = 3600):
        self.seen_products = {}
        self.ttl = ttl
        self.stock_changes = deque(maxlen=1000)  # Track recent stock changes

    def is_new_or_changed(self, identifier: str, current_stock: int) -> bool:
        """Check if product is new or stock has changed"""
        current_time = time.time()

        # Clean expired entries
        self.seen_products = {k: v for k, v in self.seen_products.items()
                            if current_time - v['timestamp'] <= self.ttl}

        if identifier not in self.seen_products:
            self.seen_products[identifier] = {
                'timestamp': current_time,
                'stock': current_stock
            }
            return True

        previous = self.seen_products[identifier]
        if previous['stock'] != current_stock:
            # Track stock change
            self.stock_changes.append({
                'identifier': identifier,
                'previous': previous['stock'],
                'current': current_stock,
                'timestamp': current_time
            })
            previous['stock'] = current_stock
            previous['timestamp'] = current_time
            return True

        return False

class ShopifyMonitor:
    def __init__(self, rate_limit: float = 0.5, proxy_list: Optional[List[str]] = None):
        self.rate_limit = rate_limit
        self.proxy_manager = ProxyManager()
        if proxy_list:
            self.proxy_manager.add_proxies_from_list(proxy_list)
        self.session_manager = SessionManager(self.proxy_manager)
        self.product_tracker = ProductTracker()
        self.store_stats = {}
        self.last_request_times: Dict[str, float] = {}
        self.request_windows: Dict[str, deque] = {}
        self.max_requests_per_window = 25
        self.window_size = 30  # 30 second window
        self.failed_stores = {}  # Store URL -> {last_failure: timestamp, failures: count, backoff: seconds}
        self.dns_cache = {}
        self.dns_cache_ttl = 300  # 5 minutes TTL for DNS cache

    def _init_store_stats(self, store_url: str):
        """Initialize store statistics"""
        if store_url not in self.store_stats:
            self.store_stats[store_url] = {
                'total_requests': 0,
                'successful_requests': 0,
                'failed_requests': 0,
                'last_success': None,
                'last_failure': None,
                'recent_errors': deque(maxlen=100)
            }

    async def _wait_for_rate_limit(self, store_url: str):
        """Advanced rate limiting with sliding window"""
        current_time = time.time()

        # Initialize request window if needed
        if store_url not in self.request_windows:
            self.request_windows[store_url] = deque()

        window = self.request_windows[store_url]

        # Remove old requests from window
        while window and window[0] < current_time - self.window_size:
            window.popleft()

        # Wait if too many requests in window
        if len(window) >= self.max_requests_per_window:
            wait_time = window[0] + self.window_size - current_time
            if wait_time > 0:
                logger.debug(f"Rate limit wait for {store_url}: {wait_time:.2f}s")
                await asyncio.sleep(wait_time)

        # Add current request to window
        window.append(current_time)

    async def fetch_products(self, store_url: str, keywords: List[str]) -> List[Dict]:
        """Fetch and process products from a store"""
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
            await self._wait_for_rate_limit(store_url)
            session = await self.session_manager.get_session(store_url)

            async with session.get(f"{store_url}/products.json") as response:
                response.raise_for_status()
                data = await response.json()

                self.session_manager.mark_proxy_success()
                stats['successful_requests'] += 1
                stats['last_success'] = time.time()

                matching_products = []
                lowercase_keywords = [k.lower() for k in keywords]

                for product in data.get('products', []):
                    try:
                        if any(k in product['title'].lower() for k in lowercase_keywords):
                            processed = await self._process_product(store_url, product)
                            if processed:
                                identifier = f"{store_url}-{product['id']}"
                                if self.product_tracker.is_new_or_changed(
                                    identifier, 
                                    processed.get('stock', 0)
                                ):
                                    matching_products.append(processed)
                    except Exception as e:
                        log_scraping_error(store_url, e, {
                            'product': product.get('title', 'Unknown'),
                            'error_location': 'product_processing'
                        })

                return matching_products

        except aiohttp.ClientError as e:
            stats['failed_requests'] += 1
            stats['last_failure'] = time.time()
            stats['recent_errors'].append({
                'error': str(e),
                'timestamp': time.time()
            })

            self.session_manager.mark_proxy_failed()
            log_scraping_error(store_url, e, {
                'stats': stats,
                'proxy_stats': self.proxy_manager.get_stats() if self.proxy_manager else None
            })
            return []

    async def _process_product(self, store_url: str, product: Dict) -> Optional[Dict]:
        """Process raw product data into structured format"""
        try:
            variants = product.get('variants', [])
            sizes = {}
            variant_ids = {}
            total_stock = 0

            for variant in variants:
                if variant.get('available'):
                    size = str(variant.get('title'))
                    inventory = variant.get('inventory_quantity', 1)
                    total_stock += inventory
                    sizes[size] = inventory
                    variant_ids[size] = str(variant.get('id', ''))

            return {
                'title': product['title'],
                'url': f"{store_url}/products/{product['handle']}",
                'price': variants[0].get('price') if variants else 'N/A',
                'image_url': product.get('images', [{}])[0].get('src', ''),
                'stock': total_stock,
                'sizes': sizes,
                'variants': variant_ids,
                'full_size_run': 'Bot 1 FSR' if total_stock > 0 else 'OOS'
            }

        except Exception as e:
            log_scraping_error(store_url, e, {
                'product': product.get('title', 'Unknown'),
                'error_location': '_process_product'
            })
            return None

    async def close(self):
        """Cleanup resources"""
        await self.session_manager.close_all()

    def _validate_domain(self, url: str, max_retries: int = 3) -> bool:
        """Validate domain accessibility with DNS lookup, caching and retries"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc

            # Check DNS cache first
            cache_entry = self.dns_cache.get(domain)
            current_time = time.time()

            if cache_entry and current_time - cache_entry['timestamp'] < self.dns_cache_ttl:
                return cache_entry['valid']

            # Try DNS resolution with retries
            for attempt in range(max_retries):
                try:
                    socket.gethostbyname(domain)
                    self.dns_cache[domain] = {'valid': True, 'timestamp': current_time}
                    return True
                except socket.gaierror as e:
                    if attempt == max_retries - 1:
                        logger.error(f"DNS resolution failed for {url} after {max_retries} attempts: {e}")
                        self.dns_cache[domain] = {'valid': False, 'timestamp': current_time}
                        return False
                    time.sleep(1 * (attempt + 1))  # Exponential backoff

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

class RetryWithProxy(Retry):
    def __init__(self, *args, **kwargs):
        self.proxy_list = kwargs.pop('proxy_list', [])
        self.current_proxy_index = 0
        super().__init__(*args, **kwargs)

    def get_next_proxy(self):
        if not self.proxy_list:
            return None
        proxy = self.proxy_list[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxy_list)
        return proxy

    def new(self, **kw):
        new_retry = super().new(**kw)
        new_retry.proxy_list = self.proxy_list
        new_retry.current_proxy_index = self.current_proxy_index
        return new_retry

async def main():
    # Example usage: Replace with your actual store URLs, keywords, and proxy list
    store_urls = ["https://example-store-1.myshopify.com", "https://example-store-2.myshopify.com"]
    keywords = ["tshirt", "jacket"]
    proxy_list = ["http://your_proxy_1:port", "http://your_proxy_2:port"] #Replace with your proxy list

    monitor = ShopifyMonitor(rate_limit=1, proxy_list=proxy_list)
    async with monitor:
        tasks = [monitor.fetch_products(url, keywords) for url in store_urls]
        results = await asyncio.gather(*tasks)
        print(results)
        #Further processing of the results
        # Example:  Save to a database, send to webhook


if __name__ == "__main__":
    asyncio.run(main())