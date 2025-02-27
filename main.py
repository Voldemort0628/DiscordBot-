import asyncio
import sys
import os
import time
import traceback
from datetime import datetime
from shopify_monitor import ShopifyMonitor
from discord_webhook import RateLimitedDiscordWebhook
from models import db, User, Store, Keyword, MonitorConfig
from logger_config import scraper_logger

logger = scraper_logger

class MonitorManager:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.monitor = None
        self.webhook = None
        self.start_time = time.time()
        self.last_health_check = time.time()
        self.health_check_interval = 300  # 5 minutes
        self.consecutive_errors = 0
        self.max_retry_delay = 300  # 5 minutes max delay

    async def initialize(self, app):
        """Initialize monitor with user configuration"""
        with app.app_context():
            try:
                user = User.query.get(self.user_id)
                if not user or not user.enabled:
                    logger.error(f"User {self.user_id} not found or disabled")
                    return False

                config = MonitorConfig.query.filter_by(user_id=self.user_id).first()
                if not config:
                    logger.error(f"No configuration found for user {self.user_id}")
                    return False

                # Get proxies if enabled
                proxies = None
                if config.use_proxies:
                    proxies = [
                        f"{p.protocol}://{p.username}:{p.password}@{p.ip}:{p.port}"
                        if p.username and p.password else
                        f"{p.protocol}://{p.ip}:{p.port}"
                        for p in user.proxies if p.enabled
                    ]

                # Initialize monitor with configuration
                self.monitor = ShopifyMonitor(
                    rate_limit=config.rate_limit,
                    proxies=proxies
                )

                # Initialize webhook
                if not user.discord_webhook_url:
                    logger.error("Discord webhook URL not configured")
                    return False

                self.webhook = RateLimitedDiscordWebhook(webhook_url=user.discord_webhook_url)

                logger.info(f"Initialized monitor for user {user.username} (ID: {self.user_id})")
                logger.info(f"- Discord Webhook: Configured")
                logger.info(f"- Rate limit: {config.rate_limit} req/s")
                logger.info(f"- Monitor delay: {config.monitor_delay}s")
                logger.info(f"- Proxies: {'Enabled' if proxies else 'Disabled'}")

                return True

            except Exception as e:
                logger.error(f"Error initializing monitor: {e}")
                return False

    async def health_check(self, app) -> bool:
        """Perform periodic health check"""
        current_time = time.time()

        # Skip if not enough time has passed
        if current_time - self.last_health_check < self.health_check_interval:
            return True

        try:
            with app.app_context():
                user = User.query.get(self.user_id)
                if not user or not user.enabled:
                    logger.warning(f"User {self.user_id} was disabled")
                    return False

                config = MonitorConfig.query.filter_by(user_id=self.user_id).first()
                if not config:
                    logger.error(f"Configuration missing for user {self.user_id}")
                    return False

                # Verify webhook
                if not user.discord_webhook_url:
                    logger.error("Discord webhook URL not configured")
                    return False

            self.last_health_check = current_time
            return True

        except Exception as e:
            logger.error(f"Health check error: {e}")
            return False

    async def monitor_stores(self, app):
        """Monitor all active stores for the user"""
        try:
            with app.app_context():
                # Get active stores and keywords
                active_stores = Store.query.filter_by(user_id=self.user_id, enabled=True).all()
                active_keywords = Keyword.query.filter_by(user_id=self.user_id, enabled=True).all()

                if not active_stores:
                    logger.info("No active stores to monitor")
                    return True

                if not active_keywords:
                    logger.info("No active keywords to monitor")
                    return True

                store_urls = [store.url for store in active_stores]
                keywords = [kw.word for kw in active_keywords]

                logger.info(f"Processing {len(store_urls)} stores with {len(keywords)} keywords")

                # Monitor stores and handle products
                try:
                    products = await self.monitor.monitor_stores(store_urls, keywords)
                    logger.info(f"Found {len(products)} matching products")

                    for product in products:
                        try:
                            await self.webhook.send_product_notification(product)
                        except Exception as e:
                            logger.error(f"Error sending notification: {e}")
                            continue

                    self.consecutive_errors = 0
                    return True

                except Exception as e:
                    self.consecutive_errors += 1
                    retry_delay = min(self.max_retry_delay, 2 ** self.consecutive_errors)
                    logger.error(f"Monitor error (attempt {self.consecutive_errors}): {e}")
                    logger.info(f"Retrying in {retry_delay} seconds")
                    await asyncio.sleep(retry_delay)
                    return True

        except Exception as e:
            logger.error(f"Fatal monitor error: {e}")
            logger.error(traceback.format_exc())
            return False

    async def run(self):
        """Main monitor loop with error recovery"""
        from app import create_app
        app = create_app()

        try:
            if not await self.initialize(app):
                return

            while True:
                try:
                    # Health check
                    if not await self.health_check(app):
                        logger.info("Health check failed, stopping monitor")
                        break

                    # Monitor cycle
                    if not await self.monitor_stores(app):
                        logger.error("Monitor cycle failed, stopping")
                        break

                    # Get delay from config
                    with app.app_context():
                        config = MonitorConfig.query.filter_by(user_id=self.user_id).first()
                        delay = config.monitor_delay if config else 30

                    await asyncio.sleep(delay)

                except Exception as e:
                    logger.error(f"Error in monitor loop: {e}")
                    logger.error(traceback.format_exc())
                    await asyncio.sleep(5)  # Brief pause before retrying

        finally:
            if self.monitor:
                await self.monitor.close()

async def main():
    try:
        # Extract user ID from command line arguments
        user_id = None
        for arg in sys.argv[1:]:
            if arg.startswith("MONITOR_USER_ID="):
                user_id = int(arg.split("=")[1])
                break

        if not user_id:
            logger.error("MONITOR_USER_ID not provided")
            sys.exit(1)

        manager = MonitorManager(user_id)
        await manager.run()

    except KeyboardInterrupt:
        logger.info("Monitor stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Error in main: {e}")
        sys.exit(1)