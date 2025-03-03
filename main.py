import asyncio
import sys
import os
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path

# Early environment check logging
logging.info("=== Monitor Starting ===")
logging.info(f"Environment variables:")
logging.info(f"MONITOR_USER_ID: {os.environ.get('MONITOR_USER_ID')}")
logging.info(f"DISCORD_WEBHOOK_URL: {'Set' if os.environ.get('DISCORD_WEBHOOK_URL') else 'Not set'}")
logging.info(f"Command line args: {sys.argv}")
logging.info(f"Current working directory: {os.getcwd()}")
logging.info(f"Python path: {sys.path}")
logging.info("=====================")

if not os.environ.get('MONITOR_USER_ID'):
    logging.error("Missing required environment variables: MONITOR_USER_ID")
    logging.error("Current environment:")
    logging.error(f"MONITOR_USER_ID: Not set")
    logging.error(f"DISCORD_WEBHOOK_URL: {'Set' if os.environ.get('DISCORD_WEBHOOK_URL') else 'Not set'}")
    logging.error(f"Command line args: {sys.argv}")
    sys.exit(1)

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
    logging.info(f"Added current directory to Python path: {current_dir}")

try:
    logging.info("Attempting to import required modules...")
    from typing import Dict, List, Set
    import time
    from shopify_monitor import ShopifyMonitor
    from discord_webhook import RateLimitedDiscordWebhook
    from models import db, User, Store, Keyword, MonitorConfig
    from sqlalchemy.exc import OperationalError, SQLAlchemyError
    logging.info("All required modules imported successfully")
except ImportError as e:
    logging.error(f"Failed to import required modules: {e}")
    logging.error(f"Python path: {sys.path}")
    sys.exit(1)

# Configure logging with rotation
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

log_filename = f'monitor_{datetime.now().strftime("%Y%m%d")}.log'
log_path = log_dir / log_filename

# Configure root logger with both file and console output
root_handler = logging.handlers.RotatingFileHandler(
    log_path,
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
root_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logging.root.handlers = []
logging.root.addHandler(root_handler)
logging.root.addHandler(console_handler)
logging.root.setLevel(logging.INFO)

# Add a separate logger for heartbeat
heartbeat_logger = logging.getLogger('heartbeat')
heartbeat_handler = logging.FileHandler(log_dir / 'heartbeat.log')
heartbeat_formatter = logging.Formatter('%(asctime)s - %(message)s')
heartbeat_handler.setFormatter(heartbeat_formatter)
heartbeat_logger.addHandler(heartbeat_handler)
heartbeat_logger.setLevel(logging.INFO)

# Add a logger for DNS resolution
dns_logger = logging.getLogger('dns')
dns_handler = logging.FileHandler(log_dir / 'dns.log')
dns_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
dns_handler.setFormatter(dns_formatter)
dns_logger.addHandler(dns_handler)
dns_logger.setLevel(logging.DEBUG)

# Add a logger for product fetching
product_logger = logging.getLogger('product')
product_handler = logging.FileHandler(log_dir / 'product.log')
product_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
product_handler.setFormatter(product_formatter)
product_logger.addHandler(product_handler)
product_logger.setLevel(logging.DEBUG)


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
            to_remove = sorted_items[:len(sorted_items) // 4]
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
            products = await monitor.async_fetch_products(store_url, keywords)
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
    try:
        # Add more detailed startup logging near the start of the monitoring loop
        logging.info("=== Starting main monitor loop ===")
        start_time = time.time()
        last_restart = start_time
        restart_threshold = 12 * 3600  # Restart every 12 hours for memory management

        while True:
            try:
                # Extract user ID from environment variables
                user_id = None
                env_user_id = os.environ.get('MONITOR_USER_ID')
                if env_user_id:
                    try:
                        user_id = int(env_user_id)
                        logging.info(f"Got user ID from environment: {user_id}")
                    except ValueError:
                        logging.error(f"Invalid MONITOR_USER_ID in environment: {env_user_id}")
                        sys.exit(1)

                if not user_id:
                    logging.error("Error: MONITOR_USER_ID not provided in environment")
                    sys.exit(1)

                logging.info("Creating Flask application...")
                from app import create_app
                app = create_app()
                logging.info("Flask application created successfully")

                while True:
                    try:
                        with app.app_context():
                            logging.info("=== Entering app context ===")
                            logging.info(f"Attempting database operations for user {user_id}")

                            if user_id not in user_seen_products:
                                user_seen_products[user_id] = TTLCache()
                                logging.info(f"Created new TTLCache for user {user_id}")

                            # Get the specific user with retry logic
                            user = None
                            for attempt in range(3):
                                try:
                                    logging.info(f"Attempting to fetch user (attempt {attempt + 1}/3)")
                                    user = db.session.get(User, user_id)
                                    if user and user.enabled:
                                        logging.info(f"Found enabled user: {user.username} (ID: {user_id})")
                                        break
                                    elif user:
                                        logging.warning(f"User found but disabled: {user.username} (ID: {user_id})")
                                    else:
                                        logging.warning(f"User not found: ID {user_id}")
                                    await asyncio.sleep(1)
                                except SQLAlchemyError as e:
                                    logging.error(f"Database error fetching user (attempt {attempt + 1}): {e}")
                                    await asyncio.sleep(2)

                            if not user or not user.enabled:
                                logging.error(f"User {user_id} not found or disabled")
                                sys.exit(1)

                            logging.info("Fetching monitor configuration...")
                            config = MonitorConfig.query.filter_by(user_id=user_id).first()
                            if not config:
                                logging.error(f"No configuration found for user {user_id}")
                                sys.exit(1)

                            logging.info("Setting up monitor and webhook...")
                            monitor = ShopifyMonitor(rate_limit=config.rate_limit)
                            webhook = RateLimitedDiscordWebhook(webhook_url=user.discord_webhook_url)

                            logging.info(f"Monitor configuration loaded for user {user.username} (ID: {user_id})")
                            logging.info(f"- Discord Webhook: {'Configured' if user.discord_webhook_url else 'Not configured'}")
                            logging.info(f"- Rate limit: {config.rate_limit} req/s")
                            logging.info(f"- Monitor delay: {config.monitor_delay}s")

                            logging.info("=== Starting monitoring loop ===")
                            # Start heartbeat task
                            heartbeat_task = asyncio.create_task(send_heartbeat(user_id))
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
                                    batch_size = min(20, len(stores))  # Process up to 20 stores at once
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
                                            batch = retailer_stores[i:i + batch_size]
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
                        logging.error(f"Database connection error: {e}")
                        await asyncio.sleep(5)
                    except Exception as e:
                        logging.error(f"Unexpected error in inner loop: {e}")
                        await asyncio.sleep(2)

            except KeyboardInterrupt:
                logging.info("Monitoring stopped by user")
                sys.exit(0)
            except Exception as e:
                logging.error(f"Fatal error: {e}")
                await asyncio.sleep(30)

    except Exception as e:
        logging.error(f"Fatal error in main function: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        logging.info("Starting monitor main loop")
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Monitor stopped by user")
    except Exception as e:
        logging.error(f"Unhandled exception in main: {e}")