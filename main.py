import os
import asyncio
import sys
from typing import List, Dict, Set
import time
from shopify_monitor import ShopifyMonitor
from discord_webhook import DiscordWebhook
from config import MONITOR_DELAY
from flask import Flask
from models import db, Store, Keyword, MonitorConfig, User

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# Global dictionary to track user monitors
user_monitors = {}

class UserMonitor:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.seen_products = set()
        self.running = True

    async def run_monitor(self):
        """Main monitoring loop for a single user"""
        try:
            with app.app_context():
                config = MonitorConfig.query.filter_by(user_id=self.user_id).first()
                if not config:
                    config = MonitorConfig(user_id=self.user_id)
                    db.session.add(config)
                    db.session.commit()

                monitor = ShopifyMonitor(rate_limit=config.rate_limit)
                webhook = DiscordWebhook(webhook_url=config.discord_webhook_url)

                print(f"\nStarting monitor for user {self.user_id}")

                while self.running:
                    try:
                        active_stores = Store.query.filter_by(enabled=True, added_by=self.user_id).all()
                        active_keywords = Keyword.query.filter_by(enabled=True, added_by=self.user_id).all()

                        print(f"User {self.user_id} monitoring {len(active_stores)} stores")

                        for store in active_stores:
                            products = monitor.fetch_products(store.url, [k.word for k in active_keywords])
                            for product in products:
                                product_id = f"{store.url}-{product['title']}-{product['price']}"
                                if product_id not in self.seen_products:
                                    webhook.send_product_notification(product)
                                    self.seen_products.add(product_id)

                        await asyncio.sleep(config.monitor_delay)
                    except Exception as e:
                        print(f"Error in monitoring cycle for user {self.user_id}: {e}")
                        await asyncio.sleep(30)  # Wait before retrying

        except Exception as e:
            print(f"Fatal error in monitor for user {self.user_id}: {e}")
            self.running = False

async def start_user_monitor(user_id: int):
    """Start a new monitor instance for a user"""
    if user_id in user_monitors:
        return {"status": "already_running"}

    monitor = UserMonitor(user_id)
    user_monitors[user_id] = monitor
    asyncio.create_task(monitor.run_monitor())
    return {"status": "started"}

def stop_user_monitor(user_id: int):
    """Stop the monitor instance for a user"""
    if user_id in user_monitors:
        user_monitors[user_id].running = False
        del user_monitors[user_id]
        return {"status": "stopped"}
    return {"status": "not_running"}

@app.route('/start_monitor/<int:user_id>')
def start_monitor(user_id):
    asyncio.run(start_user_monitor(user_id))
    return {"status": "started", "user_id": user_id}

@app.route('/stop_monitor/<int:user_id>')
def stop_monitor(user_id):
    result = stop_user_monitor(user_id)
    return {**result, "user_id": user_id}

@app.route('/status/<int:user_id>')
def status(user_id):
    is_running = user_id in user_monitors and user_monitors[user_id].running
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
def status_all():
    """Return overall monitor status"""
    return {
        "status": "running",
        "active_monitors": len(user_monitors)
    }

if __name__ == "__main__":
    # Initialize database tables
    with app.app_context():
        db.create_all()

    # Run the Flask app for the monitor service
    app.run(host='0.0.0.0', port=3000)