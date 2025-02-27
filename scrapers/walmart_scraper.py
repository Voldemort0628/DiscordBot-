import asyncio
import random
import time
import json
import base64
import hashlib
from typing import List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

class WalmartProduct:
    def __init__(self, title: str, price: float, url: str, image_url: Optional[str] = None):
        self.title = title
        self.price = price
        self.url = url
        self.image_url = image_url
        self.retailer = 'walmart'

class WalmartScraper:
    def __init__(self):
        self.base_url = "https://www.walmart.com"
        self.session_id = hashlib.md5(str(time.time()).encode()).hexdigest()
        self.init_time = int(time.time() * 1000)

    def _clean_price(self, price_str: str) -> float:
        """Convert price string to float"""
        try:
            return float(price_str.replace('$', '').replace(',', '').strip())
        except (ValueError, AttributeError):
            return 0.0

    def _generate_px_data(self) -> dict:
        """Generate PerimeterX payload data"""
        return {
            "uuid": self.session_id,
            "vid": "",
            "tid": hashlib.md5(str(random.random()).encode()).hexdigest(),
            "sid": self.session_id,
            "ft": self.init_time,
            "seq": int((time.time() * 1000 - self.init_time) / 1000),
            "en": "NTA",
            "pc": "1.5.0",
            "ex": {
                "baseUrl": "www.walmart.com",
                "cookie": True,
                "localStorage": True,
                "webGL": True
            }
        }

    async def search_products(self, keyword: str) -> List[WalmartProduct]:
        """Search Walmart for products using Playwright with PX bypass"""
        results = []
        print(f"[Walmart] Searching for: {keyword}")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']
            )
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            )

            # Add stealth scripts
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                window.chrome = { runtime: {} };
                
                // Block PX sensors
                window._pxAppId = null;
                window._pxJsClientSrc = null;
                window._pxFirstPartyEnabled = false;
            """)

            try:
                page = await context.new_page()
                
                # Set up request interception
                async def handle_route(route):
                    if 'px' in route.request.url.lower():
                        await route.abort()
                    else:
                        await route.continue_()
                
                await page.route('**/*', handle_route)
                
                # Add PX headers
                px_payload = self._generate_px_data()
                await page.set_extra_http_headers({
                    'X-PX-AUTHORIZATION': base64.b64encode(json.dumps(px_payload).encode()).decode(),
                    'X-PX-TIMESTAMP': str(int(time.time() * 1000))
                })

                # Visit homepage first
                await page.goto(self.base_url)
                await asyncio.sleep(random.uniform(2, 4))
                
                # Perform search
                search_url = f"{self.base_url}/search?q={keyword}"
                print(f"[Walmart] Navigating to: {search_url}")
                
                await page.goto(search_url, wait_until='networkidle')
                await asyncio.sleep(random.uniform(2, 3))
                
                # Wait for product grid
                await page.wait_for_selector('[data-item-id]', timeout=30000)
                
                # Extract products
                product_cards = await page.query_selector_all('[data-item-id]')
                print(f"[Walmart] Found {len(product_cards)} potential products")
                
                for card in product_cards:
                    try:
                        # Extract title
                        title_elem = await card.query_selector('[data-automation-id="product-title"]')
                        if not title_elem:
                            continue
                        title = await title_elem.text_content()
                        
                        # Only process Pokemon-related items
                        if 'pokemon' not in title.lower():
                            continue
                            
                        # Extract price
                        price_elem = await card.query_selector('[data-automation-id="product-price"]')
                        if not price_elem:
                            continue
                        price_text = await price_elem.text_content()
                        price = self._clean_price(price_text)
                        
                        # Extract URL and image
                        url_elem = await card.query_selector('a[link-identifier="linkText"]')
                        if not url_elem:
                            continue
                        url = self.base_url + await url_elem.get_attribute('href')
                        
                        img_elem = await card.query_selector('img')
                        image_url = await img_elem.get_attribute('src') if img_elem else None
                        
                        # Create product object
                        product = WalmartProduct(
                            title=title,
                            price=price,
                            url=url,
                            image_url=image_url
                        )
                        results.append(product)
                        print(f"[Walmart] Found product: {title} at ${price}")
                        
                    except Exception as e:
                        print(f"[Walmart] Error processing product card: {str(e)}")
                        continue
                        
            except Exception as e:
                print(f"[Walmart] Scraping error: {str(e)}")
            finally:
                await browser.close()
                
        return results

    @staticmethod
    async def test_scraper():
        """Test the scraper with a sample search"""
        scraper = WalmartScraper()
        products = await scraper.search_products("pokemon")
        print(f"\nFound {len(products)} Pokemon products at Walmart:")
        for product in products:
            print(f"- {product.title}: ${product.price}")
