import asyncio
import sys
from typing import List
import time
from shopify_monitor import ShopifyMonitor
from discord_webhook import DiscordWebhook
from config import MONITOR_DELAY

def get_user_input() -> tuple:
    """Gets store URL and keywords from user"""
    print("Welcome to Shopify Product Monitor")
    store_url = input("Enter Shopify store URL (e.g., https://store.com): ").strip()
    if not store_url.startswith(("http://", "https://")):
        store_url = "https://" + store_url
    
    keywords = input("Enter keywords to monitor (comma-separated): ").strip()
    keywords = [k.strip() for k in keywords.split(",")]
    
    return store_url, keywords

def main():
    try:
        store_url, keywords = get_user_input()
        monitor = ShopifyMonitor()
        webhook = DiscordWebhook()
        
        print(f"\nMonitoring {store_url} for products matching: {', '.join(keywords)}")
        print("Press Ctrl+C to stop monitoring\n")

        # Keep track of products we've already seen
        seen_products = set()

        while True:
            try:
                products = monitor.fetch_products(store_url, keywords)
                
                for product in products:
                    product_identifier = f"{product['title']}-{product['price']}"
                    
                    if product_identifier not in seen_products:
                        print(f"New product found: {product['title']}")
                        webhook.send_product_notification(product)
                        seen_products.add(product_identifier)
                
                time.sleep(MONITOR_DELAY)

            except Exception as e:
                print(f"Error during monitoring: {e}")
                time.sleep(MONITOR_DELAY)

    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
