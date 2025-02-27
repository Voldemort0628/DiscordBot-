import json
import requests
from datetime import datetime
from config import DISCORD_WEBHOOK_URL

class DiscordWebhook:
    def __init__(self, webhook_url=None):
        self.webhook_url = webhook_url or DISCORD_WEBHOOK_URL
        if not self.webhook_url:
            raise ValueError("Discord webhook URL is required")

    def send_product_notification(self, product_data):
        """
        Sends a formatted product notification to Discord
        """
        embed = {
            "title": product_data["title"],
            "url": product_data["url"],
            "color": 0x2ecc71,
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
            sizes_text = "\n".join([f"{size} | QT [{qty}]" for size, qty in product_data["sizes"].items()])
            embed["fields"].append({
                "name": "ATC / QT",
                "value": sizes_text,
                "inline": False
            })

        payload = {
            "username": "Shopify Monitor",
            "avatar_url": "https://cdn.shopify.com/shopifycloud/brochure/assets/brand-assets/shopify-logo-primary-logo-456baa801ee66a0a435671082365958316831c9960c480451dd0330bcdae304f.svg",
            "embeds": [embed]
        }

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error sending Discord webhook: {e}")
            return False
