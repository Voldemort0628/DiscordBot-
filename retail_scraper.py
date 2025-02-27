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
        self.retry_counts = {}
        self.rate_limit = 1.0

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
            print(f"Scraping Target for keyword: {keyword}")

            # Initialize session with homepage first
            base_url = "https://www.target.com"
            self.session.get(base_url)
            self._add_delay()

            # Add Target-specific headers
            headers = {
                'Referer': 'https://www.target.com',
                'Origin': 'https://www.target.com',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            }
            self.session.headers.update(headers)

            # Make the search request
            search_url = f"{base_url}/s?searchTerm={keyword}"
            response = self.session.get(search_url, timeout=15)
            print(f"Target response status: {response.status_code}")

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')

                # Try multiple possible product container selectors
                products = (
                    soup.find_all('div', {'data-test': 'product-card'}) or
                    soup.find_all('div', {'data-test': 'productCard'}) or
                    soup.find_all('div', {'class': 'styles__StyledCol-sc-fw90uk-0'})
                )

                print(f"Found {len(products)} potential products on Target")

                for product in products:
                    try:
                        # Try multiple possible title selectors
                        title_elem = (
                            product.find('a', {'data-test': 'product-title'}) or
                            product.find('a', {'data-test': 'product-link'}) or
                            product.find('div', {'data-test': 'product-title'})
                        )

                        # Try multiple possible price selectors
                        price_elem = (
                            product.find('span', {'data-test': 'product-price'}) or
                            product.find('span', {'data-test': 'current-price'}) or
                            product.find('div', {'data-test': 'product-price'})
                        )

                        if title_elem and price_elem:
                            title = title_elem.text.strip()

                            # Only process Pokemon-related items
                            if 'pokemon' in title.lower():
                                price = self._clean_price(price_elem.text)

                                # Get URL from title element or parent
                                url_elem = title_elem if title_elem.name == 'a' else title_elem.find_parent('a')
                                product_url = base_url + url_elem['href'] if url_elem else None

                                # Try multiple possible image selectors
                                img_elem = (
                                    product.find('img', {'data-test': 'product-image'}) or
                                    product.find('img', {'class': 'styles__ProductImage'}) or
                                    product.find('img')
                                )
                                image_url = img_elem['src'] if img_elem else None

                                if product_url:
                                    result = RetailScrapeResult(
                                        title=title,
                                        price=price,
                                        url=product_url,
                                        retailer='target',
                                        image_url=image_url
                                    )
                                    results.append(result)
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
            print(f"Scraping Walmart for keyword: {keyword}")

            # Initialize session with homepage first
            self.session.get("https://www.walmart.com")
            self._add_delay()

            # Add Walmart-specific headers
            headers = {
                'Referer': 'https://www.walmart.com',
                'Origin': 'https://www.walmart.com',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            }
            self.session.headers.update(headers)

            search_url = f"https://www.walmart.com/search?q={keyword}"
            response = self.session.get(search_url, timeout=15)
            print(f"Walmart response status: {response.status_code}")

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')

                # Try multiple possible product container selectors
                products = (
                    soup.find_all('div', {'data-item-id': True}) or
                    soup.find_all('div', {'class': 'mb1 ph1 pa0-xl bb b--near-white w-25'}) or
                    soup.find_all('div', {'class': 'flex flex-wrap w-100 flex-grow-0 flex-shrink-0 ph2 pr0-xl pl4-xl mt0-xl mt3'})
                )

                print(f"Found {len(products)} potential products on Walmart")

                for product in products:
                    try:
                        # Try multiple possible title selectors
                        title_elem = (
                            product.find('span', {'data-automation-id': 'product-title'}) or
                            product.find('span', {'class': 'w_V_DM'}) or
                            product.find('span', {'class': 'lh-title'})
                        )

                        # Try multiple possible price selectors
                        price_elem = (
                            product.find('div', {'data-automation-id': 'product-price'}) or
                            product.find('div', {'class': 'b black f5 mr1 mr2-xl lh-copy f4-l'}) or
                            product.find('div', {'class': 'flex flex-wrap justify-start items-center lh-title mb2 mb1-m'})
                        )

                        if title_elem and price_elem:
                            title = title_elem.text.strip()

                            # Only process Pokemon-related items
                            if 'pokemon' in title.lower():
                                price = self._clean_price(price_elem.text)

                                # Try multiple possible link selectors
                                link_elem = (
                                    product.find('a', {'link-identifier': 'linkText'}) or
                                    product.find('a', {'class': 'absolute w-100 h-100 z-1 hide-sibling-opacity'}) or
                                    product.find('a')
                                )
                                product_url = f"https://www.walmart.com{link_elem['href']}" if link_elem else None

                                # Try multiple possible image selectors
                                img_elem = (
                                    product.find('img', {'data-automation-id': 'product-image'}) or
                                    product.find('img', {'class': 'absolute top-0 left-0'}) or
                                    product.find('img')
                                )
                                image_url = img_elem['src'] if img_elem else None

                                if product_url:
                                    result = RetailScrapeResult(
                                        title=title,
                                        price=price,
                                        url=product_url,
                                        retailer='walmart',
                                        image_url=image_url
                                    )
                                    results.append(result)
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
            print(f"Scraping Best Buy for keyword: {keyword}")

            # Initialize session with homepage first
            self.session.get("https://www.bestbuy.com")
            self._add_delay()

            # Add Best Buy specific headers
            headers = {
                'Referer': 'https://www.bestbuy.com',
                'Origin': 'https://www.bestbuy.com',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="96"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            }
            self.session.headers.update(headers)

            search_url = f"https://www.bestbuy.com/site/searchpage.jsp?st={keyword}&cp=1"
            response = self.session.get(search_url, timeout=15)
            print(f"Best Buy response status: {response.status_code}")

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')

                # Try multiple possible product container selectors
                products = (
                    soup.find_all('li', {'class': 'sku-item'}) or
                    soup.find_all('div', {'class': 'shop-sku-list-item'}) or
                    soup.find_all('div', {'class': 'list-item'})
                )

                print(f"Found {len(products)} potential products on Best Buy")

                for product in products:
                    try:
                        # Try multiple possible title selectors
                        title_elem = (
                            product.find('h4', {'class': 'sku-header'}) or
                            product.find('h4', {'class': 'sku-title'}) or
                            product.find('div', {'class': 'sku-title'})
                        )

                        # Try multiple possible price selectors
                        price_elem = (
                            product.find('div', {'class': 'priceView-customer-price'}) or
                            product.find('div', {'class': 'priceView-hero-price'}) or
                            product.find('span', {'class': 'sr-only'}, string=lambda x: x and 'current price' in x.lower())
                        )

                        if title_elem and price_elem:
                            title = title_elem.text.strip()

                            # Only process Pokemon-related items
                            if 'pokemon' in title.lower():
                                # Handle different price element structures
                                price_text = price_elem.find('span').text if price_elem.find('span') else price_elem.text
                                price = self._clean_price(price_text)

                                # Try multiple possible link selectors
                                link_elem = (
                                    product.find('a', {'class': 'image-link'}) or
                                    product.find('a', {'class': 'product-image'}) or
                                    product.find('a')
                                )
                                product_url = f"https://www.bestbuy.com{link_elem['href']}" if link_elem else None

                                # Try multiple possible image selectors
                                img_elem = (
                                    product.find('img', {'class': 'product-image'}) or
                                    product.find('img', {'class': 'thumb'}) or
                                    product.find('img')
                                )
                                image_url = img_elem['src'] if img_elem else None

                                if product_url:
                                    result = RetailScrapeResult(
                                        title=title,
                                        price=price,
                                        url=product_url,
                                        retailer='bestbuy',
                                        image_url=image_url
                                    )
                                    results.append(result)
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