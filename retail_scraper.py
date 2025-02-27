import json
import time
import random
import asyncio
import urllib.parse
from typing import List, Dict, Optional
from datetime import datetime
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium_stealth import stealth
from playwright.async_api import async_playwright

class RetailScrapeResult:
    def __init__(self, title: str, price: float, url: str, retailer: str, image_url: Optional[str] = None):
        self.title = title
        self.price = price
        self.url = url
        self.retailer = retailer
        self.image_url = image_url

class RetailScraper:
    def __init__(self):
        self.driver = None
        self.init_time = int(time.time() * 1000)
        self.retry_counts = {}
        self.rate_limit = 1.0

    def _setup_driver(self):
        """Setup undetected-chromedriver with stealth"""
        options = uc.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')

        self.driver = uc.Chrome(options=options)

        # Apply stealth settings
        stealth(self.driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

    def _clean_price(self, price_str: str) -> float:
        """Convert price string to float"""
        try:
            return float(price_str.replace('$', '').replace(',', '').strip())
        except (ValueError, AttributeError):
            return 0.0

    async def _get_with_playwright(self, url: str, retailer: str) -> str:
        """Use Playwright for JavaScript-heavy pages"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            )

            page = await context.new_page()

            # Add stealth scripts
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            # Handle retailer-specific logic
            if retailer == 'walmart':
                await page.route('**/*', lambda route: route.continue_() if 'px' not in route.request.url.lower() else route.abort())

            response = await page.goto(url, wait_until='networkidle')
            content = await page.content()

            await browser.close()
            return content

    def scrape_target(self, keyword: str) -> List[RetailScrapeResult]:
        """Scrape Target using Playwright"""
        results = []
        if not self.driver:
            self._setup_driver()

        try:
            print(f"Scraping Target for keyword: {keyword}")
            base_url = "https://www.target.com"
            search_url = f"{base_url}/s?searchTerm={urllib.parse.quote(keyword)}"

            # Use undetected-chromedriver for initial page load
            self.driver.get(search_url)
            time.sleep(random.uniform(2, 4))  # Random delay

            # Wait for product cards to load
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-test="product-card"]'))
            )

            # Parse the page content
            soup = BeautifulSoup(self.driver.page_source, 'lxml')
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

    async def scrape_walmart(self, keyword: str) -> List[RetailScrapeResult]:
        """Scrape Walmart using Playwright with PX bypass"""
        results = []
        try:
            print(f"Scraping Walmart for keyword: {keyword}")
            base_url = "https://www.walmart.com"
            search_url = f"{base_url}/search?q={urllib.parse.quote(keyword)}"

            # Use Playwright for JavaScript challenge solving
            content = await self._get_with_playwright(search_url, 'walmart')

            soup = BeautifulSoup(content, 'lxml')
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
        """Scrape Best Buy using undetected-chromedriver"""
        results = []
        if not self.driver:
            self._setup_driver()

        try:
            print(f"Scraping Best Buy for keyword: {keyword}")
            base_url = "https://www.bestbuy.com"
            search_url = f"{base_url}/site/searchpage.jsp?st={urllib.parse.quote(keyword)}"

            self.driver.get(search_url)
            time.sleep(random.uniform(2, 4))  # Random delay

            # Wait for product containers to load
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CLASS_NAME, 'sku-item'))
            )

            soup = BeautifulSoup(self.driver.page_source, 'lxml')
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

    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            self.driver.quit()
            self.driver = None

    async def scrape_all(self, keyword: str) -> List[RetailScrapeResult]:
        """Scrape all supported retailers"""
        results = []
        try:
            # Scrape Target (synchronous)
            results.extend(self.scrape_target(keyword))
            time.sleep(random.uniform(2, 4))

            # Scrape Walmart (asynchronous)
            walmart_results = await self.scrape_walmart(keyword)
            results.extend(walmart_results)
            time.sleep(random.uniform(2, 4))

            # Scrape Best Buy (synchronous)
            results.extend(self.scrape_bestbuy(keyword))
        finally:
            self.cleanup()

        return results