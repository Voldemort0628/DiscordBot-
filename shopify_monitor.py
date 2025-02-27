import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Optional, Set
from datetime import datetime
from collections import deque
import logging
from urllib.parse import urlparse
from aiohttp import ClientTimeout, TCPConnector, ClientError
from config import USER_AGENT, SHOPIFY_RATE_LIMIT, MAX_PRODUCTS
from logger_config import scraper_logger
from protection_bypass import ProtectionBypass

logger = scraper_logger

class DomainRateLimiter:
    """Per-domain rate limiting with dynamic backoff"""
    def __init__(self, default_rate: float = 1.0):
        self.default_rate = default_rate
        self.domain_rates: Dict[str, float] = {}
        self.last_request: Dict[str, float] = {}
        self.backoff_multiplier: Dict[str, float] = {}
        self.failed_domains: Dict[str, Dict] = {}

    async def acquire(self, domain: str):
        """Wait for rate limit slot with dynamic backoff"""
        current_time = time.time()

        # Check if domain is in cooldown
        if domain in self.failed_domains:
            failed_data = self.failed_domains[domain]
            if current_time < failed_data['next_try']:
                raise Exception(f"Domain {domain} in cooldown for {failed_data['next_try'] - current_time:.1f}s")

        rate = self.domain_rates.get(domain, self.default_rate)
        last_time = self.last_request.get(domain, 0)
        multiplier = self.backoff_multiplier.get(domain, 1.0)

        delay = max(0, (1.0 / rate) * multiplier - (current_time - last_time))
        if delay > 0:
            await asyncio.sleep(delay)

        self.last_request[domain] = current_time

    def mark_failure(self, domain: str, error_type: str):
        """Mark domain failure with exponential backoff"""
        current_time = time.time()

        if domain not in self.failed_domains:
            self.failed_domains[domain] = {
                'failures': 0,
                'next_try': current_time,
                'backoff': 5  # Start with 5 second backoff
            }

        data = self.failed_domains[domain]
        data['failures'] += 1

        # Exponential backoff based on error type
        if error_type == '404':  # Invalid endpoint
            data['backoff'] = min(3600, data['backoff'] * 2)  # Max 1 hour
        elif error_type == '429':  # Rate limit
            data['backoff'] = min(300, data['backoff'] * 1.5)  # Max 5 minutes
        elif error_type == 'dns':  # DNS failure
            data['backoff'] = min(1800, data['backoff'] * 2)  # Max 30 minutes
        else:
            data['backoff'] = min(600, data['backoff'] * 1.5)  # Max 10 minutes

        data['next_try'] = current_time + data['backoff']
        logger.warning(f"Domain {domain} backed off for {data['backoff']}s after {error_type} error")

    def mark_success(self, domain: str):
        """Mark successful request and reduce backoff"""
        if domain in self.failed_domains:
            self.failed_domains[domain]['failures'] = max(0, self.failed_domains[domain]['failures'] - 1)
            if self.failed_domains[domain]['failures'] == 0:
                del self.failed_domains[domain]

class ProxyManager:
    """Advanced proxy management with health tracking"""
    def __init__(self, proxies: Optional[List[str]] = None):
        self.proxies = proxies or []
        self.health_scores: Dict[str, float] = {}
        self.error_counts: Dict[str, int] = {}
        self.last_used: Dict[str, float] = {}
        self.in_use: Set[str] = set()

    async def get_proxy(self) -> Optional[str]:
        """Get best available proxy"""
        if not self.proxies:
            return None

        available = [p for p in self.proxies if p not in self.in_use]
        if not available:
            await asyncio.sleep(1)  # Wait if all proxies are in use
            return await self.get_proxy()

        proxy = max(available, key=lambda p: (
            self.health_scores.get(p, 0.5),
            -self.last_used.get(p, 0)
        ))

        self.in_use.add(proxy)
        self.last_used[proxy] = time.time()
        return proxy

    def release_proxy(self, proxy: str, success: bool, error_type: Optional[str] = None):
        """Release proxy and update health metrics"""
        if proxy not in self.proxies:
            return

        self.in_use.discard(proxy)
        score = self.health_scores.get(proxy, 0.5)

        if success:
            self.health_scores[proxy] = min(1.0, score + 0.1)
            self.error_counts[proxy] = 0
        else:
            # Adjust penalty based on error type
            penalty = 0.1
            if error_type == '429':  # Rate limit
                penalty = 0.05
            elif error_type in ('403', '404'):  # Access denied
                penalty = 0.2
            elif error_type == 'timeout':
                penalty = 0.15

            self.health_scores[proxy] = max(0.0, score - penalty)
            self.error_counts[proxy] = self.error_counts.get(proxy, 0) + 1

