import json
import time
import requests
from typing import Dict, Optional

class FlareSolver:
    def __init__(self):
        self.base_url = "http://localhost:8191/v1"  # Default FlareSolverr address
        self.session = requests.Session()
        self.test_mode = True  # For initial testing, will fall back to regular requests if FlareSolverr not available

    def _make_request(self, url: str, headers: Optional[Dict] = None) -> requests.Response:
        """Make request through FlareSolverr if available, otherwise fallback to regular requests"""
        if not self.test_mode:
            try:
                payload = {
                    "cmd": "request.get",
                    "url": url,
                    "maxTimeout": 60000
                }
                if headers:
                    payload["headers"] = headers

                response = self.session.post(self.base_url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if data["status"] == "ok":
                        # Create a requests.Response-like object from FlareSolverr response
                        mock_response = requests.Response()
                        mock_response.status_code = data["solution"]["status"]
                        mock_response._content = data["solution"]["response"].encode()
                        mock_response.headers = data["solution"]["headers"]
                        return mock_response
            except Exception as e:
                print(f"FlareSolverr error: {e}, falling back to regular requests")

        # Fallback to regular requests with enhanced headers
        headers = headers or {}
        headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        })
        return self.session.get(url, headers=headers, timeout=30)

    def get(self, url: str, headers: Optional[Dict] = None) -> requests.Response:
        """Get URL content through FlareSolverr"""
        max_retries = 3
        current_retry = 0
        
        while current_retry < max_retries:
            try:
                response = self._make_request(url, headers)
                if response.status_code == 200:
                    return response
                elif response.status_code == 403:
                    print(f"Got 403 error, retrying after delay (attempt {current_retry + 1}/{max_retries})")
                    time.sleep(5 * (current_retry + 1))  # Exponential backoff
                else:
                    print(f"Unexpected status code: {response.status_code}")
                    return response
            except Exception as e:
                print(f"Error during request: {e}")
                time.sleep(5 * (current_retry + 1))
            current_retry += 1
        
        # If all retries failed, raise the last exception
        raise Exception(f"Failed to get content after {max_retries} retries")
