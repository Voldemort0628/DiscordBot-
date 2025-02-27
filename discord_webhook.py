import json
import requests
import time
from datetime import datetime
from config import INFO_COLOR
import random

class RateLimitedDiscordWebhook:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.last_request_time = 0
        self.rate_limit_window = 2  # seconds between requests
        self.max_retries = 3

    def send_product_notification(self, product):
        """Send product notification with rate limiting and retry logic"""
        for attempt in range(self.max_retries):
            # Apply rate limiting
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.rate_limit_window:
                sleep_time = self.rate_limit_window - time_since_last + random.uniform(0.1, 0.5)
                time.sleep(sleep_time)

            try:
                # Create webhook content
                embed = {
                    "title": product["title"],
                    "url": product["url"],
                    "color": INFO_COLOR,
                    "timestamp": datetime.utcnow().isoformat(),
                    "thumbnail": {"url": product.get("image_url", "")},
                    "fields": [
                        {
                            "name": "Price",
                            "value": f"${product['price']}" if isinstance(product['price'], (int, float)) else product['price'],
                            "inline": True
                        }
                    ]
                }

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

                # Send webhook
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()

                # Update last request time
                self.last_request_time = time.time()

                # Check for success
                if response and response.status_code == 200:
                    return True

                # Handle rate limiting
                if response and response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 5)) + random.uniform(0.5, 1.5)
                    print(f"Rate limited by Discord. Retrying after {retry_after}s")
                    time.sleep(retry_after)
                    continue

            except requests.exceptions.RequestException as e:
                print(f"Error sending Discord webhook: {e}")
                time.sleep(1 * (attempt + 1))  # Progressive backoff

        print("Failed to send webhook after multiple retries")
        return False

#Example usage (assuming 'user' object exists with discord_webhook_url attribute)

#webhook = RateLimitedDiscordWebhook(webhook_url=user.discord_webhook_url)
#webhook.send_product_notification(product_data)