import os
import asyncio
import sys
from typing import Dict, Set
import time
from shopify_monitor import ShopifyMonitor
from discord_webhook import DiscordWebhook
from flask import Flask, jsonify, request
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
                    print(f"No configuration found for user {self.user_id}")
                    self.running = False
                    return

                monitor = ShopifyMonitor(rate_limit=config.rate_limit)
                webhook = DiscordWebhook(webhook_url=config.discord_webhook_url)

                print(f"Starting monitor for user {self.user_id}")
                print(f"Configuration: rate_limit={config.rate_limit}, delay={config.monitor_delay}")

                while self.running:
                    try:
                        stores = Store.query.filter_by(enabled=True, added_by=self.user_id).all()
                        keywords = Keyword.query.filter_by(enabled=True, added_by=self.user_id).all()

                        if not stores or not keywords:
                            print(f"No active stores or keywords for user {self.user_id}")
                            await asyncio.sleep(config.monitor_delay)
                            continue

                        print(f"User {self.user_id} monitoring {len(stores)} stores")

                        for store in stores:
                            try:
                                products = monitor.fetch_products(store.url, [k.word for k in keywords])
                                for product in products:
                                    product_id = f"{store.url}-{product['title']}-{product['price']}"
                                    if product_id not in self.seen_products:
                                        webhook.send_product_notification(product)
                                        self.seen_products.add(product_id)
                            except Exception as e:
                                print(f"Error monitoring store {store.url}: {e}")

                        await asyncio.sleep(config.monitor_delay)
                    except Exception as e:
                        print(f"Error in monitoring cycle for user {self.user_id}: {e}")
                        await asyncio.sleep(30)  # Wait before retrying

        except Exception as e:
            print(f"Fatal error in monitor for user {self.user_id}: {e}")
            self.running = False

@app.route('/start_monitor/<int:user_id>')
def start_monitor(user_id):
    """Start a new monitor instance for a user"""
    print(f"Received start monitor request for user {user_id}")

    with app.app_context():
        config = MonitorConfig.query.filter_by(user_id=user_id).first()
        if not config:
            print(f"No configuration found for user {user_id}")
            return jsonify({"status": "error", "message": "No configuration found"}), 400

    if user_id in user_monitors and user_monitors[user_id].running:
        print(f"Monitor already running for user {user_id}")
        return jsonify({"status": "already_running"})

    monitor = UserMonitor(user_id)
    user_monitors[user_id] = monitor
    asyncio.create_task(monitor.run_monitor())
    print(f"Started monitor for user {user_id}")
    return jsonify({"status": "started"})

@app.route('/stop_monitor/<int:user_id>')
def stop_monitor(user_id):
    """Stop the monitor instance for a user"""
    print(f"Received stop monitor request for user {user_id}")
    if user_id in user_monitors:
        user_monitors[user_id].running = False
        del user_monitors[user_id]
        print(f"Stopped monitor for user {user_id}")
        return jsonify({"status": "stopped"})
    return jsonify({"status": "not_running"})

@app.route('/status/<int:user_id>')
def status(user_id):
    """Check if monitor is running for a specific user"""
    is_running = user_id in user_monitors and user_monitors[user_id].running
    status_info = {
        "status": "running" if is_running else "stopped",
        "user_id": user_id,
        "active_monitors": len(user_monitors)
    }
    print(f"Status check for user {user_id}: {status_info}")
    return jsonify(status_info)

@app.route('/')
def home():
    """Homepage showing monitor service status"""
    return jsonify({
        "status": "running",
        "active_monitors": len(user_monitors)
    })

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    # ALWAYS serve the app on port 3000
    app.run(host='0.0.0.0', port=3000)