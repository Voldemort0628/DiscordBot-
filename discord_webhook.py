import json
import requests
import time
from datetime import datetime
from config import INFO_COLOR
import random
import asyncio
from collections import deque
from typing import Dict, Optional
from logger_config import webhook_logger, log_webhook_error

logger = webhook_logger

class DiscordWebhook:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url

    def send_product_notification(self, product):
        """Simple webhook sender - fallback implementation"""
        try:
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

            payload = {
                "username": "SoleAddictionsLLC Monitor",
                "avatar_url": "https://cdn.shopify.com/shopifycloud/brochure/assets/brand-assets/shopify-logo-primary-logo-456baa801ee66a0a435671082365958316831c9960c480451dd0330bcdae304f.svg",
                "embeds": [embed]
            }

            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=3
            )
            response.raise_for_status()
            return True
        except Exception as e:
            log_webhook_error(self.webhook_url, e)
            return False

class RateLimitedDiscordWebhook:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.session = requests.Session()
        self.message_queue = deque()
        self.processing = False
        self.last_request_time = 0
        self.rate_limit = {
            'reset_after': 0,
            'remaining': 5,
            'limit': 5,
            'window': 2.0  # Discord's rate limit window (2 seconds)
        }
        self.retries = {}  # Track retry attempts per message
        self.max_retries = 5
        self.max_queue_size = 1000
        self.webhook_stats = {
            'total_sent': 0,
            'failed_attempts': 0,
            'rate_limits_hit': 0,
            'current_queue_size': 0
        }

    async def process_queue(self):
        """Background worker to process queued messages"""
        if self.processing:
            return

        self.processing = True
        try:
            while self.message_queue:
                current_time = time.time()
                self.webhook_stats['current_queue_size'] = len(self.message_queue)

                # Check rate limits
                if self.rate_limit['remaining'] <= 0:
                    wait_time = max(0, self.rate_limit['reset_after'] - current_time)
                    if wait_time > 0:
                        logger.info(
                            "Rate limit reached, waiting",
                            extra={'extra_fields': {
                                'wait_time': wait_time,
                                'queue_size': len(self.message_queue),
                                'stats': self.webhook_stats
                            }}
                        )
                        await asyncio.sleep(wait_time)
                        continue

                # Process next message
                payload = self.message_queue.popleft()
                success = await self._send_webhook(payload)

                if not success:
                    retry_count = self.retries.get(id(payload), 0) + 1
                    if retry_count <= self.max_retries:
                        logger.warning(
                            "Retrying webhook",
                            extra={'extra_fields': {
                                'attempt': retry_count,
                                'max_retries': self.max_retries,
                                'queue_size': len(self.message_queue)
                            }}
                        )
                        self.retries[id(payload)] = retry_count
                        self.message_queue.append(payload)
                        self.webhook_stats['failed_attempts'] += 1
                    else:
                        logger.error(
                            "Failed to send webhook after maximum retries",
                            extra={'extra_fields': {
                                'stats': self.webhook_stats
                            }}
                        )

                # Adaptive delay between requests
                elapsed = time.time() - self.last_request_time
                if elapsed < (self.rate_limit['window'] / self.rate_limit['limit']):
                    await asyncio.sleep(0.1)  # Small delay to prevent bursts

        except Exception as e:
            log_webhook_error(self.webhook_url, e, {
                'queue_size': len(self.message_queue),
                'stats': self.webhook_stats
            })
        finally:
            self.processing = False

    async def _send_webhook(self, payload: Dict) -> bool:
        """Send a single webhook with rate limit handling"""
        try:
            response = self.session.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5
            )

            # Update rate limit info from headers
            self.rate_limit['remaining'] = int(response.headers.get('X-RateLimit-Remaining', 5))
            reset_after = float(response.headers.get('X-RateLimit-Reset-After', 0))
            self.rate_limit['reset_after'] = time.time() + reset_after
            self.last_request_time = time.time()

            if response.status_code == 429:
                retry_after = float(response.headers.get('Retry-After', 5))
                self.rate_limit['reset_after'] = time.time() + retry_after
                self.webhook_stats['rate_limits_hit'] += 1
                return False

            response.raise_for_status()
            self.webhook_stats['total_sent'] += 1
            return True

        except Exception as e:
            log_webhook_error(
                self.webhook_url,
                e,
                {'stats': self.webhook_stats}
            )
            return False

    def send_product_notification(self, product: Dict) -> bool:
        """Queue a product notification for sending"""
        try:
            if len(self.message_queue) >= self.max_queue_size:
                logger.warning(
                    "Webhook queue full, dropping oldest message",
                    extra={'extra_fields': {'queue_size': len(self.message_queue)}}
                )
                self.message_queue.popleft()  # Remove oldest message

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
                    size_text = f"• {size} | QT [{qty}]"
                    if product["variants"].get(size):
                        cart_url = f"{product['url']}?variant={product['variants'][size]}"
                        size_text = f"[{size_text}]({cart_url})"
                    sizes_text.append(size_text)

                embed["fields"].append({
                    "name": "Sizes / Stock",
                    "value": "\n".join(sizes_text),
                    "inline": False
                })

            payload = {
                "username": "SoleAddictionsLLC Monitor",
                "avatar_url": "https://cdn.shopify.com/shopifycloud/brochure/assets/brand-assets/shopify-logo-primary-logo-456baa801ee66a0a435671082365958316831c9960c480451dd0330bcdae304f.svg",
                "embeds": [embed]
            }

            self.message_queue.append(payload)
            logger.debug(
                "Added notification to queue",
                extra={'extra_fields': {
                    'queue_size': len(self.message_queue),
                    'product_title': product['title']
                }}
            )

            # Start queue processing if not already running
            asyncio.create_task(self.process_queue())
            return True

        except Exception as e:
            log_webhook_error(
                self.webhook_url,
                e,
                {
                    'product_title': product.get('title', 'Unknown'),
                    'queue_size': len(self.message_queue)
                }
            )
            return False