import asyncio
import sys
import os
from typing import Dict, List, Set
import time
import logging
from datetime import datetime, timedelta
from shopify_monitor import ShopifyMonitor
from discord_webhook import RateLimitedDiscordWebhook
from models import db, User, Store, Keyword, MonitorConfig
from sqlalchemy.exc import OperationalError, SQLAlchemyError

# Configure logging with rotation
log_filename = f'monitor_{datetime.now().strftime("%Y%m%d")}.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_filename)
    ]
)

# Add a separate logger for heartbeat
heartbeat_logger = logging.getLogger('heartbeat')
heartbeat_handler = logging.FileHandler('heartbeat.log')
heartbeat_logger.addHandler(heartbeat_handler)
heartbeat_logger.setLevel(logging.INFO)

class TTLCache:
    def __init__(self, max_size=10000, ttl_hours=12):  # Reduced TTL from 24 to 12 hours
        self.cache = {}
        self.timestamps = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_hours * 3600
        self.last_cleanup = time.time()

    def add(self, key: str):
        current_time = time.time()
        if current_time - self.last_cleanup > 1800:  # Cleanup every 30 minutes instead of hourly
            self._cleanup()
            self.last_cleanup = current_time

        if len(self.cache) >= self.max_size:
            self._cleanup()
        self.cache[key] = True
        self.timestamps[key] = current_time

    def exists(self, key: str) -> bool:
        if key not in self.cache:
            return False
        if time.time() - self.timestamps[key] > self.ttl_seconds:
            del self.cache[key]
            del self.timestamps[key]
            return False
        return True

    def _cleanup(self):
        current_time = time.time()
        expired_keys = [k for k, t in self.timestamps.items() 
                       if current_time - t > self.ttl_seconds]
        for k in expired_keys:
            del self.cache[k]
            del self.timestamps[k]

        if len(self.cache) >= self.max_size:
            # Keep the most recent 75% of entries instead of 50%
            sorted_items = sorted(self.timestamps.items(), key=lambda x: x[1])
            to_remove = sorted_items[:len(sorted_items)//4]
            for k, _ in to_remove:
                del self.cache[k]
                del self.timestamps[k]

user_seen_products: Dict[int, TTLCache] = {}

async def send_heartbeat(user_id: int):
    """Send periodic heartbeat to verify monitor is running"""
    while True:
        try:
            heartbeat_logger.info(f"Monitor heartbeat - User {user_id} - Active and running")
            await asyncio.sleep(300)  # Heartbeat every 5 minutes
        except Exception as e:
            logging.error(f"Error in heartbeat: {e}")
            await asyncio.sleep(60)  # Shorter retry on error

async def monitor_store(store_url: str, keywords: List[str], monitor: ShopifyMonitor, 
                       webhook: RateLimitedDiscordWebhook, seen_products: TTLCache, user_id: int):
    """Monitors a single store for products with enhanced error handling and detection"""
    retry_count = 0
    max_retries = 3

    while retry_count < max_retries:
        try:
            products = monitor.fetch_products(store_url, keywords)
            new_products = 0

            if not products:
                logging.warning(f"[User {user_id}] No products found for {store_url}, this might indicate an access issue")
                return 0

            for product in products:
                # Enhanced product identifier including more attributes for better restock detection
                product_identifier = (
                    f"{store_url}-{product['title']}-{product['price']}-"
                    f"{product.get('variant_id', '')}-{product.get('stock', 0)}-{user_id}"
                )

                # Check if this is a new product or a restock
                if not seen_products.exists(product_identifier):
                    logging.info(f"[User {user_id}] New product/restock found on {store_url}: {product['title']}")
                    try:
                        webhook_success = await webhook.send_product_notification(product)
                        if webhook_success:
                            seen_products.add(product_identifier)
                            new_products += 1
                            logging.info(f"Successfully notified about product: {product['title']}")
                        else:
                            logging.warning(f"Failed to send webhook notification for {product['title']}, will retry on next cycle")
                    except Exception as webhook_error:
                        logging.error(f"Webhook error for {product['title']}: {webhook_error}")
                        continue

            return new_products

        except Exception as e:
            retry_count += 1
            logging.error(f"[User {user_id}] Error monitoring {store_url} (attempt {retry_count}/{max_retries}): {e}")
            if retry_count < max_retries:
                await asyncio.sleep(1 * retry_count)  # Further reduced backoff time for faster recovery
            else:
                logging.error(f"[User {user_id}] Failed to monitor {store_url} after {max_retries} attempts")
                return 0

async def main():
    start_time = time.time()
    last_restart = start_time
    restart_threshold = 12 * 3600  # Restart every 12 hours for memory management

    while True:
        try:
            # Extract user ID from command line arguments
            user_id = None
            for arg in sys.argv[1:]:
                if arg.startswith("MONITOR_USER_ID="):
                    user_id = int(arg.split("=")[1])
                    break

            if not user_id:
                logging.error("Error: MONITOR_USER_ID not provided")
                sys.exit(1)

            logging.info(f"Starting monitor for user ID: {user_id}")
            logging.info(f"Monitor uptime: {time.time() - start_time:.2f} seconds")

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(send_heartbeat(user_id))

            from app import create_app
            app = create_app()

            # Database connection management with retries
            max_db_retries = 5
            db_retry_count = 0

            while True:
                try:
                    with app.app_context():
                        if user_id not in user_seen_products:
                            user_seen_products[user_id] = TTLCache()

                        # Get the specific user with retry logic
                        user = None
                        for _ in range(3):
                            try:
                                # Use Session.get() instead of Query.get()
                                user = db.session.get(User, user_id)
                                if user and user.enabled:
                                    break
                                await asyncio.sleep(1)
                            except SQLAlchemyError as e:
                                logging.error(f"Database error fetching user: {e}")
                                await asyncio.sleep(2)

                        if not user or not user.enabled:
                            logging.error(f"User {user_id} not found or disabled")
                            sys.exit(1)

                        config = MonitorConfig.query.filter_by(user_id=user_id).first()
                        if not config:
                            logging.error(f"No configuration found for user {user_id}")
                            sys.exit(1)

                        rate_limit_value = getattr(config, 'rate_limit', 0.5)
                        monitor = ShopifyMonitor(rate_limit=rate_limit_value)
                        webhook = RateLimitedDiscordWebhook(webhook_url=user.discord_webhook_url)

                        logging.info(f"Monitoring configuration for user {user.username} (ID: {user_id})")
                        logging.info(f"- Discord Webhook: {'Configured' if user.discord_webhook_url else 'Not configured'}")
                        logging.info(f"- Rate limit: {config.rate_limit} req/s")
                        logging.info(f"- Monitor delay: {config.monitor_delay}s")

                        monitor_cycle = 0
                        while True:
                            # Check if we need to restart for memory management
                            if time.time() - last_restart > restart_threshold:
                                logging.info("Scheduled restart for memory management")
                                sys.exit(0)  # Clean exit for restart

                            cycle_start_time = time.time()
                            monitor_cycle += 1
                            logging.info(f"\n---- Monitor Cycle #{monitor_cycle} ----")

                            try:
                                # Refresh user and config from database
                                db.session.remove()
                                user = db.session.get(User, user_id)
                                config = MonitorConfig.query.filter_by(user_id=user_id).first()

                                if not user or not user.enabled:
                                    logging.warning(f"User {user_id} was disabled, exiting...")
                                    sys.exit(0)

                                stores = Store.query.filter_by(user_id=user_id, enabled=True).all()
                                keywords = Keyword.query.filter_by(user_id=user_id, enabled=True).all()

                                if not stores or not keywords:
                                    logging.info("No active stores or keywords. Waiting...")
                                    await asyncio.sleep(config.monitor_delay)
                                    continue

                                # Process stores in parallel batches with improved efficiency
                                batch_size = min(20, len(stores))  # Increased from 10 to 20
                                all_results = []

                                # Group stores by retailer for better rate limiting
                                stores_by_retailer = {}
                                for store in stores:
                                    retailer = store.url.split('/')[2]  # Extract domain
                                    if retailer not in stores_by_retailer:
                                        stores_by_retailer[retailer] = []
                                    stores_by_retailer[retailer].append(store)

                                # Process each retailer group separately
                                for retailer, retailer_stores in stores_by_retailer.items():
                                    logging.info(f"Processing {len(retailer_stores)} stores for retailer: {retailer}")

                                    for i in range(0, len(retailer_stores), batch_size):
                                        batch = retailer_stores[i:i+batch_size]
                                        tasks = [
                                            monitor_store(
                                                store.url,
                                                [kw.word for kw in keywords],
                                                monitor,
                                                webhook,
                                                user_seen_products[user_id],
                                                user_id
                                            )
                                            for store in batch
                                        ]

                                        # Process batch with individual error handling
                                        try:
                                            results = await asyncio.gather(*tasks, return_exceptions=True)
                                            successful_results = []

                                            for idx, result in enumerate(results):
                                                if isinstance(result, Exception):
                                                    store_url = batch[idx].url
                                                    logging.error(f"Error processing store {store_url}: {str(result)}")
                                                else:
                                                    successful_results.append(result)

                                            all_results.extend(successful_results)

                                            # Add smaller delay between batches for the same retailer
                                            if i + batch_size < len(retailer_stores):
                                                await asyncio.sleep(0.25)  # Reduced delay between batches

                                        except Exception as batch_error:
                                            logging.error(f"Batch processing error for retailer {retailer}: {batch_error}")
                                            continue

                                total_new_products = sum(r for r in all_results if isinstance(r, int))
                                logging.info(f"New products found: {total_new_products}")

                                # Adaptive delay based on results and retailer
                                cycle_duration = time.time() - cycle_start_time

                                # More aggressive delay reduction when products are found
                                delay_multiplier = 0.25 if total_new_products > 0 else 1.0
                                # Cap minimum delay at 0.05 seconds
                                sleep_time = max(0.05, config.monitor_delay * delay_multiplier - cycle_duration)
                                logging.info(f"Cycle completed in {cycle_duration:.2f}s, waiting {sleep_time:.2f}s")
                                await asyncio.sleep(sleep_time)

                            except OperationalError as e:
                                logging.error(f"Database error: {e}")
                                await asyncio.sleep(5)
                                break  # Reconnect to DB
                            except Exception as e:
                                logging.error(f"Cycle error: {e}")
                                await asyncio.sleep(2)

                except OperationalError as e:
                    db_retry_count += 1
                    if db_retry_count >= max_db_retries:
                        logging.critical("Maximum database retry attempts reached")
                        sys.exit(1)
                    logging.error(f"Database connection error (attempt {db_retry_count}/{max_db_retries}): {e}")
                    await asyncio.sleep(5 * db_retry_count)

        except KeyboardInterrupt:
            logging.info("Monitoring stopped by user")
            sys.exit(0)
        except Exception as e:
            logging.error(f"Fatal error: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())