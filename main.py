import asyncio
import sys
import os
from typing import List, Dict, Set
import time
from shopify_monitor import ShopifyMonitor
from discord_webhook import DiscordWebhook
from config import MONITOR_DELAY
from stores import SHOPIFY_STORES, DEFAULT_KEYWORDS
from flask import Flask
from models import db, Store, Keyword, MonitorConfig, User

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

class UserMonitor:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.seen_products = set()
        self.running = True

    async def monitor_store(self, store_url: str, keywords: List[str], monitor: ShopifyMonitor, 
                          webhook: DiscordWebhook):
        """Monitors a single store for products"""
        try:
            products = monitor.fetch_products(store_url, keywords)
            new_products = 0

            for product in products:
                product_identifier = f"{store_url}-{product['title']}-{product['price']}"

                if product_identifier not in self.seen_products:
                    print(f"New product found for user {self.user_id} on {store_url}: {product['title']}")
                    webhook.send_product_notification(product)
                    self.seen_products.add(product_identifier)
                    new_products += 1

            return new_products
        except Exception as e:
            print(f"Error monitoring {store_url} for user {self.user_id}: {e}")
            return 0

    async def run_monitor(self):
        """Main monitoring loop for a single user"""
        try:
            with app.app_context():
                # Get user's configuration
                config = MonitorConfig.query.filter_by(user_id=self.user_id).first()
                if not config:
                    config = MonitorConfig(user_id=self.user_id)
                    db.session.add(config)
                    db.session.commit()

                # Initialize monitor and webhook with user's configuration
                monitor = ShopifyMonitor(rate_limit=config.rate_limit)
                webhook = DiscordWebhook(webhook_url=config.discord_webhook_url)

                print(f"\nStarting monitor for user {self.user_id} with configuration:")
                print(f"- Rate limit: {config.rate_limit} req/s")
                print(f"- Monitor delay: {config.monitor_delay} seconds")
                print(f"- Max products: {config.max_products}")
                print(f"- Discord webhook: {'Configured' if config.discord_webhook_url else 'Not configured'}\n")

                while self.running:
                    # Get active stores and keywords for this user
                    active_stores = [store.url for store in Store.query.filter_by(enabled=True, added_by=self.user_id).all()]
                    active_keywords = [kw.word for kw in Keyword.query.filter_by(enabled=True, added_by=self.user_id).all()]

                    print(f"User {self.user_id} monitoring {len(active_stores)} stores")
                    print(f"Keywords: {', '.join(active_keywords)}")

                    tasks = []
                    for store_url in active_stores:
                        task = asyncio.create_task(
                            self.monitor_store(store_url, active_keywords, monitor, webhook)
                        )
                        tasks.append(task)

                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    total_new_products = sum(r for r in results if isinstance(r, int))

                    print(f"\nCompleted monitoring cycle for user {self.user_id}:")
                    print(f"- New products found: {total_new_products}")
                    print(f"- Stores with issues: {len(monitor.failed_stores)}")
                    if monitor.failed_stores:
                        print("- Failed stores:", ", ".join(monitor.failed_stores))
                    print(f"- Total products tracked: {len(self.seen_products)}")
                    print(f"- Active stores: {len(active_stores)}\n")

                    await asyncio.sleep(config.monitor_delay)

        except Exception as e:
            print(f"Fatal error in monitor for user {self.user_id}: {e}")
            self.running = False

# Global dictionary to track user monitors
user_monitors = {}

async def start_user_monitor(user_id: int):
    """Start a new monitor instance for a user"""
    if user_id in user_monitors:
        print(f"Monitor already running for user {user_id}")
        return

    monitor = UserMonitor(user_id)
    user_monitors[user_id] = monitor
    await monitor.run_monitor()

def stop_user_monitor(user_id: int):
    """Stop the monitor instance for a user"""
    if user_id in user_monitors:
        user_monitors[user_id].running = False
        del user_monitors[user_id]
        print(f"Stopped monitor for user {user_id}")

@app.route('/start_monitor/<int:user_id>')
def start_monitor(user_id):
    """Start monitoring for a specific user"""
    asyncio.run(start_user_monitor(user_id))
    return {"status": "started", "user_id": user_id}

@app.route('/stop_monitor/<int:user_id>')
def stop_monitor(user_id):
    """Stop monitoring for a specific user"""
    stop_user_monitor(user_id)
    return {"status": "stopped", "user_id": user_id}

@app.route('/status/<int:user_id>')
def status_user(user_id):
    """Return the monitor status for a specific user"""
    is_running = user_id in user_monitors
    return {
        "status": "running" if is_running else "stopped",
        "user_id": user_id,
        "active_monitors": len(user_monitors)
    }

@app.route('/')
def home():
    """Homepage that shows the monitor status"""
    return "Shopify Monitor is running. Access the dashboard at /dashboard"

@app.route('/dashboard')
def redirect_to_dashboard():
    """Redirect to the main dashboard app"""
    from flask import redirect
    # Redirect to the web dashboard - use the default port (80) for the main app
    dashboard_url = f"https://{os.environ.get('REPL_SLUG')}.{os.environ.get('REPL_OWNER')}.repl.co"
    return redirect(dashboard_url)

@app.route('/status')
def status():
    """Return the monitor status"""
    return {"status": "running", "stores_count": len(SHOPIFY_STORES), "keywords_count": len(DEFAULT_KEYWORDS)}

if __name__ == "__main__":
    # Start the Flask server
    # Make sure to bind to 0.0.0.0 for Replit deployment
    app.run(host='0.0.0.0', port=3000)  # Changed port to avoid conflict with app.py