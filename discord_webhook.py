import json
import requests
import time
from datetime import datetime
from config import INFO_COLOR

class DiscordWebhook:
    def __init__(self, webhook_url=None):
        self.webhook_url = webhook_url
        self.last_webhook_time = 0
        self.webhook_rate_limit = 1  # Max 1 request per second

    def _rate_limit(self):
        """Implements rate limiting for Discord webhook requests"""
        current_time = time.time()
        time_passed = current_time - self.last_webhook_time
        if time_passed < self.webhook_rate_limit:
            time.sleep(self.webhook_rate_limit - time_passed)
        self.last_webhook_time = time.time()

    def send_product_notification(self, product_data):
        """
        Sends a formatted product notification to Discord
        """
        if not self.webhook_url:
            print("Warning: Discord webhook URL not configured, skipping notification")
            return False

        embed = {
            "title": product_data["title"],
            "url": product_data["url"],
            "color": INFO_COLOR,
            "timestamp": datetime.utcnow().isoformat(),
            "thumbnail": {"url": product_data.get("image_url", "")},
            "fields": [
                {
                    "name": "Price",
                    "value": f"${product_data['price']}" if isinstance(product_data['price'], (int, float)) else product_data['price'],
                    "inline": True
                }
            ]
        }

        # Add retailer field if present (for retail scraper results)
        if "retailer" in product_data:
            embed["fields"].append({
                "name": "Retailer",
                "value": product_data["retailer"],
                "inline": True
            })

        # Add sizes if available (for Shopify products)
        if product_data.get("sizes"):
            sizes_text = []
            for size, qty in product_data["sizes"].items():
                base_url = product_data["url"]
                variant_id = product_data["variants"].get(size, "")
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
                f"[Quick Purchase]({product_data['url']}/cart.js) | " +
                f"[Market Price](https://stockx.com/search?s={product_data['title'].replace(' ', '%20')})",
                "",  # Empty line for spacing
                f"[Product Link]({product_data['url']}) | Stock: {product_data.get('stock', 0)}",
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
            self._rate_limit()  # Apply rate limiting before sending
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error sending Discord webhook: {e}")
            if e.response and e.response.status_code == 429:  # Rate limit hit
                retry_after = int(e.response.headers.get('Retry-After', 5))
                print(f"Rate limited, waiting {retry_after} seconds")
                time.sleep(retry_after)
                return self.send_product_notification(product_data)  # Retry once
            return False