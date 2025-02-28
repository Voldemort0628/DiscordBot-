import json
import aiohttp
import asyncio
import time
from datetime import datetime
from config import INFO_COLOR
import random
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RateLimitedDiscordWebhook:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.last_request_time = 0
        self.rate_limit_window = 1.25  # seconds between requests
        self.max_retries = 5
        self.rate_limit_remaining = 5
        self.rate_limit_reset = 0
        self._lock = asyncio.Lock()

    async def send_product_notification(self, product):
        """Send product notification with adaptive rate limiting and retry logic"""
        for attempt in range(self.max_retries):
            try:
                current_time = time.time()

                async with self._lock:
                    if self.rate_limit_remaining <= 1 and current_time < self.rate_limit_reset:
                        wait_time = self.rate_limit_reset - current_time + 0.1
                        logging.info(f"Waiting for Discord rate limit to reset. Sleeping {wait_time:.2f}s")
                        await asyncio.sleep(wait_time)
                    elif current_time - self.last_request_time < self.rate_limit_window:
                        sleep_time = self.rate_limit_window - (current_time - self.last_request_time)
                        sleep_time += random.uniform(0.05, 0.2)  # Add jitter
                        await asyncio.sleep(sleep_time)

                # Create webhook content
                embed = {
                    "title": product["title"],
                    "url": product["url"],
                    "color": INFO_COLOR,
                    "timestamp": datetime.utcnow().isoformat(),
                }

                if product.get("image_url"):
                    embed["thumbnail"] = {"url": product["image_url"]}

                embed["fields"] = [
                    {
                        "name": "Price",
                        "value": f"${product['price']}" if isinstance(product['price'], (int, float)) else product['price'],
                        "inline": True
                    }
                ]

                if "retailer" in product:
                    embed["fields"].append({
                        "name": "Retailer",
                        "value": product["retailer"],
                        "inline": True
                    })

                if product.get("sizes"):
                    sizes_text = []
                    for size, qty in product["sizes"].items():
                        base_url = product["url"]
                        variant_id = product["variants"].get(size, "")
                        size_text = f"• {size} | QT [{qty}]"
                        if variant_id:
                            cart_url = f"{base_url}?variant={variant_id}"
                            size_text = f"[{size_text}]({cart_url})"
                        sizes_text.append(size_text)

                    embed["fields"].append({
                        "name": "Sizes / Stock",
                        "value": "\n".join(sizes_text),
                        "inline": False
                    })

                    links_text = [
                        f"[Quick Purchase]({product['url']}/cart.js) | " +
                        f"[Market Price](https://stockx.com/search?s={product['title'].replace(' ', '%20')})",
                        "",  # Empty line for spacing
                        f"[Product Link]({product['url']}) | Stock: {product.get('stock', 0)}",
                    ]

                    embed["fields"].append({
                        "name": "Links",
                        "value": "\n".join(links_text),
                        "inline": False
                    })

                payload = {
                    "username": "SoleAddictionsLLC Monitor",
                    "avatar_url": "https://cdn.shopify.com/shopifycloud/brochure/assets/brand-assets/shopify-logo-primary-logo-456baa801ee66a0a435671082365958316831c9960c480451dd0330bcdae304f.svg",
                    "embeds": [embed]
                }

                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            self.webhook_url,
                            json=payload,
                            headers={"Content-Type": "application/json"},
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as response:
                            # Update rate limit tracking
                            self.last_request_time = time.time()

                            if 'X-RateLimit-Remaining' in response.headers:
                                self.rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', 5))
                            if 'X-RateLimit-Reset-After' in response.headers:
                                reset_after = float(response.headers.get('X-RateLimit-Reset-After', 0))
                                self.rate_limit_reset = time.time() + reset_after

                            if response.status == 429:  # Rate limited
                                retry_after = float(response.headers.get('Retry-After', 5))
                                logging.warning(f"Rate limited by Discord. Retrying after {retry_after}s")
                                await asyncio.sleep(retry_after)
                                continue

                            await response.read()
                            response.raise_for_status()
                            logging.info(f"Successfully sent webhook notification for {product['title']}")
                            return True

                except aiohttp.ClientError as e:
                    logging.error(f"Network error sending Discord webhook for {product['title']}: {str(e)}")
                    backoff = min((2 ** attempt) * 0.5, 5)  # Cap at 5 seconds
                    await asyncio.sleep(backoff)
                except Exception as e:
                    logging.error(f"Unexpected error sending Discord webhook for {product['title']}: {str(e)}")
                    await asyncio.sleep(1)

            except Exception as outer_e:
                logging.error(f"Outer exception in webhook notification: {str(outer_e)}")
                await asyncio.sleep(1)

        logging.error(f"Failed to send webhook for {product['title']} after {self.max_retries} retries")
        return False