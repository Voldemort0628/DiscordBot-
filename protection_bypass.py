import json
import random
import time
import hashlib
import base64
import cloudscraper
from typing import Dict, Optional
from datetime import datetime

class ProtectionBypass:
    def __init__(self):
        self.session_id = hashlib.md5(str(time.time()).encode()).hexdigest()
        self.client_version = "1.5.0"
        self.init_time = int(time.time() * 1000)
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )

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
                "userAgent": self.scraper.headers['User-Agent'],
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

        headers = self.scraper.headers.copy()
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

        headers = self.scraper.headers.copy()
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

        headers = self.scraper.headers.copy()
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