import asyncio
import sys
import os
from typing import Dict, List, Set
import time
from shopify_monitor import ShopifyMonitor
from discord_webhook import DiscordWebhook
from models import db, User, Store, Keyword, MonitorConfig

# Dictionary to store seen products per user
user_seen_products: Dict[int, Set[str]] = {}

async def monitor_store(store_url: str, keywords: List[str], monitor: ShopifyMonitor, 
                       webhook: DiscordWebhook, seen_products: Set[str], user_id: int):
    """Monitors a single store for products"""
    try:
        products = monitor.fetch_products(store_url, keywords)
        new_products = 0

        for product in products:
            product_identifier = f"{store_url}-{product['title']}-{product['price']}-{user_id}"

            if product_identifier not in seen_products:
                print(f"[User {user_id}] New product found on {store_url}: {product['title']}")
                webhook.send_product_notification(product)
                seen_products.add(product_identifier)
                new_products += 1

        return new_products
    except Exception as e:
        print(f"[User {user_id}] Error monitoring {store_url}: {e}")
        return 0

async def main():
    try:
        # Extract user ID from command line arguments
        user_id = None
        for arg in sys.argv[1:]:
            if arg.startswith("MONITOR_USER_ID="):
                user_id = int(arg.split("=")[1])
                break

        if not user_id:
            print("Error: MONITOR_USER_ID not provided")
            sys.exit(1)

        print(f"Starting monitor for user ID: {user_id}")

        from app import create_app
        app = create_app()

        with app.app_context():
            # Get the specific user
            user = User.query.get(user_id)
            if not user or not user.enabled:
                print(f"Error: User {user_id} not found or disabled")
                sys.exit(1)

            # Initialize monitor for this user
            config = MonitorConfig.query.filter_by(user_id=user_id).first()
            if not config:
                print(f"Error: No configuration found for user {user_id}")
                sys.exit(1)

            monitor = ShopifyMonitor(rate_limit=config.rate_limit)

            # Initialize user's seen products
            if user_id not in user_seen_products:
                user_seen_products[user_id] = set()

            # Initialize webhook with user's configuration
            webhook = DiscordWebhook(webhook_url=user.discord_webhook_url)

            print(f"Starting monitor for user {user.username} (ID: {user_id})")
            print(f"- Discord Webhook: {'Configured' if user.discord_webhook_url else 'Not configured'}")
            print(f"- Rate limit: {config.rate_limit} req/s")
            print(f"- Monitor delay: {config.monitor_delay}s")

            while True:
                # Get user's active stores and keywords
                active_stores = Store.query.filter_by(user_id=user_id, enabled=True).all()
                active_keywords = Keyword.query.filter_by(user_id=user_id, enabled=True).all()

                print(f"\nProcessing stores for user {user.username}:")
                print(f"- Active stores: {len(active_stores)}")
                print(f"- Active keywords: {', '.join(kw.word for kw in active_keywords)}")

                tasks = []
                for store in active_stores:
                    task = asyncio.create_task(
                        monitor_store(
                            store.url,
                            [kw.word for kw in active_keywords],
                            monitor,
                            webhook,
                            user_seen_products[user_id],
                            user_id
                        )
                    )
                    tasks.append(task)

                results = await asyncio.gather(*tasks, return_exceptions=True)
                total_new_products = sum(r for r in results if isinstance(r, int))

                print(f"- New products found: {total_new_products}")
                if monitor.failed_stores:
                    print(f"- Failed stores for user {user_id}:", ", ".join(monitor.failed_stores))

                await asyncio.sleep(config.monitor_delay)

    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error in monitor: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())