class ProductTracker:
    """Track product changes with deduplication"""
    def __init__(self, ttl: int = 3600):
        self.seen_products: Dict[str, Dict] = {}
        self.ttl = ttl
        self.changes = deque(maxlen=1000)

    def is_new_or_changed(self, product: Dict) -> bool:
        """Check if product is new or has changed"""
        current_time = time.time()
        product_id = str(product.get('id'))

        # Clean expired entries
        self.seen_products = {
            k: v for k, v in self.seen_products.items()
            if current_time - v['timestamp'] <= self.ttl
        }

        # Generate hash of important fields
        state_hash = hash(json.dumps({
            'title': product.get('title'),
            'price': product.get('price'),
            'available': product.get('available'),
            'variants': product.get('variants', [])
        }, sort_keys=True))

        if product_id not in self.seen_products:
            self.seen_products[product_id] = {
                'timestamp': current_time,
                'hash': state_hash
            }
            return True

        previous = self.seen_products[product_id]
        if previous['hash'] != state_hash:
            self.changes.append({
                'product_id': product_id,
                'timestamp': current_time,
                'previous_hash': previous['hash'],
                'new_hash': state_hash
            })
            previous.update({
                'timestamp': current_time,
                'hash': state_hash
            })
            return True

        return False

class ShopifyMonitor:
    """Advanced Shopify product monitor with robust error handling"""
    def __init__(self, rate_limit: float = 1.0, proxies: Optional[List[str]] = None):
        self.rate_limiter = DomainRateLimiter(rate_limit)
        self.proxy_manager = ProxyManager(proxies)
        self.session: Optional[aiohttp.ClientSession] = None
        self.product_tracker = ProductTracker()
        self.protection_bypass = ProtectionBypass()
        self.verified_stores: Set[str] = set()

    async def setup(self):
        """Initialize monitor resources"""
        if self.session is None:
            timeout = ClientTimeout(total=30, connect=10)
            connector = TCPConnector(
                ssl=False,
                limit=10,
                force_close=True,
                enable_cleanup_closed=True
            )
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={'User-Agent': USER_AGENT}
            )

    async def close(self):
        """Cleanup resources"""
        if self.session and not self.session.closed:
            await self.session.close()

    def _get_api_url(self, store_url: str) -> str:
        """Generate API endpoint URL"""
        base = store_url.rstrip('/')
        if not base.startswith(('http://', 'https://')):
            base = f'https://{base}'
        return f"{base}/products.json"

    async def verify_store(self, store_url: str) -> bool:
        """Verify store accessibility and protection"""
        try:
            if store_url in self.verified_stores:
                return True

            if await self.protection_bypass.verify_store(self.session, store_url):
                self.verified_stores.add(store_url)
                return True

            return False

        except Exception as e:
            logger.error(f"Error verifying store {store_url}: {e}")
            return False

    async def get_store_products(self, store_url: str, retries: int = 3) -> Optional[List[Dict]]:
        """Fetch products from store with retries and error handling"""
        await self.setup()
        domain = urlparse(store_url).netloc

        # Verify store first
        if not await self.verify_store(store_url):
            logger.error(f"Failed to verify store {store_url}")
            return None

        api_url = self._get_api_url(store_url)

        for attempt in range(retries):
            try:
                # Get proxy and wait for rate limit
                proxy = await self.proxy_manager.get_proxy()
                await self.rate_limiter.acquire(domain)

                # Get request parameters with protection bypass
                request_params = self.protection_bypass.get_request_params(store_url)
                if proxy:
                    request_params['proxy'] = proxy

                # Make request
                async with self.session.get(api_url, **request_params) as response:
                    if response.status == 404:
                        logger.error(f"Invalid API endpoint for {store_url}")
                        self.rate_limiter.mark_failure(domain, '404')
                        return None

                    if response.status == 429:
                        logger.warning(f"Rate limited on {store_url}")
                        self.rate_limiter.mark_failure(domain, '429')
                        if proxy:
                            self.proxy_manager.release_proxy(proxy, False, '429')
                        continue

                    if response.status >= 400:
                        logger.error(f"HTTP {response.status} from {store_url}")
                        self.rate_limiter.mark_failure(domain, str(response.status))
                        if proxy:
                            self.proxy_manager.release_proxy(proxy, False, str(response.status))
                        continue

                    # Success
                    self.rate_limiter.mark_success(domain)
                    if proxy:
                        self.proxy_manager.release_proxy(proxy, True)

                    try:
                        data = await response.json()
                        return data.get('products', [])
                    except ValueError as e:
                        logger.error(f"Invalid JSON from {store_url}: {e}")
                        self.rate_limiter.mark_failure(domain, 'json')
                        continue

            except Exception as e:
                logger.error(f"Error fetching {store_url} (attempt {attempt + 1}): {e}")
                self.rate_limiter.mark_failure(domain, 'unknown')
                if proxy:
                    self.proxy_manager.release_proxy(proxy, False, 'unknown')

                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                continue

        return None

    def _process_product(self, product: Dict) -> Optional[Dict]:
        """Process raw product data into structured format"""
        try:
            variants = product.get('variants', [])
            if not variants:
                return None

            # Calculate availability and stock levels
            total_stock = 0
            sizes = {}
            for variant in variants:
                if variant.get('available'):
                    size = str(variant.get('title', 'One Size'))
                    inventory = variant.get('inventory_quantity', 0)
                    total_stock += inventory
                    sizes[size] = inventory

            if not total_stock:
                return None

            return {
                'id': str(product['id']),
                'title': product['title'],
                'handle': product['handle'],
                'price': float(variants[0].get('price', 0)),
                'image_url': (product.get('images', [{}])[0] or {}).get('src'),
                'available': total_stock > 0,
                'total_stock': total_stock,
                'sizes': sizes,
                'variants': [{
                    'id': str(v['id']),
                    'title': v['title'],
                    'price': float(v.get('price', 0)),
                    'available': v.get('available', False)
                } for v in variants]
            }

        except Exception as e:
            logger.error(f"Error processing product: {e}")
            return None

    def _matches_keywords(self, product: Dict, keywords: List[str]) -> bool:
        """Check if product matches keywords"""
        if not keywords:
            return True

        text = (
            product.get('title', '').lower() + ' ' +
            product.get('handle', '').lower() + ' ' +
            product.get('description', '').lower()
        )
        return any(k.lower() in text for k in keywords)

    async def monitor_store(self, store_url: str, keywords: List[str]) -> List[Dict]:
        """Monitor a single store with error handling"""
        products = await self.get_store_products(store_url)
        if not products:
            return []

        matching = []
        for product in products:
            if self._matches_keywords(product, keywords):
                processed = self._process_product(product)
                if processed and self.product_tracker.is_new_or_changed(processed):
                    matching.append(processed)

        return matching

    async def monitor_stores(self, stores: List[str], keywords: List[str]) -> List[Dict]:
        """Monitor multiple stores concurrently"""
        await self.setup()

        tasks = []
        for store in stores:
            task = asyncio.create_task(self.monitor_store(store, keywords))
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        products = []
        for store, result in zip(stores, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to monitor {store}: {result}")
            elif isinstance(result, list):
                products.extend(result)

        return products

async def main():
    """Example usage of ShopifyMonitor"""
    monitor = ShopifyMonitor(rate_limit=1.0)

    try:
        stores = [
            "https://shop.shopwss.com",
            "https://www.shoepalace.com",
            "https://www.jimmyjazz.com"
        ]
        keywords = ["nike", "jordan", "dunk"]

        products = await monitor.monitor_stores(stores, keywords)
        print(f"Found {len(products)} matching products")

    finally:
        await monitor.close()

if __name__ == "__main__":
    asyncio.run(main())