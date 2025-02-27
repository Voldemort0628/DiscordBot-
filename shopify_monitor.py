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

        profile = {
            'user_agent': user_agent,
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'accept_language': language,
            'accept_encoding': 'gzip, deflate, br',
            'connection': 'keep-alive',
            'dnt': '1',
            'upgrade_insecure_requests': '1',
            'sec_fetch_dest': 'document',
            'sec_fetch_mode': 'navigate',
            'sec_fetch_site': 'none',
            'sec_fetch_user': '?1',
            'sec_ch_ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
            'sec_ch_ua_mobile': '?0',
            'sec_ch_ua_platform': f'"{platform}"'
        }

        return profile

class SessionManager:
    """Manage browser sessions with rotation"""
    def __init__(self, max_sessions: int = 5):
        self.max_sessions = max_sessions
        self.sessions: Dict[str, Dict] = {}
        self.browser_profile = BrowserProfile()

    def _generate_client_identifier(self) -> str:
        """Generate unique client identifier"""
        timestamp = str(int(time.time() * 1000))
        random_str = hashlib.md5(str(random.random()).encode()).hexdigest()[:8]
        return f"{timestamp}-{random_str}"

    def _generate_session_token(self, domain: str) -> str:
        """Generate session token for Shopify"""
        timestamp = int(time.time() * 1000)
        session_id = hashlib.sha256(f"{domain}-{timestamp}".encode()).hexdigest()
        return session_id

    async def get_session(self, store_url: str) -> Dict:
        """Get or create session for store"""
        domain = urlparse(store_url).netloc

        # Clean old sessions
        current_time = time.time()
        self.sessions = {
            k: v for k, v in self.sessions.items()
            if current_time - v['created_at'] < 3600  # 1 hour TTL
        }

        # Rotate if too many sessions
        if len(self.sessions) >= self.max_sessions:
            oldest = min(self.sessions.items(), key=lambda x: x[1]['created_at'])
            del self.sessions[oldest[0]]

        # Generate new session
        if domain not in self.sessions:
            client_id = self._generate_client_identifier()
            session_token = self._generate_session_token(domain)
            browser = self.browser_profile.generate()

            self.sessions[domain] = {
                'client_id': client_id,
                'session_token': session_token,
                'browser': browser,
                'created_at': current_time,
                'request_count': 0,
                'cookies': {}
            }

        session = self.sessions[domain]
        session['request_count'] += 1
        return session

class ProxyManager:
    """Advanced proxy management with health tracking"""
    def __init__(self, proxies: Optional[List[str]] = None):
        self.proxies = proxies or []
        self.health_scores: Dict[str, float] = {}
        self.error_counts: Dict[str, int] = {}
        self.last_used: Dict[str, float] = {}
        self.in_use: Set[str] = set()
        self.banned_until: Dict[str, float] = {}

    async def get_proxy(self) -> Optional[str]:
        """Get best available proxy with ban checking"""
        if not self.proxies:
            return None

        current_time = time.time()

        # Filter out banned and in-use proxies
        available = [
            p for p in self.proxies 
            if p not in self.in_use and current_time >= self.banned_until.get(p, 0)
        ]

        if not available:
            await asyncio.sleep(1)
            return await self.get_proxy()

        # Select best proxy based on health and last used time
        proxy = max(available, key=lambda p: (
            self.health_scores.get(p, 0.5),
            -self.last_used.get(p, 0)
        ))

        self.in_use.add(proxy)
        self.last_used[proxy] = current_time
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
            return

        # Handle failures
        self.error_counts[proxy] = self.error_counts.get(proxy, 0) + 1

        # Determine penalty and ban duration based on error type
        if error_type == '429':  # Rate limit
            penalty = 0.05
            ban_duration = 300  # 5 minutes
        elif error_type in ('403', '404'):  # Access denied
            penalty = 0.2
            ban_duration = 1800  # 30 minutes
        elif error_type == 'timeout':
            penalty = 0.15
            ban_duration = 600  # 10 minutes
        else:
            penalty = 0.1
            ban_duration = 900  # 15 minutes

        self.health_scores[proxy] = max(0.0, score - penalty)

        # Ban proxy if too many errors
        if self.error_counts[proxy] >= 3:
            self.banned_until[proxy] = time.time() + ban_duration
            logger.warning(f"Proxy {proxy} banned for {ban_duration}s due to repeated errors")

