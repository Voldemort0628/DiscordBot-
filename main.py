import asyncio
import sys
import os
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path

# Configure logging
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

try:
    logging.info("Attempting to import required modules...")
    from shopify_monitor import ShopifyMonitor
    from discord_webhook import RateLimitedDiscordWebhook
    from models import db, User, Store, Keyword, MonitorConfig
    from sqlalchemy.exc import OperationalError, SQLAlchemyError
    logging.info("All required modules imported successfully")
except ImportError as e:
    logging.error(f"Failed to import required modules: {e}")
    sys.exit(1)

def get_user_id():
    """Extract user ID from environment variables"""
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

    return user_id

async def monitor_store(store_url: str, keywords: list, monitor: ShopifyMonitor,
                       webhook: RateLimitedDiscordWebhook, seen_products: set, user_id: int):
    """Monitors a single store for products"""
    retry_count = 0
    max_retries = 3

    while retry_count < max_retries:
        try:
            products = await monitor.async_fetch_products(store_url, keywords)
            if not products:
                logging.warning(f"No products found for {store_url}")
                return 0

            new_products = 0
            for product in products:
                product_id = f"{store_url}-{product['id']}-{user_id}"
                if product_id not in seen_products:
                    logging.info(f"New product found: {product['title']}")
                    if await webhook.send_product_notification(product):
                        seen_products.add(product_id)
                        new_products += 1

            return new_products

        except Exception as e:
            retry_count += 1
            logging.error(f"Error monitoring {store_url} (attempt {retry_count}/{max_retries}): {e}")
            if retry_count < max_retries:
                await asyncio.sleep(1 * retry_count)
            else:
                logging.error(f"Failed to monitor {store_url} after {max_retries} attempts")
                return 0

async def main():
    user_id = get_user_id()
    seen_products = set()

    while True:
        try:
            # Initialize database session
            from models import init_db
            init_db()

            # Get user configuration
            user = db.session.get(User, user_id)
            if not user or not user.enabled:
                logging.error(f"User {user_id} not found or disabled")
                sys.exit(1)

            config = MonitorConfig.query.filter_by(user_id=user_id).first()
            if not config:
                logging.error(f"No configuration found for user {user_id}")
                sys.exit(1)

            # Initialize monitor and webhook
            monitor = ShopifyMonitor(rate_limit=config.rate_limit)
            webhook = RateLimitedDiscordWebhook(webhook_url=user.discord_webhook_url)

            while True:
                try:
                    # Refresh user and config
                    db.session.remove()
                    user = db.session.get(User, user_id)
                    if not user or not user.enabled:
                        logging.warning(f"User {user_id} was disabled, exiting...")
                        sys.exit(0)

                    stores = Store.query.filter_by(user_id=user_id, enabled=True).all()
                    keywords = [kw.word for kw in Keyword.query.filter_by(user_id=user_id, enabled=True).all()]

                    if not stores or not keywords:
                        logging.info("No active stores or keywords. Waiting...")
                        await asyncio.sleep(config.monitor_delay)
                        continue

                    # Monitor stores
                    tasks = [
                        monitor_store(
                            store.url,
                            keywords,
                            monitor,
                            webhook,
                            seen_products,
                            user_id
                        )
                        for store in stores
                    ]

                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    total_new_products = sum(r for r in results if isinstance(r, int))

                    delay = config.monitor_delay * (0.25 if total_new_products > 0 else 1.0)
                    await asyncio.sleep(max(0.05, delay))

                except OperationalError:
                    logging.error("Database connection error")
                    await asyncio.sleep(5)
                    break
                except Exception as e:
                    logging.error(f"Error in monitor loop: {e}")
                    await asyncio.sleep(2)

        except Exception as e:
            logging.error(f"Fatal error: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    try:
        logging.info("Starting monitor main loop")
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Monitor stopped by user")
    except Exception as e:
        logging.error(f"Unhandled exception in main: {e}")