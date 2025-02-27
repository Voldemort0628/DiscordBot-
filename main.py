import asyncio
import sys
import os
from typing import Dict, List, Set
import time
from shopify_monitor import ShopifyMonitor
from discord_webhook import DiscordWebhook
from models import db, User, Store, Keyword, MonitorConfig

# Dictionary to store seen products per user with TTL
user_seen_products: Dict[int, Dict[str, float]] = {}
PRODUCT_TTL = 3600  # 1 hour TTL for seen products

async def monitor_store(store_url: str, keywords: List[str], monitor: ShopifyMonitor, 
                       webhook: DiscordWebhook, seen_products: Dict[str, float], user_id: int):
    """Monitors a single store for products with improved error handling"""
    try:
        products = monitor.fetch_products(store_url, keywords)
        new_products = 0
        current_time = time.time()

        for product in products:
            product_identifier = f"{store_url}-{product['title']}-{product['price']}-{user_id}"

            # Check if product was seen within TTL window
            if product_identifier not in seen_products or (current_time - seen_products[product_identifier]) > PRODUCT_TTL:
                print(f"[User {user_id}] New product found on {store_url}: {product['title']}")
                webhook.send_product_notification(product)
                seen_products[product_identifier] = current_time
                new_products += 1

        return new_products
    except Exception as e:
        print(f"[User {user_id}] Error monitoring {store_url}: {e}")
        return 0

async def main():
    start_time = time.time()
    retry_count = 0
    max_retries = 3

    while True:
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
            print(f"Monitor uptime: {time.time() - start_time:.2f} seconds")

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

                # Make sure rate_limit is properly passed to ShopifyMonitor
                rate_limit_value = config.rate_limit if hasattr(config, 'rate_limit') else 0.5
                monitor = ShopifyMonitor(rate_limit=rate_limit_value)

                # Initialize user's seen products with TTL if not exists
                if user_id not in user_seen_products:
                    user_seen_products[user_id] = {}

                # Initialize webhook with user's configuration
                from discord_webhook import RateLimitedDiscordWebhook
                webhook = RateLimitedDiscordWebhook(webhook_url=user.discord_webhook_url)

                print(f"Starting monitor for user {user.username} (ID: {user_id})")
                print(f"- Discord Webhook: {'Configured' if user.discord_webhook_url else 'Not configured'}")
                print(f"- Rate limit: {config.rate_limit} req/s")
                print(f"- Monitor delay: {config.monitor_delay}s")

                monitor_cycle = 0
                while True:
                    cycle_start_time = time.time()
                    monitor_cycle += 1
                    print(f"\n---- Monitor Cycle #{monitor_cycle} ----")

                    try:
                        # Clean expired products from cache
                        current_time = time.time()
                        user_seen_products[user_id] = {
                            k: v for k, v in user_seen_products[user_id].items()
                            if current_time - v <= PRODUCT_TTL
                        }

                        # Use a new session for each cycle
                        db.session.close()
                        db.session.begin()

                        # Refresh user and config
                        user = User.query.get(user_id)
                        config = MonitorConfig.query.filter_by(user_id=user_id).first()

                        if not user or not user.enabled:
                            print(f"User {user_id} was disabled, exiting...")
                            sys.exit(0)

                        # Get user's active stores and keywords
                        active_stores = Store.query.filter_by(user_id=user_id, enabled=True).all()
                        active_keywords = Keyword.query.filter_by(user_id=user_id, enabled=True).all()

                        print(f"Processing stores for user {user.username}:")
                        print(f"- Active stores: {len(active_stores)}")
                        print(f"- Active keywords: {len(active_keywords)}")

                        if not active_stores or not active_keywords:
                            print("No active stores or keywords to monitor. Waiting before next check.")
                            db.session.commit()
                            await asyncio.sleep(config.monitor_delay)
                            continue

                        # Process stores in smaller batches with adaptive delay
                        batch_size = min(5, len(active_stores))  # Reduced from 10 to 5
                        all_results = []

                        for i in range(0, len(active_stores), batch_size):
                            batch_stores = active_stores[i:i+batch_size]

                            tasks = []
                            for store in batch_stores:
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

                            # Add delay between batches to prevent overloading
                            if i > 0:
                                await asyncio.sleep(1)

                            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                            all_results.extend(batch_results)

                        # Process results
                        error_count = sum(1 for r in all_results if isinstance(r, Exception))
                        total_new_products = sum(r for r in all_results if isinstance(r, int))

                        print(f"- New products found: {total_new_products}")
                        print(f"- Errors encountered: {error_count}")

                        if monitor.failed_stores:
                            failed_count = len(monitor.failed_stores)
                            print(f"- Failed stores: {failed_count} (showing first 3)")
                            for store in list(monitor.failed_stores)[:3]:
                                print(f"  - {store}")

                        # Reset retry counter on success
                        retry_count = 0

                        # Commit the transaction
                        db.session.commit()

                        # Adaptive delay based on results
                        cycle_duration = time.time() - cycle_start_time
                        base_delay = config.monitor_delay

                        # Adjust delay based on results
                        if total_new_products > 0:
                            # Reduce delay if we found products
                            actual_delay = max(1, base_delay * 0.5)
                        elif error_count > 0:
                            # Increase delay if we had errors
                            actual_delay = min(base_delay * 1.5, 60)
                        else:
                            actual_delay = base_delay

                        sleep_time = max(1, actual_delay - cycle_duration)
                        print(f"Cycle completed in {cycle_duration:.2f}s, waiting {sleep_time:.2f}s...")
                        await asyncio.sleep(sleep_time)

                    except Exception as e:
                        print(f"Error in monitor cycle: {e}")
                        db.session.rollback()
                        await asyncio.sleep(5)  # Brief pause before retry

        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")
            sys.exit(0)
        except Exception as e:
            retry_count += 1
            print(f"Fatal error in monitor: {e}")
            print(f"Retry {retry_count}/{max_retries}")

            try:
                db.session.rollback()
            except Exception as rollback_error:
                print(f"Error rolling back transaction: {rollback_error}")

            if retry_count >= max_retries:
                print("Maximum retries reached. Exiting monitor.")
                sys.exit(1)

            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())