import asyncio
import sys
import os
from typing import List, Dict, Set
import time
from shopify_monitor import ShopifyMonitor
from discord_webhook import DiscordWebhook
from config import MONITOR_DELAY
from flask import Flask
from models import db, User, Store, Keyword, MonitorConfig

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# Make seen_products user-specific
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
                print(f"New product found on {store_url}: {product['title']}")
                webhook.send_product_notification(product)
                seen_products.add(product_identifier)
                new_products += 1

        return new_products
    except Exception as e:
        print(f"Error monitoring {store_url}: {e}")
        return 0

async def main():
    try:
        with app.app_context():
            # Get all active users
            active_users = User.query.filter_by(enabled=True).all()

            # Initialize monitors per user
            monitors = {user.id: ShopifyMonitor(rate_limit=1.0) for user in active_users}

            # Initialize seen products per user
            for user in active_users:
                if user.id not in user_seen_products:
                    user_seen_products[user.id] = set()

            print(f"Starting monitor for {len(active_users)} active users")

            while True:
                for user in active_users:
                    # Get user-specific configuration
                    config = MonitorConfig.query.filter_by(user_id=user.id).first()
                    if not config:
                        continue

                    # Initialize user's webhook
                    webhook = DiscordWebhook(webhook_url=user.discord_webhook_url)

                    # Get user's active stores and keywords
                    active_stores = [store.url for store in Store.query.filter_by(user_id=user.id, enabled=True).all()]
                    active_keywords = [kw.word for kw in Keyword.query.filter_by(user_id=user.id, enabled=True).all()]

                    print(f"\nProcessing user {user.username}:")
                    print(f"- Active stores: {len(active_stores)}")
                    print(f"- Active keywords: {', '.join(active_keywords)}")

                    tasks = []
                    for store_url in active_stores:
                        task = asyncio.create_task(
                            monitor_store(
                                store_url, 
                                active_keywords, 
                                monitors[user.id], 
                                webhook, 
                                user_seen_products[user.id],
                                user.id
                            )
                        )
                        tasks.append(task)

                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    total_new_products = sum(r for r in results if isinstance(r, int))

                    print(f"- New products found: {total_new_products}")
                    if monitors[user.id].failed_stores:
                        print("- Failed stores:", ", ".join(monitors[user.id].failed_stores))

                # Use the shortest monitor delay among all users
                min_delay = min(
                    (c.monitor_delay for c in MonitorConfig.query.all()),
                    default=30
                )
                await asyncio.sleep(min_delay)

    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())