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
        self.rate_limit_window = 2  # Increased from 1.25 to 2 seconds between requests
        self.max_retries = 3  # Reduced from 5 to 3 to avoid excessive retries
        self.rate_limit_remaining = 5
        self.rate_limit_reset = 0
        self._lock = asyncio.Lock()
        self._pending_notifications = []
        self._batch_size = 5  # Maximum webhooks to combine in one message
        self._batch_timeout = 10  # Seconds to wait before sending a non-full batch

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
                        sleep_time += random.uniform(0.1, 0.3)  # Increased jitter
                        await asyncio.sleep(sleep_time)

                # Create webhook content with validation
                embed = {
                    "title": str(product["title"])[:256],  # Discord limit
                    "url": str(product["url"])[:512],  # Discord limit
                    "color": INFO_COLOR,
                    "timestamp": datetime.utcnow().isoformat(),
                }

                if product.get("image_url"):
                    embed["thumbnail"] = {"url": str(product["image_url"])[:512]}

                embed["fields"] = [
                    {
                        "name": "Price",
                        "value": f"${product['price']}" if isinstance(product['price'], (int, float)) else str(product['price'])[:1024],
                        "inline": True
                    }
                ]

                if "retailer" in product:
                    embed["fields"].append({
                        "name": "Retailer",
                        "value": str(product["retailer"])[:1024],
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

                    # Ensure size text doesn't exceed Discord's limit
                    sizes_value = "\n".join(sizes_text)[:1024]
                    embed["fields"].append({
                        "name": "Sizes / Stock",
                        "value": sizes_value,
                        "inline": False
                    })

                    links_text = [
                        f"[Quick Purchase]({product['url']}/cart.js) | " +
                        f"[Market Price](https://stockx.com/search?s={product['title'].replace(' ', '%20')})",
                        "",  # Empty line for spacing
                        f"[Product Link]({product['url']}) | Stock: {product.get('stock', 0)}",
                    ]

                    # Ensure links text doesn't exceed Discord's limit
                    links_value = "\n".join(links_text)[:1024]
                    embed["fields"].append({
                        "name": "Links",
                        "value": links_value,
                        "inline": False
                    })

                payload = {
                    "username": "SoleAddictionsLLC Monitor",
                    "embeds": [embed]
                }

                # Validate payload size (Discord limit is 8MB)
                payload_size = len(json.dumps(payload).encode('utf-8'))
                if payload_size > 8_000_000:  # 8MB limit
                    logging.error(f"Payload too large ({payload_size} bytes), truncating content")
                    # Truncate fields if necessary
                    while payload_size > 8_000_000 and embed["fields"]:
                        embed["fields"].pop()
                        payload_size = len(json.dumps(payload).encode('utf-8'))

                logging.info(f"Sending webhook notification - Attempt {attempt + 1}/{self.max_retries}")
                logging.debug(f"Webhook payload: {json.dumps(payload, indent=2)}")

                try:
                    conn = aiohttp.TCPConnector(ssl=False, force_close=True, ttl_dns_cache=300)
                    timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=10)

                    async with aiohttp.ClientSession(connector=conn, timeout=timeout) as session:
                        async with session.post(
                            self.webhook_url,
                            json=payload,
                            headers={"Content-Type": "application/json"},
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

                            # Read response body before raising for status
                            response_text = await response.text()
                            logging.info(f"Discord response status: {response.status}")
                            logging.debug(f"Discord response headers: {dict(response.headers)}")
                            logging.debug(f"Discord response body: {response_text}")

                            try:
                                response.raise_for_status()
                                logging.info(f"Successfully sent webhook notification for {product['title']}")
                                return True
                            except aiohttp.ClientResponseError as e:
                                if response.status == 400:
                                    logging.error(f"Bad request error. Response: {response_text}")
                                    # If it's a payload issue, don't retry
                                    if "payload" in response_text.lower():
                                        return False
                                raise  # Re-raise for other status codes

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