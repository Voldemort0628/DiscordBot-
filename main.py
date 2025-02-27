import asyncio
import sys
import os
from typing import Dict, List
import time
import traceback
from shopify_monitor import ShopifyMonitor
from discord_webhook import DiscordWebhook, RateLimitedDiscordWebhook
from models import db, User, Store, Keyword, MonitorConfig
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Dictionary to store seen products per user with TTL
user_seen_products: Dict[int, Dict[str, float]] = {}
PRODUCT_TTL = 3600  # 1 hour TTL for seen products

async def monitor_store(store_url: str, keywords: List[str], monitor: ShopifyMonitor, 
                       webhook: RateLimitedDiscordWebhook, seen_products: Dict[str, float], user_id: int):
    """Monitors a single store for products with improved error handling"""
    try:
        products = monitor.fetch_products(store_url, keywords)
        new_products = 0
        current_time = time.time()

        for product in products:
            try:
                product_identifier = f"{store_url}-{product['title']}-{product['price']}-{user_id}"

                # Check if product was seen within TTL window
                if product_identifier not in seen_products or (current_time - seen_products[product_identifier]) > PRODUCT_TTL:
                    logger.info(f"[User {user_id}] New product found on {store_url}: {product['title']}")

                    # Queue the webhook notification
                    webhook.send_product_notification(product)
                    seen_products[product_identifier] = current_time
                    new_products += 1

            except Exception as product_error:
                logger.error(f"Error processing product from {store_url}: {product_error}")
                continue

        return new_products
    except Exception as e:
        logger.error(f"[User {user_id}] Error monitoring {store_url}: {e}")
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
                logger.error("Error: MONITOR_USER_ID not provided")
                sys.exit(1)

            logger.info(f"Starting monitor for user ID: {user_id}")
            logger.info(f"Monitor uptime: {time.time() - start_time:.2f} seconds")

            from app import create_app
            app = create_app()

            with app.app_context():
                # Get the specific user
                user = User.query.get(user_id)
                if not user or not user.enabled:
                    logger.error(f"Error: User {user_id} not found or disabled")
                    sys.exit(1)

                # Initialize monitor for this user
                config = MonitorConfig.query.filter_by(user_id=user_id).first()
                if not config:
                    logger.error(f"Error: No configuration found for user {user_id}")
                    sys.exit(1)

                # Make sure rate_limit is properly passed to ShopifyMonitor
                rate_limit_value = config.rate_limit if hasattr(config, 'rate_limit') else 0.5
                monitor = ShopifyMonitor(rate_limit=rate_limit_value)

                # Initialize user's seen products with TTL if not exists
                if user_id not in user_seen_products:
                    user_seen_products[user_id] = {}

                # Initialize webhook with user's configuration
                webhook = RateLimitedDiscordWebhook(webhook_url=user.discord_webhook_url)

                logger.info(f"Starting monitor for user {user.username} (ID: {user_id})")
                logger.info(f"- Discord Webhook: {'Configured' if user.discord_webhook_url else 'Not configured'}")
                logger.info(f"- Rate limit: {config.rate_limit} req/s")
                logger.info(f"- Monitor delay: {config.monitor_delay}s")

                monitor_cycle = 0
                consecutive_errors = 0
                max_consecutive_errors = 5

                while True:
                    cycle_start_time = time.time()
                    monitor_cycle += 1
                    logger.info(f"\n---- Monitor Cycle #{monitor_cycle} ----")

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
                            logger.warning(f"User {user_id} was disabled, exiting...")
                            sys.exit(0)

                        # Get user's active stores and keywords
                        active_stores = Store.query.filter_by(user_id=user_id, enabled=True).all()
                        active_keywords = Keyword.query.filter_by(user_id=user_id, enabled=True).all()

                        logger.info(f"Processing stores for user {user.username}:")
                        logger.info(f"- Active stores: {len(active_stores)}")
                        logger.info(f"- Active keywords: {len(active_keywords)}")

                        if not active_stores or not active_keywords:
                            logger.info("No active stores or keywords to monitor. Waiting before next check.")
                            db.session.commit()
                            await asyncio.sleep(config.monitor_delay)
                            continue

                        # Process stores in smaller batches with adaptive delay
                        batch_size = min(3, len(active_stores))  # Small batch size to prevent rate limits
                        all_results = []

                        for i in range(0, len(active_stores), batch_size):
                            batch_stores = active_stores[i:i+batch_size]
                            batch_start_time = time.time()

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

                            try:
                                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                                all_results.extend(batch_results)

                                # Only add delay if we have more batches and the batch was fast
                                batch_duration = time.time() - batch_start_time
                                if i + batch_size < len(active_stores) and batch_duration < 2:
                                    delay = max(0, 2 - batch_duration)
                                    logger.debug(f"Adding {delay:.2f}s delay between batches")
                                    await asyncio.sleep(delay)

                            except Exception as batch_error:
                                logger.error(f"Error processing batch: {batch_error}")
                                continue

                        # Process results
                        error_count = sum(1 for r in all_results if isinstance(r, Exception))
                        total_new_products = sum(r for r in all_results if isinstance(r, int))

                        logger.info(f"- New products found: {total_new_products}")
                        logger.info(f"- Errors encountered: {error_count}")

                        if error_count > 0:
                            consecutive_errors += 1
                            if consecutive_errors >= max_consecutive_errors:
                                logger.error(f"Too many consecutive errors ({consecutive_errors}), restarting monitor...")
                                sys.exit(1)  # Exit with error to trigger restart
                        else:
                            consecutive_errors = 0  # Reset on successful cycle

                        if monitor.failed_stores:
                            failed_count = len(monitor.failed_stores)
                            logger.warning(f"- Failed stores: {failed_count} (showing first 3)")
                            for store in list(monitor.failed_stores)[:3]:
                                logger.warning(f"  - {store}")

                        # Reset retry counter on success
                        retry_count = 0

                        # Commit the transaction
                        db.session.commit()

                        # Adaptive delay based on results and performance
                        cycle_duration = time.time() - cycle_start_time
                        base_delay = config.monitor_delay

                        # Dynamic delay calculation based on results and errors
                        if total_new_products > 0:
                            actual_delay = max(5, base_delay * 0.5)  # Min 5 second delay when finding products
                        elif error_count > 0:
                            actual_delay = min(base_delay * 1.5, 60)  # Max 60 second delay on errors
                        else:
                            actual_delay = base_delay

                        # Ensure we don't sleep negative time
                        sleep_time = max(5, actual_delay - cycle_duration)
                        logger.info(f"Cycle completed in {cycle_duration:.2f}s, waiting {sleep_time:.2f}s...")
                        await asyncio.sleep(sleep_time)

                    except Exception as e:
                        logger.error(f"Error in monitor cycle: {e}")
                        logger.error(traceback.format_exc())
                        db.session.rollback()
                        await asyncio.sleep(5)  # Brief pause before retry

        except KeyboardInterrupt:
            logger.info("\nMonitoring stopped by user")
            sys.exit(0)
        except Exception as e:
            retry_count += 1
            logger.error(f"Fatal error in monitor: {e}")
            logger.error(traceback.format_exc())
            logger.info(f"Retry {retry_count}/{max_retries}")

            try:
                db.session.rollback()
            except Exception as rollback_error:
                logger.error(f"Error rolling back transaction: {rollback_error}")

            if retry_count >= max_retries:
                logger.error("Maximum retries reached. Exiting monitor.")
                sys.exit(1)

            await asyncio.sleep(30)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Fatal error in main loop: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)