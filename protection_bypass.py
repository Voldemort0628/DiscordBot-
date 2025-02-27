import aiohttp
import json
import time
import hashlib
import base64
from typing import Dict, Optional
from datetime import datetime
import logging

class ProtectionBypass:
    def __init__(self):
        self.session_id = hashlib.md5(str(time.time()).encode()).hexdigest()
        self.init_time = int(time.time() * 1000)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        }
        self.cookies = {}

    def get_shopify_headers(self, store_url: str) -> Dict:
        """Get basic headers for Shopify API requests"""
        headers = self.headers.copy()
        headers.update({
            'Origin': store_url,
            'Referer': store_url
        })
        return headers

    def get_cookies(self, store_url: str) -> Dict:
        """Generate basic store cookies"""
        timestamp = int(time.time())
        cookies = {
            '_s': self.session_id,
            'cart_ts': str(timestamp)
        }
        return cookies

    async def verify_store(self, session: aiohttp.ClientSession, store_url: str) -> bool:
        """Simple store verification"""
        try:
            headers = self.get_shopify_headers(store_url)
            cookies = self.get_cookies(store_url)

            async with session.get(
                store_url,
                headers=headers,
                cookies=cookies,
                timeout=10,
                ssl=False
            ) as response:
                if response.status != 200:
                    return False

                # Store new cookies safely
                for name, value in response.cookies.items():
                    if isinstance(value, str):  # Only store string cookies
                        self.cookies[name] = value

                return True

        except Exception as e:
            logging.error(f"Error verifying store {store_url}: {e}")
            return False

    def get_request_params(self, store_url: str) -> Dict:
        """Get basic request parameters"""
        return {
            'headers': self.get_shopify_headers(store_url),
            'cookies': self.cookies,
            'timeout': aiohttp.ClientTimeout(total=30),
            'ssl': False
        }