class ShopifyMonitor:
    """Advanced Shopify monitor with anti-bot measures"""
    def __init__(self, rate_limit: float = 1.0, proxies: Optional[List[str]] = None):
        self.session_manager = SessionManager()
        self.proxy_manager = ProxyManager(proxies)
        self.rate_limit = rate_limit
        self.last_request: Dict[str, float] = {}
        self.product_hashes: Dict[str, str] = {}
        self.session: Optional[aiohttp.ClientSession] = None

    async def setup(self):
        """Initialize session"""
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

    def _get_api_url(self, store_url: str) -> str:
        """Generate inventory API URL"""
        base = store_url.rstrip('/')
        if not base.startswith(('http://', 'https://')):
            base = f'https://{base}'
        return f"{base}/products.json"

    def _get_graphql_url(self, store_url: str) -> str:
        """Generate GraphQL API URL"""
        base = store_url.rstrip('/')
        if not base.startswith(('http://', 'https://')):
            base = f'https://{base}'
        return f"{base}/api/2024-01/graphql.json"

    async def _wait_for_rate_limit(self, domain: str):
        """Implement rate limiting with jitter"""
        current_time = time.time()
        last_request = self.last_request.get(domain, 0)

        delay = (1.0 / self.rate_limit) - (current_time - last_request)
        if delay > 0:
            jitter = random.uniform(0, 0.1)  # Add 0-100ms jitter
            await asyncio.sleep(delay + jitter)

        self.last_request[domain] = time.time()

    async def get_store_products(self, store_url: str) -> Optional[List[Dict]]:
        """Fetch products with advanced anti-bot evasion"""
        await self.setup()
        domain = urlparse(store_url).netloc

        try:
            # Get session and proxy
            session_data = await self.session_manager.get_session(store_url)
            proxy = await self.proxy_manager.get_proxy()
            await self._wait_for_rate_limit(domain)

            # Prepare request
            headers = session_data['browser'].copy()
            headers.update({
                'x-shopify-client-id': session_data['client_id'],
                'x-shopify-session-token': session_data['session_token'],
                'x-requested-with': 'XMLHttpRequest',
                'origin': store_url,
                'referer': f"{store_url}/"
            })

            cookies = {
                '_shopify_y': str(int(time.time() - 86400)),
                '_shopify_s': session_data['session_token'],
                'cart_currency': 'USD',
                '_secure_session_id': hashlib.sha256(session_data['session_token'].encode()).hexdigest()
            }
            cookies.update(session_data['cookies'])

            params = {
                'headers': headers,
                'cookies': cookies,
                'allow_redirects': True,
                'ssl': False
            }
            if proxy:
                params['proxy'] = proxy

            # Make request
            async with self.session.get(self._get_api_url(store_url), **params) as response:
                # Handle various response cases
                if response.status == 429:
                    logger.warning(f"Rate limited on {store_url}")
                    if proxy:
                        self.proxy_manager.release_proxy(proxy, False, '429')
                    return None

                if response.status != 200:
                    logger.error(f"HTTP {response.status} from {store_url}")
                    if proxy:
                        self.proxy_manager.release_proxy(proxy, False, str(response.status))
                    return None

                # Store new cookies
                for cookie in response.cookies:
                    session_data['cookies'][cookie.key] = cookie.value

                try:
                    data = await response.json()
                    if proxy:
                        self.proxy_manager.release_proxy(proxy, True)
                    return data.get('products', [])
                except ValueError as e:
                    logger.error(f"Invalid JSON from {store_url}: {e}")
                    if proxy:
                        self.proxy_manager.release_proxy(proxy, False, 'json')
                    return None

        except asyncio.TimeoutError:
            logger.warning(f"Timeout on {store_url}")
            if proxy:
                self.proxy_manager.release_proxy(proxy, False, 'timeout')
            return None

        except Exception as e:
            logger.error(f"Error fetching {store_url}: {e}")
            if proxy:
                self.proxy_manager.release_proxy(proxy, False, 'unknown')
            return None

    def _process_product(self, product: Dict) -> Optional[Dict]:
        """Process product data with variant handling"""
        try:
            variants = product.get('variants', [])
            if not variants:
                return None

            total_stock = sum(
                v.get('inventory_quantity', 0)
                for v in variants
                if v.get('available')
            )

            if total_stock <= 0:
                return None

            # Generate product hash for change detection
            product_state = {
                'id': str(product['id']),
                'title': product['title'],
                'variants': [{
                    'id': str(v['id']),
                    'price': v.get('price'),
                    'available': v.get('available'),
                    'inventory': v.get('inventory_quantity')
                } for v in variants]
            }

            product_hash = hashlib.sha256(
                json.dumps(product_state, sort_keys=True).encode()
            ).hexdigest()

            # Check if product changed
            product_id = str(product['id'])
            if product_id in self.product_hashes:
                if self.product_hashes[product_id] == product_hash:
                    return None

            self.product_hashes[product_id] = product_hash

            return {
                'id': product_id,
                'title': product['title'],
                'handle': product.get('handle', ''),
                'price': float(variants[0].get('price', 0)),
                'available': True,
                'stock': total_stock,
                'variants': [{
                    'id': str(v['id']),
                    'title': v.get('title', 'Default'),
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

        text = (
            product.get('title', '').lower() + ' ' +
            product.get('handle', '').lower() + ' ' +
            product.get('product_type', '').lower() + ' ' +
            product.get('vendor', '').lower()
        )
        return any(k.lower() in text for k in keywords)

    async def monitor_store(self, store_url: str, keywords: List[str]) -> List[Dict]:
        """Monitor single store"""
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