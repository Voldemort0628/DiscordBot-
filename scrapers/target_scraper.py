import asyncio
import random
import time
from typing import List, Optional
from bs4 import BeautifulSoup
from .flare_solver import FlareSolver

class TargetProduct:
    def __init__(self, title: str, price: float, url: str, image_url: Optional[str] = None):
        self.title = title
        self.price = price
        self.url = url
        self.image_url = image_url
        self.retailer = 'target'

class TargetScraper:
    def __init__(self):
        self.base_url = "https://www.target.com"
        self.solver = FlareSolver()

    def _clean_price(self, price_str: str) -> float:
        """Convert price string to float"""
        try:
            return float(price_str.replace('$', '').replace(',', '').strip())
        except (ValueError, AttributeError):
            return 0.0

    def search_products(self, keyword: str) -> List[TargetProduct]:
        """Search Target for products using FlareSolver"""
        results = []
        print(f"[Target] Searching for: {keyword}")

        try:
            # First visit homepage to set cookies
            self.solver.get(self.base_url)
            time.sleep(random.uniform(2, 4))

            # Now perform the search
            search_url = f"{self.base_url}/s?searchTerm={keyword}"
            print(f"[Target] Navigating to: {search_url}")

            response = self.solver.get(search_url)
            if response.status_code != 200:
                print(f"[Target] Error: Got status code {response.status_code}")
                return results

            soup = BeautifulSoup(response.content, 'lxml')
            products = soup.find_all('div', {'data-test': 'product-card'})
            print(f"[Target] Found {len(products)} potential products")

            for product in products:
                try:
                    title_elem = product.find('a', {'data-test': 'product-title'})
                    price_elem = product.find('span', {'data-test': 'product-price'})

                    if title_elem and price_elem and 'pokemon' in title_elem.text.lower():
                        title = title_elem.text.strip()
                        price = self._clean_price(price_elem.text)
                        product_url = self.base_url + title_elem['href']
                        image_url = product.find('img')['src'] if product.find('img') else None

                        results.append(TargetProduct(
                            title=title,
                            price=price,
                            url=product_url,
                            image_url=image_url
                        ))
                        print(f"[Target] Found product: {title} at ${price}")

                except Exception as e:
                    print(f"[Target] Error processing product card: {str(e)}")
                    continue

        except Exception as e:
            print(f"[Target] Scraping error: {str(e)}")

        return results

    @staticmethod
    def test_scraper():
        """Test the scraper with a sample search"""
        scraper = TargetScraper()
        products = scraper.search_products("pokemon")
        print(f"\nFound {len(products)} Pokemon products at Target:")
        for product in products:
            print(f"- {product.title}: ${product.price}")