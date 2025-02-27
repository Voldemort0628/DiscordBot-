import json
import random
import time
import hashlib
import base64
from typing import Dict, Optional
from datetime import datetime

class ProtectionBypass:
    def __init__(self):
        self.session_id = hashlib.md5(str(time.time()).encode()).hexdigest()
        self.client_version = "1.5.0"
        self.init_time = int(time.time() * 1000)

    def _generate_px_payload(self) -> Dict:
        """Generate PerimeterX payload for Walmart"""
        return {
            "uuid": self.session_id,
            "vid": "",
            "tid": hashlib.md5(str(random.random()).encode()).hexdigest(),
            "sid": self.session_id,
            "ft": self.init_time,
            "seq": 0,
            "en": "NTA",
            "pc": self.client_version,
            "ex": {},
            "clf": str(random.random())
        }

    def _generate_shape_payload(self) -> Dict:
        """Generate Shape Security payload for Target"""
        return {
            "__st": self.init_time,
            "__vh": hashlib.sha256(str(random.random()).encode()).hexdigest(),
            "__rc": "0",
            "__duid": self.session_id,
            "__cs": hashlib.md5(str(time.time()).encode()).hexdigest()
        }

    def _generate_akamai_payload(self) -> Dict:
        """Generate Akamai sensor data for Best Buy"""
        return {
            "sensor_data": base64.b64encode(json.dumps({
                "bm_sz": self.session_id,
                "akam_seq": 0,
                "akam_ts": int(time.time() * 1000),
                "api_type": "js",
                "auth": hashlib.sha256(str(random.random()).encode()).hexdigest()
            }).encode()).decode()
        }

    def get_walmart_headers(self) -> Dict:
        """Get headers for bypassing Walmart's PerimeterX"""
        px_payload = self._generate_px_payload()
        return {
            "sec-ch-ua": '"Chromium";v="92", " Not A;Brand";v="99", "Google Chrome";v="92"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "Windows",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "X-PX-AUTHORIZATION": base64.b64encode(json.dumps(px_payload).encode()).decode(),
            "X-PX-CLIENT-VERSION": self.client_version
        }

    def get_target_headers(self) -> Dict:
        """Get headers for bypassing Target's Shape Security"""
        shape_payload = self._generate_shape_payload()
        return {
            "X-SHAPE-UTC": str(int(time.time())),
            "X-SHAPE-CLIENT": base64.b64encode(json.dumps(shape_payload).encode()).decode(),
            "sec-ch-ua": '"Chromium";v="92", " Not A;Brand";v="99", "Google Chrome";v="92"',
            "sec-ch-ua-mobile": "?0",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "X-Requested-With": "XMLHttpRequest"
        }

    def get_bestbuy_headers(self) -> Dict:
        """Get headers for bypassing Best Buy's Akamai"""
        akamai_payload = self._generate_akamai_payload()
        return {
            "_abck": hashlib.sha256(str(time.time()).encode()).hexdigest(),
            "bm_sz": self.session_id,
            "sec-ch-ua": '"Chromium";v="92", " Not A;Brand";v="99", "Google Chrome";v="92"',
            "sec-ch-ua-mobile": "?0",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "X-Akamai-Sensor": base64.b64encode(json.dumps(akamai_payload).encode()).decode()
        }

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
