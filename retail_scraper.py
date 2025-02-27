import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional
import json
import time
import random
import urllib.parse
from bot_detection_ml import MLBasedBotBypass

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
        self.ml_bypass = MLBasedBotBypass()
        self._rotate_user_agent()
        self.retry_counts = {}
        self.rate_limit = 1.0

    def _make_request(self, url: str, referrer: Optional[str] = None) -> requests.Response:
        """Make a request with ML-based bot detection bypass"""
        # Generate timing for request
        delay = self.ml_bypass.generate_request_timing('page_load')
        time.sleep(delay)

        # Simulate user behavior before request
        behaviors = self.ml_bypass.simulate_user_behavior()
        for behavior in behaviors:
            time.sleep(behavior['timestamp'] - (0 if not behaviors else behaviors[-1]['timestamp']))

        # Get ML-optimized headers
        headers = self.ml_bypass.get_request_headers()
        if referrer:
            headers['Referer'] = referrer

        # Make the request
        response = self.session.get(url, headers=headers, timeout=15)

        # Analyze response and update patterns
        analysis = self.ml_bypass.analyze_response(response.headers)
        success = response.status_code == 200
        self.ml_bypass.update_patterns(success, {
            'status_code': response.status_code,
            'headers': dict(response.headers),
            'url': url
        })

        return response

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

    def _init_session(self, base_url: str, referrers: List[str]):
        """Initialize session with ML-based behavior patterns"""
        for referrer in referrers:
            try:
                full_url = f"{base_url}{referrer}"
                self._make_request(full_url)
            except Exception as e:
                print(f"Error initializing session at {full_url}: {e}")

    def scrape_target(self, keyword: str) -> List[RetailScrapeResult]:
        """Scrape Target with ML-based bot detection bypass"""
        results = []
        self._rotate_user_agent()

        try:
            print(f"Scraping Target for keyword: {keyword}")
            base_url = "https://www.target.com"

            # Initialize session with ML-based behavior
            referrers = [
                "/",
                "/s?category=5xt1a",
                "/s?category=54hza"
            ]
            self._init_session(base_url, referrers)

            # Make the search request with ML bypass
            search_url = f"{base_url}/s?searchTerm={urllib.parse.quote(keyword)}"
            response = self._make_request(
                search_url,
                referrer='https://www.target.com/c/toys-games/-/N-5xtb0'
            )

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                product_containers = soup.find_all(['div', 'li'], {
                    'class': lambda x: x and any(c in str(x).lower() for c in [
                        'productscontainer',
                        'productcontainer',
                        'product-card',
                        'styles__StyledCol'
                    ])
                })

                print(f"Found {len(product_containers)} potential products on Target")

                for container in product_containers:
                    try:
                        title_elem = None
                        for selector in [
                            {'data-test': 'product-title'},
                            {'class': 'Heading__StyledHeading'},
                            {'class': 'h-display-flex'}
                        ]:
                            title_elem = container.find(['a', 'div', 'span'], selector)
                            if title_elem:
                                break

                        price_elem = None
                        for selector in [
                            {'data-test': 'product-price'},
                            {'class': 'h-text-bs'},
                            {'class': 'ProductPriceDetails'}
                        ]:
                            price_elem = container.find(['span', 'div'], selector)
                            if price_elem:
                                break

                        if title_elem and price_elem and 'pokemon' in title_elem.text.lower():
                            title = title_elem.text.strip()
                            price = self._clean_price(price_elem.text)

                            url_elem = title_elem if title_elem.name == 'a' else container.find('a')
                            if url_elem and 'href' in url_elem.attrs:
                                product_url = base_url + url_elem['href'] if not url_elem['href'].startswith('http') else url_elem['href']

                                img_elem = container.find('img')
                                image_url = img_elem['src'] if img_elem and 'src' in img_elem.attrs else None

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
        """Scrape Walmart with ML-based bot detection bypass"""
        results = []
        self._rotate_user_agent()

        try:
            print(f"Scraping Walmart for keyword: {keyword}")
            base_url = "https://www.walmart.com"

            # Initialize session with ML-based behavior
            referrers = [
                "/",
                "/browse/toys/235762",
                "/browse/games/4171"
            ]
            self._init_session(base_url, referrers)

            # Make the search request with ML bypass
            search_url = f"{base_url}/search?q={urllib.parse.quote(keyword)}"
            response = self._make_request(
                search_url,
                referrer='https://www.walmart.com/browse/toys/235762'
            )

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')

                product_containers = []
                for selector in [
                    {'data-item-id': True},
                    {'data-element-id': 'product-item'},
                    {'class': 'mb1 ph1 pa0-xl bb b--near-white w-25'}
                ]:
                    containers = soup.find_all('div', selector)
                    if containers:
                        product_containers.extend(containers)
                        break

                print(f"Found {len(product_containers)} potential products on Walmart")

                for container in product_containers:
                    try:
                        title_elem = None
                        for selector in [
                            {'data-automation-id': 'product-title'},
                            {'class': 'w_V_DM'},
                            {'class': 'lh-title'}
                        ]:
                            title_elem = container.find(['span', 'div'], selector)
                            if title_elem:
                                break

                        price_elem = None
                        for selector in [
                            {'data-automation-id': 'product-price'},
                            {'class': 'b black f5 mr1 mr2-xl lh-copy f4-l'},
                            {'class': 'price-main'}
                        ]:
                            price_elem = container.find(['div', 'span'], selector)
                            if price_elem:
                                break

                        if title_elem and price_elem and 'pokemon' in title_elem.text.lower():
                            title = title_elem.text.strip()
                            price = self._clean_price(price_elem.text)

                            url_elem = container.find('a', href=True)
                            if url_elem:
                                product_url = f"{base_url}{url_elem['href']}" if not url_elem['href'].startswith('http') else url_elem['href']

                                img_elem = container.find('img')
                                image_url = img_elem['src'] if img_elem and 'src' in img_elem.attrs else None

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
        """Scrape Best Buy with ML-based bot detection bypass"""
        results = []
        self._rotate_user_agent()

        try:
            print(f"Scraping Best Buy for keyword: {keyword}")
            base_url = "https://www.bestbuy.com"

            # Initialize session with ML-based behavior
            referrers = [
                "/",
                "/site/video-games/nintendo-switch-games/pcmcat1484080052161.c",
                "/site/toys-games-and-collectibles/toys-and-collectibles/pcmcat252700050006.c"
            ]
            self._init_session(base_url, referrers)

            # Make the search request with ML bypass
            search_url = f"{base_url}/site/searchpage.jsp?st={urllib.parse.quote(keyword)}&cp=1"
            response = self._make_request(
                search_url,
                referrer='https://www.bestbuy.com/site/toys-games-and-collectibles/toys-and-collectibles/pcmcat252700050006.c'
            )

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')

                product_containers = []
                for selector in [
                    {'class': 'sku-item'},
                    {'class': 'shop-sku-list-item'},
                    {'class': 'list-item'}
                ]:
                    containers = soup.find_all(['li', 'div'], selector)
                    if containers:
                        product_containers.extend(containers)
                        break

                print(f"Found {len(product_containers)} potential products on Best Buy")

                for container in product_containers:
                    try:
                        title_elem = None
                        for selector in [
                            {'class': 'sku-header'},
                            {'class': 'sku-title'},
                            {'class': 'heading-5 v-fw-regular'}
                        ]:
                            title_elem = container.find(['h4', 'div'], selector)
                            if title_elem:
                                break

                        price_elem = None
                        for selector in [
                            {'class': 'priceView-customer-price'},
                            {'class': 'priceView-hero-price'},
                            {'class': 'price-block'}
                        ]:
                            price_elem = container.find('div', selector)
                            if price_elem:
                                break

                        if title_elem and price_elem and 'pokemon' in title_elem.text.lower():
                            title = title_elem.text.strip()
                            price_text = price_elem.find('span').text if price_elem.find('span') else price_elem.text
                            price = self._clean_price(price_text)

                            url_elem = container.find('a', href=True)
                            if url_elem:
                                product_url = f"{base_url}{url_elem['href']}" if not url_elem['href'].startswith('http') else url_elem['href']

                                img_elem = container.find('img')
                                image_url = img_elem['src'] if img_elem and 'src' in img_elem.attrs else None

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