import requests
import time
import json
from typing import Dict, List
import random
from config import USER_AGENT, SHOPIFY_RATE_LIMIT, MAX_PRODUCTS

class ShopifyMonitor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json"
        })
        self.last_request_time = 0
        self.failed_stores = set()
        self.retry_counts = {}

    def _rate_limit(self):
        """Implements rate limiting for Shopify requests with jitter"""
        current_time = time.time()
        time_passed = current_time - self.last_request_time
        if time_passed < 1/SHOPIFY_RATE_LIMIT:
            # Add random jitter between 0-0.5 seconds
            jitter = random.uniform(0, 0.5)
            time.sleep(1/SHOPIFY_RATE_LIMIT - time_passed + jitter)
        self.last_request_time = time.time()

    def fetch_products(self, store_url: str, keywords: List[str]) -> List[Dict]:
        """
        Fetches products from a Shopify store matching given keywords
        Implements exponential backoff for failed stores
        """
        if store_url in self.failed_stores:
            retry_count = self.retry_counts.get(store_url, 0)
            backoff = min(300, 2 ** retry_count)  # Max 5 minutes backoff
            if time.time() - self.last_request_time < backoff:
                return []
            self.retry_counts[store_url] = retry_count + 1

        self._rate_limit()

        try:
            products_url = f"{store_url}/products.json?limit={MAX_PRODUCTS}"
            response = self.session.get(products_url, timeout=10)
            response.raise_for_status()

            data = response.json()
            matching_products = []

            for product in data.get("products", []):
                if any(keyword.lower() in product["title"].lower() for keyword in keywords):
                    processed_product = self._process_product(store_url, product)
                    if processed_product:
                        matching_products.append(processed_product)

            # Reset failed status and retry count if successful
            self.failed_stores.discard(store_url)
            self.retry_counts.pop(store_url, None)
            return matching_products

        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            print(f"Error fetching products from {store_url}: {e}")
            if isinstance(e, (requests.exceptions.ConnectionError, 
                            requests.exceptions.Timeout,
                            requests.exceptions.SSLError)):
                self.failed_stores.add(store_url)
            return []

    def _process_product(self, store_url: str, product: Dict) -> Dict:
        """
        Processes raw product data into formatted structure
        """
        try:
            variants = product.get("variants", [])
            sizes = {}
            stock = 0

            for variant in variants:
                if variant.get("available"):
                    size = str(variant.get("title"))
                    inventory = variant.get("inventory_quantity", 1)
                    stock += inventory
                    sizes[size] = inventory

            return {
                "title": product["title"],
                "url": f"{store_url}/products/{product['handle']}",
                "price": variants[0].get("price") if variants else "N/A",
                "image_url": product.get("images", [{}])[0].get("src", ""),
                "stock": stock,
                "sizes": sizes,
                "full_size_run": "Bot 1 FSR" if stock > 0 else "OOS"
            }
        except Exception as e:
            print(f"Error processing product {product.get('title', 'Unknown')}: {e}")
            return None