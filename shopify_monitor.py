import requests
import time
import json
from typing import Dict, List
import random
from config import USER_AGENT, SHOPIFY_RATE_LIMIT, MAX_PRODUCTS

class ShopifyMonitor:
    def __init__(self, rate_limit: float = SHOPIFY_RATE_LIMIT):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json"
        })
        self.last_request_time = 0
        self.failed_stores = set()
        self.retry_counts = {}
        self.rate_limit = rate_limit

    def _rate_limit(self):
        """Implements rate limiting for Shopify requests with jitter"""
        current_time = time.time()
        time_passed = current_time - self.last_request_time
        if time_passed < 1/self.rate_limit:
            # Add random jitter between 0-0.5 seconds
            jitter = random.uniform(0, 0.5)
            time.sleep(1/self.rate_limit - time_passed + jitter)
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
            # Use a smaller initial limit for faster responses
            initial_limit = 50
            products_url = f"{store_url}/products.json?limit={initial_limit}"
            
            # Use shorter timeout for faster error detection
            response = self.session.get(
                products_url, 
                timeout=5, 
                headers={
                    "Accept-Encoding": "gzip, deflate",
                    "Cache-Control": "no-cache"
                }
            )
            response.raise_for_status()

            data = response.json()
            matching_products = []
            
            # Optimize keyword matching with pre-computed lowercase
            lowercase_keywords = [kw.lower() for kw in keywords]

            for product in data.get("products", []):
                product_title_lower = product["title"].lower()
                if any(keyword in product_title_lower for keyword in lowercase_keywords):
                    processed_product = self._process_product(store_url, product)
                    if processed_product:
                        matching_products.append(processed_product)
            
            # If we got max products and didn't find any matches,
            # fetch more products only if necessary
            product_count = len(data.get("products", []))
            if product_count >= initial_limit and not matching_products and MAX_PRODUCTS > initial_limit:
                # Get more products in a second request
                products_url = f"{store_url}/products.json?limit={MAX_PRODUCTS}&page=2"
                
                try:
                    response = self.session.get(products_url, timeout=8)
                    response.raise_for_status()
                    more_data = response.json()
                    
                    for product in more_data.get("products", []):
                        product_title_lower = product["title"].lower()
                        if any(keyword in product_title_lower for keyword in lowercase_keywords):
                            processed_product = self._process_product(store_url, product)
                            if processed_product:
                                matching_products.append(processed_product)
                except Exception as e:
                    # If second request fails, still return what we found from first request
                    print(f"Error fetching additional products from {store_url}: {e}")

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
            variant_ids = {}
            stock = 0

            for variant in variants:
                if variant.get("available"):
                    size = str(variant.get("title"))
                    inventory = variant.get("inventory_quantity", 1)
                    stock += inventory
                    sizes[size] = inventory
                    variant_ids[size] = str(variant.get("id", ""))

            return {
                "title": product["title"],
                "url": f"{store_url}/products/{product['handle']}",
                "price": variants[0].get("price") if variants else "N/A",
                "image_url": product.get("images", [{}])[0].get("src", ""),
                "stock": stock,
                "sizes": sizes,
                "variants": variant_ids,
                "full_size_run": "Bot 1 FSR" if stock > 0 else "OOS"
            }
        except Exception as e:
            print(f"Error processing product {product.get('title', 'Unknown')}: {e}")
            return None