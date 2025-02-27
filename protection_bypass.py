import aiohttp
import json
import random
import time
import hashlib
import base64
from typing import Dict, Optional
from datetime import datetime
import logging
import cloudscraper

class ProtectionBypass:
    def __init__(self):
        self.session_id = hashlib.md5(str(time.time()).encode()).hexdigest()
        self.init_time = int(time.time() * 1000)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Sec-Ch-Ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'X-Requested-With': 'XMLHttpRequest'
        }
        self.cookies = {}
        self.client_version = "1.5.0"
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )

    def get_shopify_headers(self, store_url: str) -> Dict:
        """Get headers for Shopify API requests"""
        headers = self.headers.copy()
        headers.update({
            'Origin': store_url,
            'Referer': store_url,
            'X-Shopify-Storefront-Access-Token': 'public',
            'X-Request-Start': str(int(time.time() * 1000))
        })
        return headers

    def get_cookies(self, store_url: str) -> Dict:
        """Generate store-specific cookies"""
        timestamp = int(time.time())
        cookies = {
            '_s': self.session_id,
            '_shopify_s': self.session_id,
            '_shopify_y': str(timestamp - 86400),
            '_y': str(timestamp - 86400),
            'cart_currency': 'USD',
            'cart_ts': str(timestamp),
            'cart_ver': '2',
            'localization': 'US'
        }
        return cookies

    async def verify_store(self, session: aiohttp.ClientSession, store_url: str) -> bool:
        """Verify store accessibility and determine protection level"""
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

                # Update cookies from response
                for cookie_name, cookie_morsel in response.cookies.items():
                    self.cookies[cookie_name] = cookie_morsel.value

                # Check response headers for protection indicators
                response_headers = response.headers
                protection_indicators = [
                    ('server', 'cloudflare'),
                    ('server', 'akamai'),
                    ('x-cdn', 'Incapsula'),
                    ('x-iinfo', '')  # Incapsula info header
                ]

                for header, value in protection_indicators:
                    if value in response_headers.get(header, '').lower():
                        # Store needs protection bypass
                        self.headers.update(self.get_shopify_headers(store_url))
                        self.cookies.update(self.get_cookies(store_url))
                        break

                return True

        except Exception as e:
            logging.error(f"Error verifying store {store_url}: {e}")
            return False

    def get_request_params(self, store_url: str) -> Dict:
        """Get all necessary request parameters for a store"""
        return {
            'headers': self.get_shopify_headers(store_url),
            'cookies': self.cookies,
            'timeout': aiohttp.ClientTimeout(total=30),
            'ssl': False,
            'allow_redirects': True
        }


    def _generate_px_payload(self) -> Dict:
        """Generate PerimeterX payload for Walmart"""
        # Current timestamp in milliseconds
        timestamp = int(time.time() * 1000)

        return {
            "uuid": self.session_id,
            "vid": "",
            "tid": hashlib.md5(str(random.random()).encode()).hexdigest(),
            "sid": self.session_id,
            "ft": self.init_time,
            "seq": int((timestamp - self.init_time) / 1000),
            "en": "NTA",
            "pc": self.client_version,
            "ex": {
                "baseUrl": "www.walmart.com",
                "userAgent": self.headers['User-Agent'],
                "cookie": True,
                "localStorage": True,
                "webGL": True
            },
            "clf": str(random.random())
        }

    def _generate_shape_payload(self) -> Dict:
        """Generate Shape Security payload for Target"""
        timestamp = int(time.time() * 1000)
        return {
            "__st": timestamp,
            "__vh": hashlib.sha256(str(random.random()).encode()).hexdigest(),
            "__rc": str(int((timestamp - self.init_time) / 1000)),
            "__duid": self.session_id,
            "__cs": hashlib.md5(str(time.time()).encode()).hexdigest(),
            "__cf": {
                "webGL": True,
                "canvas": True,
                "storage": True,
                "audio": True
            }
        }

    def _generate_akamai_payload(self) -> Dict:
        """Generate Akamai sensor data for Best Buy"""
        # Generate sophisticated Akamai sensor data
        timestamp = int(time.time() * 1000)
        events = [
            {"type": "load", "timestamp": self.init_time},
            {"type": "mousemove", "timestamp": self.init_time + 100},
            {"type": "scroll", "timestamp": self.init_time + 500},
            {"type": "click", "timestamp": timestamp}
        ]

        sensor_data = {
            "events": events,
            "device": {
                "screenWidth": 1920,
                "screenHeight": 1080,
                "colorDepth": 24,
                "pixelRatio": 1,
                "localStorage": True,
                "sessionStorage": True,
                "indexedDB": True,
                "openDatabase": True,
                "cpuClass": "unknown",
                "platform": "Win32",
                "doNotTrack": "unknown",
                "plugins": "PDF Viewer,Chrome PDF Viewer,Chromium PDF Viewer",
                "canvas": True,
                "webGL": True,
                "webGLVendor": "Google Inc. (Intel)",
                "adBlock": False,
                "hasLiedLanguages": False,
                "hasLiedResolution": False,
                "hasLiedOs": False,
                "hasLiedBrowser": False,
                "touchSupport": {
                    "points": 0,
                    "event": False,
                    "start": False
                },
                "audio": "124.04347527516074"
            },
            "bm_sz": self.session_id,
            "akam_seq": int((timestamp - self.init_time) / 1000),
            "akam_ts": timestamp,
            "api_type": "js",
            "auth": hashlib.sha256(str(random.random()).encode()).hexdigest()
        }

        return {
            "sensor_data": base64.b64encode(json.dumps(sensor_data).encode()).decode()
        }

    def get_walmart_headers(self) -> Dict:
        """Get headers for bypassing Walmart's PerimeterX"""
        px_payload = self._generate_px_payload()

        headers = self.headers.copy()
        headers.update({
            "X-PX-AUTHORIZATION": base64.b64encode(json.dumps(px_payload).encode()).decode(),
            "X-PX-CLIENT-VERSION": self.client_version,
            "X-PXD-COOKIE": self.session_id,
            "X-PX-TIMESTAMP": str(int(time.time() * 1000))
        })

        return headers

    def get_target_headers(self) -> Dict:
        """Get headers for bypassing Target's Shape Security"""
        shape_payload = self._generate_shape_payload()

        headers = self.headers.copy()
        headers.update({
            "X-SHAPE-UTC": str(int(time.time())),
            "X-SHAPE-CLIENT": base64.b64encode(json.dumps(shape_payload).encode()).decode(),
            "X-SHAPE-CHALLENGE": hashlib.sha256(str(time.time()).encode()).hexdigest(),
            "X-Requested-With": "XMLHttpRequest"
        })

        return headers

    def get_bestbuy_headers(self) -> Dict:
        """Get headers for bypassing Best Buy's Akamai"""
        akamai_payload = self._generate_akamai_payload()

        headers = self.headers.copy()
        headers.update({
            "_abck": hashlib.sha256(str(time.time()).encode()).hexdigest(),
            "bm_sz": self.session_id,
            "X-Akamai-Sensor": base64.b64encode(json.dumps(akamai_payload).encode()).decode(),
            "X-NewRelic-ID": "VQYGVF5SCBADUVBRBgAGVg==",
            "X-CLIENT-SIDE-METRICS": json.dumps({
                "timing": {
                    "navigationStart": self.init_time,
                    "fetchStart": self.init_time + 50,
                    "domainLookupStart": self.init_time + 100,
                    "domainLookupEnd": self.init_time + 150,
                    "connectStart": self.init_time + 200,
                    "connectEnd": self.init_time + 300,
                    "requestStart": self.init_time + 350,
                    "responseStart": self.init_time + 400,
                    "responseEnd": int(time.time() * 1000)
                }
            })
        })

        return headers

    def simulate_human_timing(self) -> float:
        """Simulate realistic human timing between actions"""
        base_delay = random.uniform(1.5, 3.0)
        jitter = random.uniform(0, 0.5)
        return base_delay + jitter

    def get_retailer_headers(self, retailer: str) -> Dict:
        """Get appropriate headers based on retailer"""
        if retailer == "walmart":
            return self.get_walmart_headers()
        elif retailer == "target":
            return self.get_target_headers()
        elif retailer == "bestbuy":
            return self.get_bestbuy_headers()
        else:
            return {}