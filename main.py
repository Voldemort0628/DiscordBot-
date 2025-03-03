import os
import sys
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import json

# Configure logging
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

log_filename = f'monitor_{datetime.now().strftime("%Y%m%d")}.log'
log_path = log_dir / log_filename

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_path),
        logging.StreamHandler(sys.stdout)  # Log to stdout for subprocess capture
    ]
)

logger = logging.getLogger('Monitor')

# Early environment check logging
logger.info("=== Monitor Starting ===")
logger.info(f"Environment variables:")
logger.info(f"MONITOR_USER_ID: {os.environ.get('MONITOR_USER_ID')}")
logger.info(f"DISCORD_WEBHOOK_URL: {'Set' if os.environ.get('DISCORD_WEBHOOK_URL') else 'Not set'}")
logger.info(f"DATABASE_URL: {'Set' if os.environ.get('DATABASE_URL') else 'Not set'}")
logger.info(f"Command line args: {sys.argv}")
logger.info(f"Current working directory: {os.getcwd()}")
logger.info(f"Python path: {sys.path}")
logger.info("=====================")

# Create Flask app
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# Import required modules
try:
    logger.info("Importing required modules...")
    from shopify_monitor import ShopifyMonitor
    from discord_webhook import RateLimitedDiscordWebhook
    from models import db, User, Store, Keyword, MonitorConfig
    from sqlalchemy.exc import OperationalError
    logger.info("All modules imported successfully")
except ImportError as e:
    logger.error(f"Failed to import required modules: {e}", exc_info=True)
    sys.exit(1)

# Initialize SQLAlchemy with app
db.init_app(app)

async def monitor_store(store_url, keywords, monitor, webhook, seen_products, user_id):
    """Monitors a single store for products"""
    try:
        logger.info(f"Monitoring store: {store_url}")
        logger.info(f"Using webhook URL: {'Set' if webhook.webhook_url else 'Not set'}")

        products = await monitor.async_fetch_products(store_url, keywords)
        if not products:
            logger.warning(f"No products found for {store_url}")
            return 0

        new_products = 0
        for product in products:
            product_id = f"{store_url}-{product['title']}-{user_id}"
            if product_id not in seen_products:
                try:
                    # Add debug logging for webhook sending
                    logger.info(f"Attempting to send webhook for product: {product['title']}")
                    webhook_success = await webhook.send_product_notification(product)
                    if webhook_success:
                        seen_products.add(product_id)
                        new_products += 1
                        logger.info(f"Successfully sent webhook for product: {product['title']}")
                    else:
                        logger.error(f"Failed to send webhook for product: {product['title']}")
                except Exception as webhook_error:
                    logger.error(f"Error sending webhook for {product['title']}: {webhook_error}", exc_info=True)

        return new_products

    except Exception as e:
        logger.error(f"Error monitoring {store_url}: {e}", exc_info=True)
        return 0

async def main():
    # Early validation of required environment variables
    required_vars = ['MONITOR_USER_ID', 'DISCORD_WEBHOOK_URL', 'DATABASE_URL']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return 1

    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
    if not webhook_url or not webhook_url.startswith('https://discord.com/api/webhooks/'):
        logger.error("Invalid Discord webhook URL")
        return 1

    try:
        user_id = int(os.environ.get('MONITOR_USER_ID'))
    except ValueError:
        logger.error(f"Invalid MONITOR_USER_ID: {os.environ.get('MONITOR_USER_ID')}")
        return 1

    seen_products = set()

    # Create process tracking file
    tracking_file = f"monitor_process_{user_id}.json"
    try:
        with open(tracking_file, 'w') as f:
            json.dump({
                'pid': os.getpid(),
                'start_time': datetime.now().isoformat()
            }, f)
        logger.info(f"Created tracking file for PID {os.getpid()}")
    except Exception as e:
        logger.error(f"Failed to create tracking file: {e}")

    try:
        with app.app_context():
            # Initialize database and verify connection
            try:
                # Create tables if they don't exist
                db.create_all()
                logger.info("Database initialized successfully")

                # Verify database connection using text()
                db.session.execute(text('SELECT 1'))
                logger.info("Database connection test successful")
            except Exception as e:
                logger.error(f"Database initialization error: {e}", exc_info=True)
                return 1

            logger.info("Starting main monitoring loop...")
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

                    # Initialize monitor with webhook test
                    monitor = ShopifyMonitor(rate_limit=config.rate_limit)
                    webhook = RateLimitedDiscordWebhook(webhook_url=webhook_url)

                    # Test webhook before starting monitoring
                    test_payload = {
                        "username": "Monitor Test",
                        "content": "Monitor starting up - webhook test message"
                    }
                    try:
                        await webhook._send_webhook_with_backoff(test_payload)
                        logger.info("Initial webhook test successful")
                    except Exception as e:
                        logger.error(f"Initial webhook test failed: {e}", exc_info=True)
                        # Continue anyway, as the webhook might work later

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
                                logger.info("No stores or keywords configured, waiting...")
                                await asyncio.sleep(config.monitor_delay)
                                continue

                            logger.info(f"Monitoring {len(stores)} stores with {len(keywords)} keywords")

                            # Monitor stores in parallel
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