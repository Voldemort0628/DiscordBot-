import asyncio
import aiohttp
import json
import time
import random
import base64
import hashlib
from typing import Dict, List, Optional, Set
from datetime import datetime
from collections import deque
import logging
from urllib.parse import urlparse
from aiohttp import ClientTimeout, TCPConnector, ClientError
from config import USER_AGENT, SHOPIFY_RATE_LIMIT, MAX_PRODUCTS
from logger_config import scraper_logger

logger = scraper_logger

class BrowserProfile:
    """Emulate realistic browser fingerprints"""
    def __init__(self):
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
        ]
        self.languages = ['en-US,en;q=0.9', 'en-GB,en;q=0.9', 'en-CA,en;q=0.9']
        self.platforms = ['Windows', 'MacIntel']

    def generate(self) -> Dict:
        """Generate a consistent browser profile"""
        user_agent = random.choice(self.user_agents)
        language = random.choice(self.languages)
        platform = random.choice(self.platforms)

        return {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': language,
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Sec-Ch-Ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': f'"{platform}"'
        }

class StoreVerifier:
    """Verify store accessibility and type"""
    def __init__(self):
        self.verified_stores: Set[str] = set()
        self.store_types: Dict[str, str] = {}

    async def verify_store(self, session: aiohttp.ClientSession, store_url: str) -> bool:
        """Verify store with multiple checks"""
        try:
            if store_url in self.verified_stores:
                return True

            # Try direct store access first
            async with session.get(store_url, ssl=False, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Store {store_url} returned status {response.status}")
                    return False

                # Check if it's a Shopify store
                is_shopify = False
                for header in response.headers:
                    if 'shopify' in header.lower():
                        is_shopify = True
                        break

                if not is_shopify:
                    logger.error(f"Store {store_url} does not appear to be a Shopify store")
                    return False

            # Try products.json endpoint
            products_url = f"{store_url.rstrip('/')}/products.json"
            async with session.get(products_url, ssl=False, timeout=10) as response:
                if response.status == 404:
                    logger.error(f"Products endpoint not found for {store_url}")
                    return False
                elif response.status == 403:
                    logger.error(f"Access forbidden for {store_url}")
                    return False
                elif response.status == 429:
                    logger.warning(f"Rate limited while verifying {store_url}")
                    await asyncio.sleep(5)  # Basic backoff
                    return False

                # Try parsing response as JSON
                try:
                    await response.json()
                except ValueError:
                    logger.error(f"Invalid JSON response from {store_url}")
                    return False

            self.verified_stores.add(store_url)
            return True

        except Exception as e:
            logger.error(f"Error verifying store {store_url}: {e}")
            return False

class ShopifyMonitor:
    """Advanced Shopify monitor"""
    def __init__(self, rate_limit: float = 1.0, proxies: Optional[List[str]] = None):
        self.rate_limit = rate_limit
        self.proxies = proxies or []
        self.browser_profile = BrowserProfile()
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
                connector=connector
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

    def _get_headers(self, store_url: str) -> Dict:
        """Get request headers"""
        headers = self.browser_profile.generate()
        headers.update({
            'Origin': store_url,
            'Referer': store_url,
            'X-Requested-With': 'XMLHttpRequest'
        })
        return headers

    def _get_cookies(self, store_url: str) -> Dict:
        """Get store cookies"""
        domain = urlparse(store_url).netloc
        if domain not in self.store_cookies:
            self.store_cookies[domain] = {
                '_shopify_y': str(int(time.time() - 86400)),
                'cart_currency': 'USD',
                'cart_ts': str(int(time.time())),
                '_shopify_s': hashlib.md5(domain.encode()).hexdigest()
            }
        return self.store_cookies[domain]

    async def get_store_products(self, store_url: str) -> Optional[List[Dict]]:
        """Fetch products with error handling"""
        domain = urlparse(store_url).netloc
        retry_count = self.consecutive_errors.get(domain, 0)

        try:
            # Verify store first
            if not await self.store_verifier.verify_store(self.session, store_url):
                logger.error(f"Failed to verify store {store_url}")
                self.consecutive_errors[domain] = retry_count + 1
                return None

            # Rate limiting
            await self._wait_for_rate_limit(domain)

            # Prepare request
            url = f"{store_url.rstrip('/')}/products.json"
            headers = self._get_headers(store_url)
            cookies = self._get_cookies(store_url)

            # Make request
            async with self.session.get(
                url,
                headers=headers,
                cookies=cookies,
                ssl=False
            ) as response:
                if response.status == 429:
                    logger.warning(f"Rate limited on {store_url}")
                    self.consecutive_errors[domain] = retry_count + 1
                    return None

                if response.status != 200:
                    logger.error(f"HTTP {response.status} from {store_url}")
                    self.consecutive_errors[domain] = retry_count + 1
                    return None

                # Update cookies
                for cookie_name, cookie_value in response.cookies.items():
                    if hasattr(cookie_value, 'value'):
                        self.store_cookies[domain][cookie_name] = cookie_value.value

                # Parse response
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