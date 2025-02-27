import asyncio
import sys
import os
from typing import Dict, List
import time
import traceback
from datetime import datetime
from shopify_monitor import ShopifyMonitor
from discord_webhook import RateLimitedDiscordWebhook
from models import db, User, Store, Keyword, MonitorConfig
import logging
from logger_config import scraper_logger

logger = scraper_logger

class MonitorManager:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.monitor = None
        self.webhook = None
        self.seen_products = {}
        self.start_time = time.time()
        self.last_health_check = time.time()
        self.health_check_interval = 300  # 5 minutes
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5

    async def initialize(self, app):
        """Initialize monitor with user configuration"""
        with app.app_context():
            user = User.query.get(self.user_id)
            if not user or not user.enabled:
                logger.error(f"User {self.user_id} not found or disabled")
                return False

            config = MonitorConfig.query.filter_by(user_id=self.user_id).first()
            if not config:
                logger.error(f"No configuration found for user {self.user_id}")
                return False

            self.monitor = ShopifyMonitor(rate_limit=config.rate_limit)
            self.webhook = RateLimitedDiscordWebhook(webhook_url=user.discord_webhook_url)

            logger.info(f"Initialized monitor for user {user.username} (ID: {self.user_id})")
            logger.info(f"- Discord Webhook: {'Configured' if user.discord_webhook_url else 'Not configured'}")
            logger.info(f"- Rate limit: {config.rate_limit} req/s")
            logger.info(f"- Monitor delay: {config.monitor_delay}s")

            return True

    async def health_check(self, app) -> bool:
        """Perform periodic health check"""
        current_time = time.time()
        if current_time - self.last_health_check < self.health_check_interval:
            return True

        with app.app_context():
            user = User.query.get(self.user_id)
            if not user or not user.enabled:
                logger.warning(f"User {self.user_id} was disabled")
                return False

            config = MonitorConfig.query.filter_by(user_id=self.user_id).first()
            if not config:
                logger.error(f"Configuration missing for user {self.user_id}")
                return False

        self.last_health_check = current_time
        return True

    async def monitor_stores(self, app):
        """Monitor all active stores for the user"""
        try:
            with app.app_context():
                active_stores = Store.query.filter_by(user_id=self.user_id, enabled=True).all()
                active_keywords = Keyword.query.filter_by(user_id=self.user_id, enabled=True).all()

                if not active_stores or not active_keywords:
                    logger.info("No active stores or keywords to monitor")
                    return True

                logger.info(f"Processing {len(active_stores)} stores with {len(active_keywords)} keywords")

                # Process stores concurrently in small batches
                batch_size = 3
                for i in range(0, len(active_stores), batch_size):
                    batch = active_stores[i:i+batch_size]
                    tasks = []

                    for store in batch:
                        task = asyncio.create_task(
                            self.monitor.fetch_products(
                                store.url,
                                [kw.word for kw in active_keywords]
                            )
                        )
                        tasks.append(task)

                    try:
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        for store, result in zip(batch, results):
                            if isinstance(result, Exception):
                                logger.error(f"Error monitoring {store.url}: {result}")
                                continue

                            for product in result:
                                await self.webhook.send_product_notification(product)

                    except Exception as e:
                        logger.error(f"Batch processing error: {e}")
                        continue

                    # Brief pause between batches
                    await asyncio.sleep(1)

                self.consecutive_errors = 0
                return True

        except Exception as e:
            self.consecutive_errors += 1
            logger.error(f"Monitor cycle error: {e}")
            if self.consecutive_errors >= self.max_consecutive_errors:
                logger.error(f"Too many consecutive errors ({self.consecutive_errors})")
                return False
            return True

    async def run(self):
        """Main monitor loop with error recovery"""
        from app import create_app
        app = create_app()

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
                    logger.error("Monitor cycle failed, restarting")
                    break

                # Get delay from config
                with app.app_context():
                    config = MonitorConfig.query.filter_by(user_id=self.user_id).first()
                    delay = config.monitor_delay if config else 5

                await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"Fatal error in monitor loop: {e}")
                logger.error(traceback.format_exc())
                break

        # Cleanup
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