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
        try:
            with app.app_context():
                user = db.session.get(User, self.user_id)
                if not user or not user.enabled:
                    logger.error(f"User {self.user_id} not found or disabled")
                    return False

                config = MonitorConfig.query.filter_by(user_id=self.user_id).first()
                if not config:
                    logger.error(f"No configuration found for user {self.user_id}")
                    return False

                if not user.discord_webhook_url:
                    logger.error("Discord webhook URL not configured")
                    return False

                # Initialize monitor
                self.monitor = ShopifyMonitor(
                    rate_limit=config.rate_limit or 1.0,
                    proxies=None  # We'll add proxy support later
                )

                # Initialize webhook
                self.webhook = RateLimitedDiscordWebhook(webhook_url=user.discord_webhook_url)

                # Verify active stores and keywords
                stores = Store.query.filter_by(user_id=self.user_id, enabled=True).all()
                keywords = Keyword.query.filter_by(user_id=self.user_id, enabled=True).all()

                if not stores:
                    logger.error("No active stores configured")
                    return False

                if not keywords:
                    logger.error("No active keywords configured")
                    return False

                logger.info(f"Initialized monitor for user {user.username} (ID: {self.user_id})")
                logger.info(f"- Active stores: {len(stores)}")
                logger.info(f"- Active keywords: {len(keywords)}")
                logger.info(f"- Rate limit: {config.rate_limit} req/s")
                logger.info(f"- Monitor delay: {config.monitor_delay}s")

                return True

        except Exception as e:
            logger.error(f"Error initializing monitor: {e}")
            logger.error(traceback.format_exc())
            return False

    async def health_check(self, app) -> bool:
        """Perform periodic health check"""
        current_time = time.time()
        if current_time - self.last_health_check < self.health_check_interval:
            return True

        try:
            with app.app_context():
                user = db.session.get(User, self.user_id)
                if not user or not user.enabled:
                    logger.error(f"User {self.user_id} disabled")
                    return False

                if not user.discord_webhook_url:
                    logger.error("Discord webhook URL not configured")
                    return False

                self.last_health_check = current_time
                return True

        except Exception as e:
            logger.error(f"Health check error: {e}")
            return False

    async def monitor_stores(self, app) -> bool:
        """Monitor all active stores"""
        try:
            with app.app_context():
                stores = Store.query.filter_by(user_id=self.user_id, enabled=True).all()
                keywords = Keyword.query.filter_by(user_id=self.user_id, enabled=True).all()

                if not stores:
                    logger.warning("No active stores to monitor")
                    return True

                if not keywords:
                    logger.warning("No active keywords to monitor")
                    return True

                store_urls = [store.url for store in stores]
                keywords_list = [kw.word for kw in keywords]

                logger.info(f"Monitoring {len(store_urls)} stores with {len(keywords_list)} keywords")
                try:
                    products = await self.monitor.monitor_stores(store_urls, keywords_list)
                    if products:
                        logger.info(f"Found {len(products)} matching products")
                        for product in products:
                            try:
                                await self.webhook.send_product_notification(product)
                            except Exception as e:
                                logger.error(f"Error sending notification: {e}")
                                continue
                    return True

                except Exception as e:
                    self.consecutive_errors += 1
                    retry_delay = min(self.max_retry_delay, 2 ** self.consecutive_errors)
                    logger.error(f"Monitor error (attempt {self.consecutive_errors}): {e}")
                    await asyncio.sleep(retry_delay)
                    return True

        except Exception as e:
            logger.error(f"Fatal monitor error: {e}")
            logger.error(traceback.format_exc())
            return False

    async def run(self):
        """Main monitor loop"""
        from app import create_app
        app = create_app()

        try:
            if not await self.initialize(app):
                logger.error("Failed to initialize monitor")
                return

            logger.info("Monitor initialized successfully")

            while True:
                try:
                    if not await self.health_check(app):
                        logger.error("Health check failed")
                        break

                    if not await self.monitor_stores(app):
                        logger.error("Monitor cycle failed")
                        break

                    with app.app_context():
                        config = MonitorConfig.query.filter_by(user_id=self.user_id).first()
                        delay = config.monitor_delay if config else 30

                    await asyncio.sleep(delay)

                except Exception as e:
                    logger.error(f"Error in monitor loop: {e}")
                    logger.error(traceback.format_exc())
                    await asyncio.sleep(5)

        finally:
            if self.monitor:
                await self.monitor.close()

async def main():
    """Entry point"""
    try:
        user_id = None
        for arg in sys.argv[1:]:
            if arg.startswith("MONITOR_USER_ID="):
                user_id = int(arg.split("=")[1])
                break

        if not user_id:
            logger.error("MONITOR_USER_ID not provided")
            sys.exit(1)

        logger.info(f"Starting monitor for user {user_id}")
        manager = MonitorManager(user_id)
        await manager.run()

    except KeyboardInterrupt:
        logger.info("Monitor stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())