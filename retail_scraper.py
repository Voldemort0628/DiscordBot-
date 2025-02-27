import requests
import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional
import json
import time
import random
import urllib.parse
from protection_bypass import ProtectionBypass

class RetailScrapeResult:
    def __init__(self, title: str, price: float, url: str, retailer: str, image_url: Optional[str] = None):
        self.title = title
        self.price = price
        self.url = url
        self.retailer = retailer
        self.image_url = image_url

class RetailScraper:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        self.protection_bypass = ProtectionBypass()
        self.retry_counts = {}
        self.rate_limit = 1.0

    def _clean_price(self, price_str: str) -> float:
        """Convert price string to float"""
        try:
            return float(price_str.replace('$', '').replace(',', '').strip())
        except (ValueError, AttributeError):
            return 0.0

    def _make_request(self, url: str, retailer: str) -> requests.Response:
        """Make a request with appropriate protection bypass"""
        # Get retailer-specific headers
        headers = self.protection_bypass.get_retailer_headers(retailer)

        # Add common headers
        headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        })

        # Add delay to simulate human behavior
        time.sleep(self.protection_bypass.simulate_human_timing())

        # Make the request using cloudscraper
        response = self.scraper.get(url, headers=headers, timeout=15)
        print(f"{retailer.title()} response status: {response.status_code}")
        return response

    def scrape_target(self, keyword: str) -> List[RetailScrapeResult]:
        """Scrape Target with Shape Security bypass"""
        results = []
        try:
            print(f"Scraping Target for keyword: {keyword}")
            base_url = "https://www.target.com"
            search_url = f"{base_url}/s?searchTerm={urllib.parse.quote(keyword)}"

            response = self._make_request(search_url, "target")

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                products = soup.find_all('div', {'data-test': 'product-card'})

                print(f"Found {len(products)} potential products on Target")

                for product in products:
                    try:
                        title_elem = product.find('a', {'data-test': 'product-title'})
                        price_elem = product.find('span', {'data-test': 'product-price'})

                        if title_elem and price_elem and 'pokemon' in title_elem.text.lower():
                            title = title_elem.text.strip()
                            price = self._clean_price(price_elem.text)
                            product_url = base_url + title_elem['href']
                            image_url = product.find('img')['src'] if product.find('img') else None

                            results.append(RetailScrapeResult(
                                title=title,
                                price=price,
                                url=product_url,
                                retailer='target',
                                image_url=image_url
                            ))
                            print(f"Added Target product: {title} at ${price}")
                    except Exception as e:
                        print(f"Error processing Target product: {e}")
                        continue
        except Exception as e:
            print(f"Error scraping Target: {e}")

        return results

    def scrape_walmart(self, keyword: str) -> List[RetailScrapeResult]:
        """Scrape Walmart with PerimeterX bypass"""
        results = []
        try:
            print(f"Scraping Walmart for keyword: {keyword}")
            base_url = "https://www.walmart.com"
            search_url = f"{base_url}/search?q={urllib.parse.quote(keyword)}"

            response = self._make_request(search_url, "walmart")

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                products = soup.find_all('div', {'data-item-id': True})

                print(f"Found {len(products)} potential products on Walmart")

                for product in products:
                    try:
                        title_elem = product.find('span', {'data-automation-id': 'product-title'})
                        price_elem = product.find('div', {'data-automation-id': 'product-price'})

                        if title_elem and price_elem and 'pokemon' in title_elem.text.lower():
                            title = title_elem.text.strip()
                            price = self._clean_price(price_elem.text)
                            product_url = base_url + product.find('a')['href']
                            image_url = product.find('img')['src'] if product.find('img') else None

                            results.append(RetailScrapeResult(
                                title=title,
                                price=price,
                                url=product_url,
                                retailer='walmart',
                                image_url=image_url
                            ))
                            print(f"Added Walmart product: {title} at ${price}")
                    except Exception as e:
                        print(f"Error processing Walmart product: {e}")
                        continue
        except Exception as e:
            print(f"Error scraping Walmart: {e}")

        return results

    def scrape_bestbuy(self, keyword: str) -> List[RetailScrapeResult]:
        """Scrape Best Buy with Akamai bypass"""
        results = []
        try:
            print(f"Scraping Best Buy for keyword: {keyword}")
            base_url = "https://www.bestbuy.com"
            search_url = f"{base_url}/site/searchpage.jsp?st={urllib.parse.quote(keyword)}"

            response = self._make_request(search_url, "bestbuy")

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                products = soup.find_all('li', {'class': 'sku-item'})

                print(f"Found {len(products)} potential products on Best Buy")

                for product in products:
                    try:
                        title_elem = product.find('h4', {'class': 'sku-header'})
                        price_elem = product.find('div', {'class': 'priceView-customer-price'})

                        if title_elem and price_elem and 'pokemon' in title_elem.text.lower():
                            title = title_elem.text.strip()
                            price = self._clean_price(price_elem.find('span').text)
                            link_elem = product.find('a', {'class': 'image-link'})
                            if link_elem:
                                product_url = base_url + link_elem['href']
                                image_url = product.find('img', {'class': 'product-image'})['src'] if product.find('img', {'class': 'product-image'}) else None

                                results.append(RetailScrapeResult(
                                    title=title,
                                    price=price,
                                    url=product_url,
                                    retailer='bestbuy',
                                    image_url=image_url
                                ))
                                print(f"Added Best Buy product: {title} at ${price}")
                    except Exception as e:
                        print(f"Error processing Best Buy product: {e}")
                        continue
        except Exception as e:
            print(f"Error scraping Best Buy: {e}")

        return results

    def scrape_all(self, keyword: str) -> List[RetailScrapeResult]:
        """Scrape all supported retailers"""
        results = []
        results.extend(self.scrape_target(keyword))
        time.sleep(random.uniform(2, 4))
        results.extend(self.scrape_walmart(keyword))
        time.sleep(random.uniform(2, 4))
        results.extend(self.scrape_bestbuy(keyword))
        return results