import json
import requests
import time
from datetime import datetime
from config import DISCORD_WEBHOOK_URL, INFO_COLOR

class DiscordWebhook:
    def __init__(self, webhook_url=None):
        self.webhook_url = webhook_url or DISCORD_WEBHOOK_URL
        if not self.webhook_url:
            raise ValueError("Discord webhook URL is required")
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
        embed = {
            "title": product_data["title"],
            "url": product_data["url"],
            "color": INFO_COLOR,
            "timestamp": datetime.utcnow().isoformat(),
            "thumbnail": {"url": product_data.get("image_url", "")},
            "fields": [
                {
                    "name": "Price",
                    "value": f"{product_data['price']} USD",
                    "inline": True
                },
                {
                    "name": "Stock",
                    "value": str(product_data.get("stock", "N/A")),
                    "inline": True
                },
                {
                    "name": "Full Size Run",
                    "value": product_data.get("full_size_run", "N/A"),
                    "inline": True
                }
            ]
        }

        # Add sizes if available
        if product_data.get("sizes"):
            sizes_text = []
            for size, qty in product_data["sizes"].items():
                base_url = product_data["url"]
                variant_id = product_data["variants"].get(size, "")
                size_text = f"• {size} | QT [{qty}]"  # Added bullet point
                if variant_id:
                    cart_url = f"{base_url}?variant={variant_id}"
                    size_text = f"[{size_text}]({cart_url})"
                sizes_text.append(size_text)

            embed["fields"].append({
                "name": "ATC / QT",
                "value": "\n".join(sizes_text),
                "inline": False
            })

        # Add quick links with proper formatting
        links_text = [
            f"[Quicktask]({product_data['url']}/cart.js) | " +
            f"[StockX](https://stockx.com/search?s={product_data['title'].replace(' ', '%20')}) | " +
            "[Setup](javascript:void(0))",
            "",  # Empty line for spacing
            f"[Zephyr QT]({product_data['url']}) | SRC: {product_data.get('stock', 0)}",
            "",  # Empty line for spacing
            "[Link Change](javascript:void(0)) | " +
            f"[Copy Link]({product_data['url']}) | " +
            "[Setup ShopPay](javascript:void(0))"
        ]

        embed["fields"].append({
            "name": "Links",
            "value": "\n".join(links_text),
            "inline": False
        })

        payload = {
            "username": "Shopify Monitor",
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