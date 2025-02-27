import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime
from collections import deque
import logging
from urllib.parse import urlparse
from aiohttp import ClientTimeout, TCPConnector
from config import USER_AGENT, SHOPIFY_RATE_LIMIT, MAX_PRODUCTS
from logger_config import scraper_logger

logger = scraper_logger

class DomainRateLimiter:
    """Per-domain rate limiting with dynamic backoff"""
    def __init__(self, default_rate: float = 1.0):
        self.default_rate = default_rate
        self.domain_rates: Dict[str, float] = {}
        self.last_request: Dict[str, float] = {}
        self.backoff_multiplier: Dict[str, float] = {}

    def get_delay(self, domain: str) -> float:
        """Calculate delay needed for rate limiting"""
        current_time = time.time()
        rate = self.domain_rates.get(domain, self.default_rate)
        last_time = self.last_request.get(domain, 0)
        multiplier = self.backoff_multiplier.get(domain, 1.0)

        delay = max(0, (1.0 / rate) * multiplier - (current_time - last_time))
        return delay

    async def acquire(self, domain: str):
        """Wait for rate limit slot"""
        delay = self.get_delay(domain)
        if delay > 0:
            await asyncio.sleep(delay)
        self.last_request[domain] = time.time()

    def increase_backoff(self, domain: str):
        """Increase backoff multiplier after failures"""
        self.backoff_multiplier[domain] = min(8.0, 
            self.backoff_multiplier.get(domain, 1.0) * 2)

    def decrease_backoff(self, domain: str):
        """Decrease backoff multiplier after success"""
        if domain in self.backoff_multiplier:
            self.backoff_multiplier[domain] = max(1.0, 
                self.backoff_multiplier[domain] * 0.75)

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
            return None

        # Sort by health score and last used time
        proxy = max(available, key=lambda p: (
            self.health_scores.get(p, 0.5),
            -self.last_used.get(p, 0)
        ))

        self.in_use.add(proxy)
        self.last_used[proxy] = time.time()
        return proxy

    def release_proxy(self, proxy: str, success: bool):
        """Release proxy and update health metrics"""
        if proxy not in self.proxies:
            return

        self.in_use.discard(proxy)
        score = self.health_scores.get(proxy, 0.5)

        if success:
            self.health_scores[proxy] = min(1.0, score + 0.1)
            self.error_counts[proxy] = 0
        else:
            self.health_scores[proxy] = max(0.0, score - 0.2)
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
    """Advanced Shopify product monitor"""
    def __init__(self, 
                 rate_limit: float = 1.0,
                 proxies: Optional[List[str]] = None,
                 max_concurrent: int = 3):
        self.rate_limiter = DomainRateLimiter(rate_limit)
        self.proxy_manager = ProxyManager(proxies)
        self.product_tracker = ProductTracker()
        self.max_concurrent = max_concurrent
        self.session: Optional[aiohttp.ClientSession] = None
        self.tasks: Set[asyncio.Task] = set()
        self.store_queues: Dict[str, asyncio.Queue] = {}

    async def setup(self):
        """Initialize monitor resources"""
        if self.session is None:
            timeout = ClientTimeout(total=30)
            connector = TCPConnector(ssl=False, limit=self.max_concurrent)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    'User-Agent': USER_AGENT,
                    'Accept': 'application/json'
                }
            )

    async def close(self):
        """Cleanup resources"""
        if self.session and not self.session.closed:
            await self.session.close()

        # Cancel all running tasks
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

    async def monitor_store(self, store_url: str, keywords: List[str]) -> List[Dict]:
        """Monitor a single store with retries and error handling"""
        await self.setup()
        domain = urlparse(store_url).netloc
        retry_count = 0
        max_retries = 3

        while retry_count < max_retries:
            try:
                # Get proxy and wait for rate limit
                proxy = await self.proxy_manager.get_proxy()
                await self.rate_limiter.acquire(domain)

                # Make request with proxy if available
                async with self.session.get(
                    f"{store_url}/products.json",
                    proxy=proxy
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    # Update rate limiting and proxy health
                    self.rate_limiter.decrease_backoff(domain)
                    if proxy:
                        self.proxy_manager.release_proxy(proxy, True)

                    # Process matching products
                    products = []
                    for product in data.get('products', []):
                        if await self._matches_keywords(product, keywords):
                            processed = await self._process_product(product)
                            if processed and self.product_tracker.is_new_or_changed(processed):
                                products.append(processed)

                    return products

            except Exception as e:
                retry_count += 1
                logger.error(f"Error monitoring {store_url} (attempt {retry_count}): {e}")

                # Update rate limiting and proxy health
                self.rate_limiter.increase_backoff(domain)
                if proxy:
                    self.proxy_manager.release_proxy(proxy, False)

                if retry_count < max_retries:
                    await asyncio.sleep(2 ** retry_count)  # Exponential backoff

        return []  # Return empty list after all retries failed

    async def _matches_keywords(self, product: Dict, keywords: List[str]) -> bool:
        """Check if product matches keywords"""
        product_text = (
            product.get('title', '').lower() + ' ' +
            product.get('description', '').lower()
        )
        return any(k.lower() in product_text for k in keywords)

    async def _process_product(self, product: Dict) -> Optional[Dict]:
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
                'id': product['id'],
                'title': product['title'],
                'handle': product['handle'],
                'price': variants[0].get('price'),
                'image_url': (product.get('images', [{}])[0] or {}).get('src'),
                'available': total_stock > 0,
                'total_stock': total_stock,
                'sizes': sizes,
                'variants': [
                    {
                        'id': v['id'],
                        'title': v['title'],
                        'price': v['price'],
                        'available': v['available']
                    }
                    for v in variants
                ]
            }

        except Exception as e:
            logger.error(f"Error processing product {product.get('title')}: {e}")
            return None

    async def monitor_stores(self, stores: List[str], keywords: List[str]) -> List[Dict]:
        """Monitor multiple stores concurrently"""
        await self.setup()

        tasks = []
        for store_url in stores:
            task = asyncio.create_task(self.monitor_store(store_url, keywords))
            tasks.append(task)
            self.tasks.add(task)
            task.add_done_callback(self.tasks.remove)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        products = []
        for store_url, result in zip(stores, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to monitor {store_url}: {result}")
            else:
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