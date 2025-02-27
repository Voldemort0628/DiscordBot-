import asyncio
import random
import time
import json
import base64
import hashlib
from typing import List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

class BestBuyProduct:
    def __init__(self, title: str, price: float, url: str, image_url: Optional[str] = None):
        self.title = title
        self.price = price
        self.url = url
        self.image_url = image_url
        self.retailer = 'bestbuy'

class BestBuyScraper:
    def __init__(self):
        self.base_url = "https://www.bestbuy.com"
        self.session_id = hashlib.md5(str(time.time()).encode()).hexdigest()
        self.init_time = int(time.time() * 1000)

    def _clean_price(self, price_str: str) -> float:
        """Convert price string to float"""
        try:
            return float(price_str.replace('$', '').replace(',', '').strip())
        except (ValueError, AttributeError):
            return 0.0

    def _generate_akamai_data(self) -> dict:
        """Generate Akamai sensor data"""
        timestamp = int(time.time() * 1000)
        events = [
            {"type": "load", "timestamp": self.init_time},
            {"type": "mousemove", "timestamp": self.init_time + 100},
            {"type": "scroll", "timestamp": self.init_time + 500},
            {"type": "click", "timestamp": timestamp}
        ]
        
        return {
            "events": events,
            "device": {
                "screenWidth": 1920,
                "screenHeight": 1080,
                "colorDepth": 24,
                "pixelRatio": 1,
                "localStorage": True,
                "sessionStorage": True,
                "indexedDB": True,
                "openDatabase": True,
                "cpuClass": "unknown",
                "platform": "Win32",
                "doNotTrack": "unknown",
                "plugins": "PDF Viewer,Chrome PDF Viewer,Chromium PDF Viewer",
                "canvas": True,
                "webGL": True,
                "webGLVendor": "Google Inc. (Intel)",
                "adBlock": False,
                "hasLiedLanguages": False,
                "hasLiedResolution": False,
                "hasLiedOs": False,
                "hasLiedBrowser": False,
                "touchSupport": {
                    "points": 0,
                    "event": False,
                    "start": False
                },
                "audio": "124.04347527516074"
            },
            "bm_sz": self.session_id,
            "akam_seq": int((timestamp - self.init_time) / 1000),
            "akam_ts": timestamp,
            "api_type": "js",
            "auth": hashlib.sha256(str(random.random()).encode()).hexdigest()
        }

    async def search_products(self, keyword: str) -> List[BestBuyProduct]:
        """Search Best Buy for products using Playwright with Akamai bypass"""
        results = []
        print(f"[Best Buy] Searching for: {keyword}")
        
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
                
                // Override Akamai detection methods
                window._phantom = false;
                window.callPhantom = null;
                window._selenium = false;
                window.callSelenium = null;
                window.domAutomation = false;
                window.domAutomationController = false;
            """)

            try:
                page = await context.new_page()
                
                # Add Akamai headers
                akamai_data = self._generate_akamai_data()
                await page.set_extra_http_headers({
                    '_abck': hashlib.sha256(str(time.time()).encode()).hexdigest(),
                    'bm_sz': self.session_id,
                    'X-Akamai-Sensor': base64.b64encode(json.dumps(akamai_data).encode()).decode(),
                })

                # Visit homepage first
                await page.goto(self.base_url)
                await asyncio.sleep(random.uniform(2, 4))
                
                # Perform search
                search_url = f"{self.base_url}/site/searchpage.jsp?st={keyword}"
                print(f"[Best Buy] Navigating to: {search_url}")
                
                await page.goto(search_url, wait_until='networkidle')
                await asyncio.sleep(random.uniform(2, 3))
                
                # Wait for product grid
                await page.wait_for_selector('.sku-item', timeout=30000)
                
                # Extract products
                product_cards = await page.query_selector_all('.sku-item')
                print(f"[Best Buy] Found {len(product_cards)} potential products")
                
                for card in product_cards:
                    try:
                        # Extract title
                        title_elem = await card.query_selector('.sku-header')
                        if not title_elem:
                            continue
                        title = await title_elem.text_content()
                        
                        # Only process Pokemon-related items
                        if 'pokemon' not in title.lower():
                            continue
                            
                        # Extract price
                        price_elem = await card.query_selector('.priceView-customer-price span')
                        if not price_elem:
                            continue
                        price_text = await price_elem.text_content()
                        price = self._clean_price(price_text)
                        
                        # Extract URL and image
                        url_elem = await card.query_selector('a.image-link')
                        if not url_elem:
                            continue
                        url = self.base_url + await url_elem.get_attribute('href')
                        
                        img_elem = await card.query_selector('img.product-image')
                        image_url = await img_elem.get_attribute('src') if img_elem else None
                        
                        # Create product object
                        product = BestBuyProduct(
                            title=title,
                            price=price,
                            url=url,
                            image_url=image_url
                        )
                        results.append(product)
                        print(f"[Best Buy] Found product: {title} at ${price}")
                        
                    except Exception as e:
                        print(f"[Best Buy] Error processing product card: {str(e)}")
                        continue
                        
            except Exception as e:
                print(f"[Best Buy] Scraping error: {str(e)}")
            finally:
                await browser.close()
                
        return results

    @staticmethod
    async def test_scraper():
        """Test the scraper with a sample search"""
        scraper = BestBuyScraper()
        products = await scraper.search_products("pokemon")
        print(f"\nFound {len(products)} Pokemon products at Best Buy:")
        for product in products:
            print(f"- {product.title}: ${product.price}")
