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

    async def _send_webhook_with_backoff(self, payload, attempt=0):
        """Send webhook with exponential backoff and adaptive rate limiting"""
        try:
            # Calculate backoff time with jitter
            backoff = (min(300, (2 ** attempt) * 0.5) if attempt > 0 else 0)  # Cap at 5 minutes
            if backoff > 0:
                backoff += random.uniform(0, backoff * 0.1)  # Add up to 10% jitter
                await asyncio.sleep(backoff)

            # Ensure we respect the rate limit
            current_time = time.time()
            async with self._lock:
                if self.rate_limit_remaining <= 1 and current_time < self.rate_limit_reset:
                    wait_time = self.rate_limit_reset - current_time + 0.1
                    logging.info(f"Rate limit approaching, waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                elif current_time - self.last_request_time < self.rate_limit_window:
                    sleep_time = self.rate_limit_window - (current_time - self.last_request_time)
                    sleep_time += random.uniform(0.1, 0.3)  # Add jitter
                    await asyncio.sleep(sleep_time)

            # Use connection pooling for better performance
            conn = aiohttp.TCPConnector(
                ssl=False,
                force_close=True,
                ttl_dns_cache=300,
                limit=5  # Limit concurrent connections
            )
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

                    response_text = await response.text()

                    if response.status == 429:  # Rate limited
                        retry_after = float(response.headers.get('Retry-After', 5))
                        logging.warning(f"Rate limited by Discord. Retrying after {retry_after}s")
                        await asyncio.sleep(retry_after)
                        if attempt < self.max_retries:
                            return await self._send_webhook_with_backoff(payload, attempt + 1)
                        return False

                    if 200 <= response.status < 300:
                        return True

                    logging.error(f"Discord webhook error: Status {response.status}, Response: {response_text}")
                    if attempt < self.max_retries:
                        return await self._send_webhook_with_backoff(payload, attempt + 1)
                    return False

        except Exception as e:
            logging.error(f"Webhook delivery error: {str(e)}")
            if attempt < self.max_retries:
                return await self._send_webhook_with_backoff(payload, attempt + 1)
            return False

    async def send_product_notification(self, product):
        """Send product notification with adaptive rate limiting and retry logic"""
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

        return await self._send_webhook_with_backoff(payload)