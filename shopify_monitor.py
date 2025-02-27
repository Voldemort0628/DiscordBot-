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

    def _rate_limit(self):
        """Implements rate limiting for Shopify requests"""
        current_time = time.time()
        time_passed = current_time - self.last_request_time
        if time_passed < 1/SHOPIFY_RATE_LIMIT:
            time.sleep(1/SHOPIFY_RATE_LIMIT - time_passed)
        self.last_request_time = time.time()

    def fetch_products(self, store_url: str, keywords: List[str]) -> List[Dict]:
        """
        Fetches products from a Shopify store matching given keywords
        """
        self._rate_limit()
        
        try:
            products_url = f"{store_url}/products.json?limit={MAX_PRODUCTS}"
            response = self.session.get(products_url)
            response.raise_for_status()
            
            data = response.json()
            matching_products = []

            for product in data.get("products", []):
                if any(keyword.lower() in product["title"].lower() for keyword in keywords):
                    processed_product = self._process_product(store_url, product)
                    if processed_product:
                        matching_products.append(processed_product)

            return matching_products

        except requests.exceptions.RequestException as e:
            print(f"Error fetching products from {store_url}: {e}")
            return []

    def _process_product(self, store_url: str, product: Dict) -> Dict:
        """
        Processes raw product data into formatted structure
        """
        variants = product.get("variants", [])
        sizes = {}
        stock = 0

        for variant in variants:
            if variant.get("available"):
                size = str(variant.get("title"))
                stock += variant.get("inventory_quantity", 1)
                sizes[size] = variant.get("inventory_quantity", 1)

        return {
            "title": product["title"],
            "url": f"{store_url}/products/{product['handle']}",
            "price": variants[0].get("price") if variants else "N/A",
            "image_url": product.get("images", [{}])[0].get("src", ""),
            "stock": stock,
            "sizes": sizes,
            "full_size_run": "Bot 1 FSR" if stock > 0 else "OOS"
        }
