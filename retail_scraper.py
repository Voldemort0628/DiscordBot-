import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional
import json
import time
import random

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15'
]

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
        self._rotate_user_agent()

    def _rotate_user_agent(self):
        """Randomly select a new User-Agent"""
        user_agent = random.choice(USER_AGENTS)
        self.session.headers.update({
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1'
        })

    def _clean_price(self, price_str: str) -> float:
        """Convert price string to float"""
        try:
            return float(price_str.replace('$', '').replace(',', '').strip())
        except (ValueError, AttributeError):
            return 0.0

    def _add_delay(self):
        """Add random delay between requests"""
        time.sleep(random.uniform(2, 4))

    def scrape_target(self, keyword: str) -> List[RetailScrapeResult]:
        """Scrape Target for Pokemon products"""
        results = []
        self._rotate_user_agent()

        try:
            # First get the category page to set cookies
            print(f"Scraping Target for keyword: {keyword}")
            base_url = "https://www.target.com"
            self.session.get(base_url)
            self._add_delay()

            # Now search with the keyword
            url = f"{base_url}/s?searchTerm={keyword}"
            response = self.session.get(url, timeout=15)

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
        """Scrape Walmart for Pokemon products"""
        results = []
        self._rotate_user_agent()

        try:
            # First visit homepage to get cookies
            print(f"Scraping Walmart for keyword: {keyword}")
            self.session.get("https://www.walmart.com")
            self._add_delay()

            # Add Walmart-specific headers
            headers = {
                'Referer': 'https://www.walmart.com',
                'Origin': 'https://www.walmart.com',
                'DNT': '1'
            }
            self.session.headers.update(headers)

            url = f"https://www.walmart.com/search?q={keyword}"
            response = self.session.get(url, timeout=15)

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
                            product_url = f"https://www.walmart.com{product.find('a')['href']}"
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
        self._rotate_user_agent()

        try:
            # First visit homepage to get cookies
            print(f"Scraping Best Buy for keyword: {keyword}")
            self.session.get("https://www.bestbuy.com")
            self._add_delay()

            # Add Best Buy specific headers
            headers = {
                'Referer': 'https://www.bestbuy.com',
                'Origin': 'https://www.bestbuy.com',
                'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="96"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            }
            self.session.headers.update(headers)

            url = f"https://www.bestbuy.com/site/searchpage.jsp?st={keyword}&cp=1"
            response = self.session.get(url, timeout=15)

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
                            product_url = f"https://www.bestbuy.com{link_elem['href']}" if link_elem else None
                            image_elem = product.find('img', {'class': 'product-image'})
                            image_url = image_elem['src'] if image_elem else None

                            if product_url:  # Only add if we have a valid URL
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
        self._add_delay()
        results.extend(self.scrape_walmart(keyword))
        self._add_delay()
        results.extend(self.scrape_bestbuy(keyword))
        return results