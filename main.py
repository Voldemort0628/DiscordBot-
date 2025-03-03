import os
import sys
import logging
import asyncio
from datetime import datetime
from pathlib import Path

# Configure logging
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

log_filename = f'monitor_{datetime.now().strftime("%Y%m%d")}.log'
log_path = log_dir / log_filename

# Enhanced logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_path),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('Monitor')

# Early startup logging
logger.info("=== Monitor Starting ===")
logger.info(f"Python version: {sys.version}")
logger.info(f"Current directory: {os.getcwd()}")
logger.info(f"PYTHONPATH: {os.environ.get('PYTHONPATH')}")

try:
    logger.info("Importing required modules...")
    from shopify_monitor import ShopifyMonitor
    from discord_webhook import RateLimitedDiscordWebhook
    from models import db, User, Store, Keyword, MonitorConfig, init_db
    from sqlalchemy.exc import OperationalError
    logger.info("All modules imported successfully")
except ImportError as e:
    logger.error(f"Failed to import required modules: {e}", exc_info=True)
    sys.exit(1)

async def monitor_store(store_url, keywords, monitor, webhook, seen_products, user_id):
    try:
        products = await monitor.async_fetch_products(store_url, keywords)
        if not products:
            return 0

        new_products = 0
        for product in products:
            product_id = f"{store_url}-{product['id']}-{user_id}"
            if product_id not in seen_products:
                if await webhook.send_product_notification(product):
                    seen_products.add(product_id)
                    new_products += 1
                    logger.info(f"New product found: {product['title']}")

        return new_products

    except Exception as e:
        logger.error(f"Error monitoring {store_url}: {e}", exc_info=True)
        return 0

async def main():
    # Validate environment
    user_id = os.environ.get('MONITOR_USER_ID')
    if not user_id:
        logger.error("MONITOR_USER_ID not set")
        return 1

    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        logger.error("DISCORD_WEBHOOK_URL not set")
        return 1

    try:
        user_id = int(user_id)
        logger.info(f"Starting monitor for user ID: {user_id}")
    except ValueError:
        logger.error(f"Invalid MONITOR_USER_ID: {user_id}")
        return 1

    seen_products = set()

    # Create process tracking file
    tracking_file = f"monitor_process_{user_id}.json"
    try:
        import json
        with open(tracking_file, 'w') as f:
            json.dump({
                'pid': os.getpid(),
                'start_time': datetime.now().isoformat()
            }, f)
        logger.info(f"Created tracking file for PID {os.getpid()}")
    except Exception as e:
        logger.error(f"Failed to create tracking file: {e}")

    try:
        # Initialize database
        logger.info("Initializing database...")
        init_db()
        logger.info("Database initialized successfully")

        while True:
            try:
                # Get user configuration
                user = db.session.get(User, user_id)
                if not user or not user.enabled:
                    logger.error(f"User {user_id} not found or disabled")
                    return 1

                config = MonitorConfig.query.filter_by(user_id=user_id).first()
                if not config:
                    logger.error(f"No configuration found for user {user_id}")
                    return 1

                logger.info(f"Loaded configuration for user {user_id}")
                logger.info(f"Rate limit: {config.rate_limit} req/s")
                logger.info(f"Monitor delay: {config.monitor_delay}s")

                # Initialize monitor
                monitor = ShopifyMonitor(rate_limit=config.rate_limit)
                webhook = RateLimitedDiscordWebhook(webhook_url=webhook_url)

                while True:
                    try:
                        # Refresh user and get stores/keywords
                        db.session.remove()
                        user = db.session.get(User, user_id)
                        if not user or not user.enabled:
                            logger.warning(f"User {user_id} disabled, exiting")
                            return 0

                        stores = Store.query.filter_by(user_id=user_id, enabled=True).all()
                        keywords = [kw.word for kw in Keyword.query.filter_by(user_id=user_id, enabled=True).all()]

                        if not stores or not keywords:
                            await asyncio.sleep(config.monitor_delay)
                            continue

                        # Monitor stores
                        tasks = []
                        for store in stores:
                            task = monitor_store(
                                store.url, 
                                keywords,
                                monitor,
                                webhook,
                                seen_products,
                                user_id
                            )
                            tasks.append(task)

                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        total_new = sum(r for r in results if isinstance(r, int))

                        # Adaptive delay based on results
                        delay = config.monitor_delay * (0.25 if total_new > 0 else 1.0)
                        await asyncio.sleep(max(0.05, delay))

                    except OperationalError as e:
                        logger.error(f"Database connection error: {e}", exc_info=True)
                        await asyncio.sleep(5)
                        break

                    except Exception as e:
                        logger.error(f"Error in monitor loop: {e}", exc_info=True)
                        await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Fatal error: {e}", exc_info=True)
                await asyncio.sleep(5)

    finally:
        # Cleanup tracking file on exit
        try:
            if os.path.exists(tracking_file):
                os.remove(tracking_file)
                logger.info("Removed tracking file")
        except Exception as e:
            logger.error(f"Error removing tracking file: {e}")

if __name__ == "__main__":
    try:
        logger.info("Starting monitor main process")
        exit_code = asyncio.run(main())
        logger.info(f"Monitor exiting with code {exit_code}")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Monitor stopped by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)