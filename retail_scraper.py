import trafilatura
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional
import json

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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def _clean_price(self, price_str: str) -> float:
        """Convert price string to float"""
        return float(price_str.replace('$', '').replace(',', '').strip())

    def scrape_target(self, keyword: str) -> List[RetailScrapeResult]:
        """Scrape Target for Pokemon products"""
        results = []
        url = f"https://www.target.com/s?searchTerm={keyword}"

        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                soup = BeautifulSoup(downloaded, 'lxml')
                products = soup.find_all('div', {'data-test': 'product-card'})

                for product in products:
                    try:
                        title = product.find('a', {'data-test': 'product-title'}).text.strip()
                        price = self._clean_price(product.find('span', {'data-test': 'product-price'}).text)
                        product_url = 'https://www.target.com' + product.find('a')['href']
                        image_url = product.find('img')['src']

                        results.append(RetailScrapeResult(
                            title=title,
                            price=price,
                            url=product_url,
                            retailer='target',
                            image_url=image_url
                        ))
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
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                soup = BeautifulSoup(downloaded, 'lxml')
                products = soup.find_all('div', {'data-item-id': True})

                for product in products:
                    try:
                        title = product.find('span', {'class': 'normal'}).text.strip()
                        price = self._clean_price(product.find('div', {'class': 'price-main'}).text)
                        product_url = 'https://www.walmart.com' + product.find('a')['href']
                        image_url = product.find('img')['src']

                        results.append(RetailScrapeResult(
                            title=title,
                            price=price,
                            url=product_url,
                            retailer='walmart',
                            image_url=image_url
                        ))
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
            # Best Buy requires additional headers
            headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0'
            }
            response = requests.get(url, headers={**self.session.headers, **headers}, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                products = soup.find_all('li', {'class': 'sku-item'})

                for product in products:
                    try:
                        title_elem = product.find('h4', {'class': 'sku-header'})
                        price_elem = product.find('div', {'class': 'priceView-customer-price'})
                        link_elem = product.find('a', {'class': 'image-link'})
                        image_elem = product.find('img', {'class': 'product-image'})

                        if all([title_elem, price_elem, link_elem]):
                            title = title_elem.text.strip()
                            price = self._clean_price(price_elem.find('span').text)
                            product_url = 'https://www.bestbuy.com' + link_elem['href']
                            image_url = image_elem['src'] if image_elem else None

                            results.append(RetailScrapeResult(
                                title=title,
                                price=price,
                                url=product_url,
                                retailer='bestbuy',
                                image_url=image_url
                            ))
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
        results.extend(self.scrape_walmart(keyword))
        results.extend(self.scrape_bestbuy(keyword))
        return results