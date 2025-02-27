import asyncio
import aiohttp
import json
import time
import random
from typing import Dict, List, Optional, Set
from datetime import datetime
from collections import deque
import logging
from urllib.parse import urlparse, urljoin
from aiohttp import ClientTimeout, TCPConnector, ClientError
from config import USER_AGENT, SHOPIFY_RATE_LIMIT, MAX_PRODUCTS
from logger_config import scraper_logger

logger = scraper_logger

class StoreVerifier:
    """Verify Shopify stores with multiple detection methods"""
    def __init__(self):
        self.verified_stores: Set[str] = set()
        self.failed_stores: Dict[str, Dict] = {}

    async def verify_store(self, session: aiohttp.ClientSession, store_url: str) -> bool:
        """Verify if store is Shopify using multiple methods"""
        try:
            if store_url in self.verified_stores:
                return True

            if store_url in self.failed_stores:
                if time.time() - self.failed_stores[store_url]['timestamp'] < 3600:
                    return False
                del self.failed_stores[store_url]

            # Method 1: Check products.json endpoint
            products_url = f"{store_url.rstrip('/')}/products.json"
            try:
                async with session.get(products_url, ssl=False, timeout=10) as response:
                    if response.status == 200:
                        try:
                            await response.json()
                            self.verified_stores.add(store_url)
                            return True
                        except ValueError:
                            pass
            except Exception:
                pass

            # Method 2: Check for Shopify assets
            try:
                async with session.get(store_url, ssl=False, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        shopify_indicators = [
                            'shopify.com',
                            '/cdn/shop/',
                            'Shopify.theme',
                            'myshopify.com',
                            'shopifycdn.com'
                        ]
                        if any(indicator in html for indicator in shopify_indicators):
                            self.verified_stores.add(store_url)
                            return True
            except Exception:
                pass

            # Method 3: Try product handle lookup
            try:
                test_url = f"{store_url.rstrip('/')}/products/does-not-exist"
                async with session.get(test_url, ssl=False, timeout=10) as response:
                    if response.status == 404:
                        html = await response.text()
                        if any(x in html.lower() for x in ['shopify', 'product not found']):
                            self.verified_stores.add(store_url)
                            return True
            except Exception:
                pass

            # Store failed verification
            self.failed_stores[store_url] = {
                'timestamp': time.time(),
                'attempts': self.failed_stores.get(store_url, {}).get('attempts', 0) + 1
            }
            return False

        except Exception as e:
            logger.error(f"Error verifying store {store_url}: {e}")
            return False

class ShopifyMonitor:
    """Advanced Shopify monitor with robust store verification"""
    def __init__(self, rate_limit: float = 1.0, proxies: Optional[List[str]] = None):
        self.rate_limit = rate_limit
        self.proxies = proxies or []
        self.store_verifier = StoreVerifier()
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_request: Dict[str, float] = {}
        self.store_cookies: Dict[str, Dict[str, str]] = {}
        self.consecutive_errors: Dict[str, int] = {}
        self.max_retries = 3

    async def setup(self):
        """Initialize monitor resources"""
        if self.session is None:
            timeout = ClientTimeout(total=30)
            connector = TCPConnector(ssl=False, limit=10)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={'User-Agent': USER_AGENT}
            )

    async def close(self):
        """Cleanup resources"""
        if self.session and not self.session.closed:
            await self.session.close()

    async def _wait_for_rate_limit(self, domain: str):
        """Rate limiting with jitter"""
        current_time = time.time()
        last_request = self.last_request.get(domain, 0)
        delay = (1.0 / self.rate_limit) - (current_time - last_request)

        if delay > 0:
            jitter = random.uniform(0, 0.1)
            await asyncio.sleep(delay + jitter)

        self.last_request[domain] = time.time()

    async def get_store_products(self, store_url: str) -> Optional[List[Dict]]:
        """Fetch products with improved error handling"""
        domain = urlparse(store_url).netloc
        retry_count = self.consecutive_errors.get(domain, 0)

        try:
            # Verify store first
            if not await self.store_verifier.verify_store(self.session, store_url):
                self.consecutive_errors[domain] = retry_count + 1
                return None

            # Rate limiting
            await self._wait_for_rate_limit(domain)

            # Make request
            url = f"{store_url.rstrip('/')}/products.json"
            headers = {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': store_url
            }

            async with self.session.get(url, headers=headers, ssl=False) as response:
                if response.status == 429:
                    logger.warning(f"Rate limited on {store_url}")
                    self.consecutive_errors[domain] = retry_count + 1
                    return None

                if response.status != 200:
                    logger.error(f"HTTP {response.status} from {store_url}")
                    self.consecutive_errors[domain] = retry_count + 1
                    return None

                try:
                    data = await response.json()
                    self.consecutive_errors[domain] = 0  # Reset on success
                    return data.get('products', [])
                except ValueError as e:
                    logger.error(f"Invalid JSON from {store_url}: {e}")
                    self.consecutive_errors[domain] = retry_count + 1
                    return None

        except Exception as e:
            logger.error(f"Error fetching {store_url}: {e}")
            self.consecutive_errors[domain] = retry_count + 1
            return None

    def _process_product(self, product: Dict) -> Optional[Dict]:
        """Process product data"""
        try:
            variants = product.get('variants', [])
            if not variants:
                return None

            # Calculate stock
            stock = sum(
                v.get('inventory_quantity', 0)
                for v in variants
                if v.get('available')
            )

            if stock <= 0:
                return None

            return {
                'id': str(product['id']),
                'title': product['title'],
                'handle': product.get('handle', ''),
                'url': f"https://{product.get('shop_url', '')}/products/{product.get('handle', '')}",
                'price': float(variants[0].get('price', 0)),
                'available': True,
                'stock': stock,
                'variants': [{
                    'id': str(v['id']),
                    'title': v.get('title', ''),
                    'price': float(v.get('price', 0)),
                    'available': v.get('available', False),
                    'inventory': v.get('inventory_quantity', 0)
                } for v in variants if v.get('available')]
            }

        except Exception as e:
            logger.error(f"Error processing product: {e}")
            return None

    def _matches_keywords(self, product: Dict, keywords: List[str]) -> bool:
        """Check if product matches keywords"""
        if not keywords:
            return True

        text = ' '.join(filter(None, [
            product.get('title', ''),
            product.get('handle', ''),
            product.get('type', ''),
            product.get('vendor', '')
        ])).lower()

        return any(k.lower() in text for k in keywords)

    async def monitor_store(self, store_url: str, keywords: List[str]) -> List[Dict]:
        """Monitor single store"""
        domain = urlparse(store_url).netloc
        if self.consecutive_errors.get(domain, 0) >= self.max_retries:
            logger.warning(f"Skipping {store_url} due to too many consecutive errors")
            return []

        products = await self.get_store_products(store_url)
        if not products:
            return []

        matching = []
        for product in products:
            if self._matches_keywords(product, keywords):
                processed = self._process_product(product)
                if processed:
                    matching.append(processed)

        return matching

    async def monitor_stores(self, stores: List[str], keywords: List[str]) -> List[Dict]:
        """Monitor multiple stores"""
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
    """Example usage"""
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