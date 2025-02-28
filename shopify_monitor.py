import requests
import time
import json
from typing import Dict, List
import random
from config import USER_AGENT, SHOPIFY_RATE_LIMIT, MAX_PRODUCTS
import logging

class RateLimiter:
    def __init__(self, rate_limit):
        self.rate_limit = rate_limit
        self.last_request_time = 0

    def __enter__(self):
        current_time = time.time()
        time_passed = current_time - self.last_request_time
        if time_passed < 1 / self.rate_limit:
            # Add random jitter between 0-0.5 seconds
            jitter = random.uniform(0, 0.5)
            time.sleep(1/self.rate_limit - time_passed + jitter)
        self.last_request_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class ShopifyMonitor:
    def __init__(self, rate_limit=0.5):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "no-cache"
        })
        self.rate_limiter = RateLimiter(rate_limit)
        self.failed_stores = set()
        self.retry_counts = {}
        self.last_request_time = time.time()

    def get_product_variants(self, product_url):
        """Fetch specific product variants from a Shopify product URL"""
        try:
            # Convert product URL to JSON endpoint
            if not product_url.endswith('.json'):
                if product_url.endswith('/'):
                    product_url = product_url[:-1]
                product_url = product_url + '.json'

            # Fetch product data with retry logic
            max_retries = 3
            retry_count = 0
            while retry_count < max_retries:
                try:
                    with self.rate_limiter:
                        response = self.session.get(product_url, timeout=10)
                        response.raise_for_status()
                        product_data = response.json().get('product', {})
                        break
                except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                    retry_count += 1
                    if retry_count == max_retries:
                        logging.error(f"Failed to fetch variants after {max_retries} retries: {e}")
                        return {'variants': []}
                    time.sleep(1 * retry_count)

            if not product_data:
                return {'variants': []}

            # Extract variant information with more details
            variants = []
            for variant in product_data.get('variants', []):
                variants.append({
                    'id': variant.get('id'),
                    'title': variant.get('title'),
                    'price': variant.get('price'),
                    'inventory_quantity': variant.get('inventory_quantity', 0),
                    'available': variant.get('available', False),
                    'sku': variant.get('sku', ''),
                    'option1': variant.get('option1'),
                    'option2': variant.get('option2'),
                    'option3': variant.get('option3'),
                })

            return {
                'product_title': product_data.get('title'),
                'product_handle': product_data.get('handle'),
                'variants': variants,
                'options': product_data.get('options', []),
                'vendor': product_data.get('vendor'),
                'type': product_data.get('type')
            }

        except Exception as e:
            logging.error(f"Error fetching variants from {product_url}: {e}")
            return {'variants': []}

    def fetch_products(self, store_url: str, keywords: List[str]) -> List[Dict]:
        """
        Fetches products from a Shopify store matching given keywords
        Implements exponential backoff for failed stores
        """
        logging.info(f"Fetching products from {store_url} with keywords: {keywords}")

        if store_url in self.failed_stores:
            retry_count = self.retry_counts.get(store_url, 0)
            backoff = min(300, 2 ** retry_count)  # Max 5 minutes backoff
            if time.time() - self.last_request_time < backoff:
                logging.info(f"Skipping {store_url} due to recent failure (backoff: {backoff}s)")
                return []
            self.retry_counts[store_url] = retry_count + 1

        self._rate_limit()

        try:
            # Use a smaller initial limit for faster responses
            initial_limit = 150  # Increased from 50
            products_url = f"{store_url}/products.json?limit={initial_limit}"

            logging.info(f"Making initial request to {products_url}")

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
            logging.info(f"Initial request successful - Status: {response.status_code}")

            data = response.json()
            matching_products = []
            total_products = len(data.get("products", []))
            logging.info(f"Retrieved {total_products} products from initial request")

            # Optimize keyword matching with pre-computed lowercase
            lowercase_keywords = [kw.lower() for kw in keywords]

            for product in data.get("products", []):
                product_title_lower = product["title"].lower()
                # More flexible matching - match any part of the title
                if any(keyword in product_title_lower for keyword in lowercase_keywords):
                    processed_product = self._process_product(store_url, product)
                    if processed_product:
                        matching_products.append(processed_product)
                        logging.info(f"Found matching product: {product['title']}")

            # If we got max products and didn't find any matches,
            # fetch more products only if necessary
            if total_products >= initial_limit and not matching_products and MAX_PRODUCTS > initial_limit:
                logging.info(f"Fetching additional products from page 2 (limit: {MAX_PRODUCTS})")
                products_url = f"{store_url}/products.json?limit={MAX_PRODUCTS}&page=2"

                try:
                    response = self.session.get(products_url, timeout=8)
                    response.raise_for_status()
                    more_data = response.json()
                    additional_products = len(more_data.get("products", []))
                    logging.info(f"Retrieved {additional_products} additional products")

                    for product in more_data.get("products", []):
                        product_title_lower = product["title"].lower()
                        if any(keyword in product_title_lower for keyword in lowercase_keywords):
                            processed_product = self._process_product(store_url, product)
                            if processed_product:
                                matching_products.append(processed_product)
                                logging.info(f"Found matching product from page 2: {product['title']}")
                except Exception as e:
                    # If second request fails, still return what we found from first request
                    logging.error(f"Error fetching additional products from {store_url}: {e}")

            # Reset failed status and retry count if successful
            self.failed_stores.discard(store_url)
            self.retry_counts.pop(store_url, None)
            logging.info(f"Found total of {len(matching_products)} matching products")
            return matching_products

        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            logging.error(f"Error fetching products from {store_url}: {e}")
            if isinstance(e, (requests.exceptions.ConnectionError, 
                            requests.exceptions.Timeout,
                            requests.exceptions.SSLError)):
                self.failed_stores.add(store_url)
                logging.warning(f"Added {store_url} to failed stores list")
            return []

    def _process_product(self, store_url: str, product: Dict) -> Dict:
        """
        Processes raw product data into formatted structure
        Returns empty dict if processing fails
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
                "full_size_run": "Bot 1 FSR" if stock > 0 else "OOS",
                "variant_id": variants[0].get("id") if variants else None,  # Added for better restock tracking
                "vendor": product.get("vendor"),
                "type": product.get("product_type"),
                "tags": product.get("tags", []),
                "retailer": store_url.split('/')[2]  # Extract domain as retailer
            }
        except Exception as e:
            logging.error(f"Error processing product {product.get('title', 'Unknown')}: {e}")
            return {}  # Return empty dict instead of None to match return type