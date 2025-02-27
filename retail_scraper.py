import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional
import json
import time
import random

class RetailScrapeResult:
    def __init__(self, title: str, price: float, url: str, retailer: str, image_url: Optional[str] = None):
        self.title = title
        self.price = price
        self.url = url
        self.retailer = retailer
        self.image_url = image_url

class RetailScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })

    def _clean_price(self, price_str: str) -> float:
        """Convert price string to float"""
        try:
            return float(price_str.replace('$', '').replace(',', '').strip())
        except (ValueError, AttributeError):
            return 0.0

    def scrape_target(self, keyword: str) -> List[RetailScrapeResult]:
        """Scrape Target for Pokemon products"""
        results = []
        url = f"https://www.target.com/s?searchTerm={keyword}"

        try:
            print(f"Scraping Target for keyword: {keyword}")
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                products = soup.find_all('div', {'data-test': 'product-card'})
                print(f"Found {len(products)} potential products on Target")

                for product in products:
                    try:
                        title_elem = product.find('a', {'data-test': 'product-title'})
                        price_elem = product.find('span', {'data-test': 'product-price'})

                        if title_elem and price_elem:
                            title = title_elem.text.strip()
                            price = self._clean_price(price_elem.text)
                            product_url = 'https://www.target.com' + title_elem['href']
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
        """Scrape Walmart for Pokemon products"""
        results = []
        url = f"https://www.walmart.com/search?q={keyword}"

        try:
            print(f"Scraping Walmart for keyword: {keyword}")
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                products = soup.find_all('div', {'data-item-id': True})
                print(f"Found {len(products)} potential products on Walmart")

                for product in products:
                    try:
                        title_elem = product.find('span', {'data-automation-id': 'product-title'})
                        price_elem = product.find('div', {'data-automation-id': 'product-price'})
                        link_elem = product.find('a', {'data-item-id': True})

                        if all([title_elem, price_elem, link_elem]):
                            title = title_elem.text.strip()
                            price = self._clean_price(price_elem.text)
                            product_url = 'https://www.walmart.com' + link_elem['href']
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
        """Scrape Best Buy for Pokemon products"""
        results = []
        url = f"https://www.bestbuy.com/site/searchpage.jsp?st={keyword}"

        try:
            print(f"Scraping Best Buy for keyword: {keyword}")
            # Add specific Best Buy headers
            headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1'
            }
            response = self.session.get(url, headers=headers, timeout=15)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                products = soup.find_all('li', {'class': 'sku-item'})
                print(f"Found {len(products)} potential products on Best Buy")

                for product in products:
                    try:
                        title_elem = product.find('h4', {'class': 'sku-header'})
                        price_elem = product.find('div', {'class': 'priceView-customer-price'})
                        link_elem = product.find('a', {'class': 'image-link'})

                        if all([title_elem, price_elem, link_elem]):
                            title = title_elem.text.strip()
                            price = self._clean_price(price_elem.find('span').text)
                            product_url = 'https://www.bestbuy.com' + link_elem['href']
                            image_elem = product.find('img', {'class': 'product-image'})
                            image_url = image_elem['src'] if image_elem else None

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
        time.sleep(random.uniform(1, 2))  # Add delay between retailers
        results.extend(self.scrape_walmart(keyword))
        time.sleep(random.uniform(1, 2))
        results.extend(self.scrape_bestbuy(keyword))
        return results