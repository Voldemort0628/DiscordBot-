import os
import sys
import logging
import asyncio
import signal
import time
import traceback
from datetime import datetime
from pathlib import Path
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import json
from typing import Dict, Set, List

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
        logging.StreamHandler(sys.stdout)
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

# Global state to track seen products
seen_products: Dict[str, Set[str]] = {}

class MonitorManager:
    def __init__(self, user_id: int, webhook_url: str, config: MonitorConfig):
        self.user_id = user_id
        self.webhook = RateLimitedDiscordWebhook(webhook_url=webhook_url)
        self.monitor = ShopifyMonitor(rate_limit=config.rate_limit)
        self.config = config
        self.running = True
        self.last_health_check = time.time()
        self.stores_status = {}

        # Set up signal handlers
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        signal.signal(signal.SIGINT, self.handle_shutdown)

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received shutdown signal {signum}")
        self.running = False

    async def monitor_store(self, store_url: str, keywords: List[str]) -> int:
        """Monitor a single store with improved error handling and retry logic"""
        if store_url not in seen_products:
            seen_products[store_url] = set()

        store_key = f"{store_url}-{self.user_id}"

        try:
            logger.info(f"Monitoring store: {store_url}")

            # Update store status
            self.stores_status[store_key] = {
                'last_check': time.time(),
                'status': 'checking'
            }

            products = await self.monitor.async_fetch_products(store_url, keywords)

            if not products:
                self.stores_status[store_key]['status'] = 'no_products'
                return 0

            new_products = 0
            for product in products:
                product_id = f"{store_url}-{product['title']}-{self.user_id}"
                if product_id not in seen_products[store_url]:
                    try:
                        webhook_success = await self.webhook.send_product_notification(product)
                        if webhook_success:
                            seen_products[store_url].add(product_id)
                            new_products += 1
                            logger.info(f"New product found and notified: {product['title']}")
                        else:
                            logger.error(f"Failed to send webhook for {product['title']}")
                    except Exception as webhook_error:
                        logger.error(f"Webhook error for {product['title']}: {webhook_error}", exc_info=True)

            self.stores_status[store_key]['status'] = 'success'
            return new_products

        except Exception as e:
            logger.error(f"Error monitoring {store_url}: {e}", exc_info=True)
            self.stores_status[store_key]['status'] = 'error'
            self.stores_status[store_key]['last_error'] = str(e)
            return 0

    async def monitor_stores(self, stores: List[Store], keywords: List[str]):
        """Monitor multiple stores concurrently"""
        while self.running:
            try:
                # Create monitoring tasks for all stores
                tasks = [
                    self.monitor_store(store.url, keywords)
                    for store in stores
                    if store.enabled
                ]

                if not tasks:
                    logger.info("No active stores to monitor")
                    await asyncio.sleep(self.config.monitor_delay)
                    continue

                # Execute all monitoring tasks concurrently
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results and handle any exceptions
                total_new = 0
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"Error monitoring store {stores[i].url}: {result}")
                    elif isinstance(result, int):
                        total_new += result

                # Adaptive delay based on results
                delay = self.config.monitor_delay * (0.25 if total_new > 0 else 1.0)
                await asyncio.sleep(max(0.05, delay))

                # Perform health check
                await self.health_check()

            except Exception as e:
                logger.error(f"Error in monitor loop: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def health_check(self):
        """Perform periodic health checks"""
        current_time = time.time()
        if current_time - self.last_health_check >= 300:  # Every 5 minutes
            logger.info("Performing health check")

            # Log monitoring statistics
            logger.info(f"Stores status: {json.dumps(self.stores_status, indent=2)}")

            # Check database connection
            try:
                with app.app_context():
                    db.session.execute(text('SELECT 1'))
                    logger.info("Database connection healthy")
            except Exception as e:
                logger.error(f"Database health check failed: {e}")

            self.last_health_check = current_time

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

    # Initialize tracking file and monitoring state
    seen_products.clear()

    try:
        with app.app_context():
            # Initialize database and verify connection
            try:
                db.create_all()
                logger.info("Database initialized successfully")
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

                    # Create monitor manager
                    manager = MonitorManager(user_id, webhook_url, config)

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

                            # Start concurrent monitoring
                            await manager.monitor_stores(stores, keywords)

                        except OperationalError as e:
                            logger.error(f"Database connection error: {e}", exc_info=True)
                            await asyncio.sleep(5)
                            break

                        except Exception as e:
                            logger.error(f"Error in monitor loop: {e}", exc_info=True)
                            traceback.print_exc()
                            await asyncio.sleep(2)

                except Exception as e:
                    logger.error(f"Fatal error: {e}", exc_info=True)
                    await asyncio.sleep(5)

    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        return 1

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