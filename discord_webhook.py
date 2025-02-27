import json
import requests
import time
from datetime import datetime
from config import INFO_COLOR
import random

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
            print(f"Error sending Discord webhook: {e}")
            return False

class RateLimitedDiscordWebhook:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.last_request_time = 0
        self.rate_limit_window = 1.25  # seconds between requests (Discord limits to ~50 per minute)
        self.max_retries = 5
        self.session = requests.Session()  # Keep session for connection pooling
        self.rate_limit_remaining = 5  # Track Discord's rate limit headers
        self.rate_limit_reset = 0

    def send_product_notification(self, product):
        """Send product notification with adaptive rate limiting and retry logic"""
        for attempt in range(self.max_retries):
            # Apply adaptive rate limiting based on Discord's response headers
            current_time = time.time()
            
            # Check if we need to wait based on Discord's rate limit headers
            if self.rate_limit_remaining <= 1 and current_time < self.rate_limit_reset:
                wait_time = self.rate_limit_reset - current_time + 0.1
                print(f"Waiting for Discord rate limit to reset. Sleeping {wait_time:.2f}s")
                time.sleep(wait_time)
            # Otherwise, use our internal rate limiting
            elif current_time - self.last_request_time < self.rate_limit_window:
                # Add slight jitter to avoid bursts hitting rate limits
                sleep_time = self.rate_limit_window - (current_time - self.last_request_time)
                # Small amount of jitter to avoid predictable patterns
                sleep_time += random.uniform(0.05, 0.2)  
                time.sleep(sleep_time)

            try:
                # Create webhook content - only include essential fields for speed
                embed = {
                    "title": product["title"],
                    "url": product["url"],
                    "color": INFO_COLOR,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                
                # Only add thumbnail if there's an image URL to reduce payload size
                if product.get("image_url"):
                    embed["thumbnail"] = {"url": product["image_url"]}
                
                # Add essential fields
                embed["fields"] = [
                    {
                        "name": "Price",
                        "value": f"${product['price']}" if isinstance(product['price'], (int, float)) else product['price'],
                        "inline": True
                    }
                ]

                # Add retailer field if present (for retail scraper results)
                if "retailer" in product:
                    embed["fields"].append({
                        "name": "Retailer",
                        "value": product["retailer"],
                        "inline": True
                    })

                # Add sizes if available (for Shopify products)
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

                    # Add quick links with proper formatting for SoleAddictionsLLC
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

                # Send webhook with connection pooling and timeout
                response = self.session.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=3  # Add timeout to prevent hanging
                )
                response.raise_for_status()

                # Update rate limit tracking from Discord's headers
                self.last_request_time = time.time()
                if 'X-RateLimit-Remaining' in response.headers:
                    self.rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', 5))
                if 'X-RateLimit-Reset-After' in response.headers:
                    reset_after = float(response.headers.get('X-RateLimit-Reset-After', 0))
                    self.rate_limit_reset = time.time() + reset_after

                # Check for success
                if response.status_code == 200 or response.status_code == 204:
                    return True

                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = float(response.headers.get('Retry-After', 5))
                    print(f"Rate limited by Discord. Retrying after {retry_after}s")
                    # Use the exact retry time Discord tells us to use
                    time.sleep(retry_after)
                    continue

            except requests.exceptions.RequestException as e:
                print(f"Error sending Discord webhook: {e}")
                # Use exponential backoff for network errors
                backoff = (2 ** attempt) * 0.5
                time.sleep(min(backoff, 5))  # Cap at 5 seconds

        print("Failed to send webhook after multiple retries")
        return False

#Example usage (assuming 'user' object exists with discord_webhook_url attribute)

#webhook = RateLimitedDiscordWebhook(webhook_url=user.discord_webhook_url)
#webhook.send_product_notification(product_data)