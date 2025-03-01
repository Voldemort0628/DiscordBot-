import json
import aiohttp
import asyncio
import time
from datetime import datetime
from config import INFO_COLOR
import random
import logging
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RateLimitedDiscordWebhook:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.last_request_time = 0
        self.rate_limit_window = 2  # 2 seconds between requests
        self.max_retries = 3
        self.rate_limit_remaining = 5
        self.rate_limit_reset = 0
        self._lock = asyncio.Lock()
        self._notification_queue = deque(maxlen=25)  # Max 25 items in queue
        self._batch_size = 10  # Max products per webhook message
        self._batch_timeout = 5  # Seconds to wait before sending non-full batch
        self._last_batch_time = time.time()
        self._processing = False

    async def _process_notification_queue(self):
        """Process queued notifications in batches"""
        if self._processing:
            return

        try:
            self._processing = True
            while True:
                current_time = time.time()
                if (len(self._notification_queue) >= self._batch_size or 
                    (len(self._notification_queue) > 0 and 
                     current_time - self._last_batch_time >= self._batch_timeout)):

                    # Take up to batch_size items
                    batch = []
                    while len(batch) < self._batch_size and self._notification_queue:
                        batch.append(self._notification_queue.popleft())

                    if batch:
                        await self._send_batch(batch)
                        self._last_batch_time = current_time

                await asyncio.sleep(0.5)  # Check queue every 500ms

                if not self._notification_queue:
                    break

        finally:
            self._processing = False

    async def _send_batch(self, products):
        """Send a batch of products in a single webhook message"""
        for attempt in range(self.max_retries):
            try:
                current_time = time.time()

                async with self._lock:
                    if self.rate_limit_remaining <= 1 and current_time < self.rate_limit_reset:
                        wait_time = self.rate_limit_reset - current_time + 0.1
                        logging.info(f"Rate limited, waiting {wait_time:.2f}s")
                        await asyncio.sleep(wait_time)
                    elif current_time - self.last_request_time < self.rate_limit_window:
                        sleep_time = self.rate_limit_window - (current_time - self.last_request_time)
                        sleep_time += random.uniform(0.1, 0.3)
                        await asyncio.sleep(sleep_time)

                embeds = []
                for product in products:
                    embed = {
                        "title": str(product["title"])[:256],
                        "url": str(product["url"])[:512],
                        "color": INFO_COLOR,
                        "timestamp": datetime.utcnow().isoformat()
                    }

                    if product.get("image_url"):
                        embed["thumbnail"] = {"url": str(product["image_url"])[:512]}

                    fields = [
                        {
                            "name": "Price",
                            "value": f"${product['price']}" if isinstance(product['price'], (int, float)) 
                                    else str(product['price'])[:1024],
                            "inline": True
                        }
                    ]

                    if "retailer" in product:
                        fields.append({
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

                        sizes_value = "\n".join(sizes_text)[:1024]
                        fields.append({
                            "name": "Sizes / Stock",
                            "value": sizes_value,
                            "inline": False
                        })

                    embed["fields"] = fields
                    embeds.append(embed)

                # Split into smaller batches if needed (Discord limit is 10 embeds)
                for i in range(0, len(embeds), 10):
                    batch_embeds = embeds[i:i + 10]
                    payload = {
                        "username": "SoleAddictionsLLC Monitor",
                        "embeds": batch_embeds
                    }

                    logging.info(f"Sending batch webhook - Attempt {attempt + 1}/{self.max_retries}")

                    conn = aiohttp.TCPConnector(ssl=False, force_close=True, ttl_dns_cache=300)
                    timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=10)

                    async with aiohttp.ClientSession(connector=conn, timeout=timeout) as session:
                        async with session.post(
                            self.webhook_url,
                            json=payload,
                            headers={"Content-Type": "application/json"},
                        ) as response:
                            self.last_request_time = time.time()

                            if 'X-RateLimit-Remaining' in response.headers:
                                self.rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', 5))
                            if 'X-RateLimit-Reset-After' in response.headers:
                                reset_after = float(response.headers.get('X-RateLimit-Reset-After', 0))
                                self.rate_limit_reset = time.time() + reset_after

                            response_text = await response.text()

                            if response.status == 429:
                                retry_after = float(response.headers.get('Retry-After', 5))
                                logging.warning(f"Rate limited by Discord. Retrying after {retry_after}s")
                                await asyncio.sleep(retry_after)
                                continue

                            try:
                                response.raise_for_status()
                                logging.info(f"Successfully sent batch webhook with {len(batch_embeds)} products")
                                return True
                            except aiohttp.ClientResponseError as e:
                                if response.status == 400:
                                    logging.error(f"Bad request error: {response_text}")
                                    if "payload" in response_text.lower():
                                        return False
                                raise

            except aiohttp.ClientError as e:
                logging.error(f"Network error sending webhook batch: {str(e)}")
                backoff = min((2 ** attempt) * 1.0, 10)  # Cap at 10 seconds
                await asyncio.sleep(backoff)
            except Exception as e:
                logging.error(f"Unexpected error in webhook batch: {str(e)}")
                await asyncio.sleep(1)

        logging.error(f"Failed to send webhook batch after {self.max_retries} retries")
        return False

    async def send_product_notification(self, product):
        """Queue a product notification for batched sending"""
        self._notification_queue.append(product)

        if not self._processing:
            asyncio.create_task(self._process_notification_queue())

        return True  # Return immediately since actual sending is handled by queue processor