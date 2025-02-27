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
from models import db, Store, Keyword, MonitorConfig

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

async def monitor_store(store_url: str, keywords: List[str], monitor: ShopifyMonitor, 
                       webhook: DiscordWebhook, seen_products: Set[str]):
    """Monitors a single store for products"""
    try:
        products = monitor.fetch_products(store_url, keywords)
        new_products = 0

        for product in products:
            product_identifier = f"{store_url}-{product['title']}-{product['price']}"

            if product_identifier not in seen_products:
                print(f"New product found on {store_url}: {product['title']}")
                webhook.send_product_notification(product)
                seen_products.add(product_identifier)
                new_products += 1

        return new_products
    except Exception as e:
        print(f"Error monitoring {store_url}: {e}")
        return 0

async def main():
    try:
        with app.app_context():
            # Get configuration from database
            config = MonitorConfig.query.first()
            if not config:
                config = MonitorConfig()
                db.session.add(config)
                db.session.commit()

            # Initialize monitor and webhook with configuration
            monitor = ShopifyMonitor(rate_limit=config.rate_limit)
            webhook = DiscordWebhook(webhook_url=config.discord_webhook_url)
            seen_products = set()

            print("Starting monitor with configuration:")
            print(f"- Rate limit: {config.rate_limit} req/s")
            print(f"- Monitor delay: {config.monitor_delay} seconds")
            print(f"- Max products: {config.max_products}")
            print(f"- Discord webhook: {'Configured' if config.discord_webhook_url else 'Not configured'}")
            print("\nPress Ctrl+C to stop monitoring\n")

            while True:
                # Get active stores and keywords from database
                active_stores = [store.url for store in Store.query.filter_by(enabled=True).all()]
                active_keywords = [kw.word for kw in Keyword.query.filter_by(enabled=True).all()]

                print(f"Starting monitor for {len(active_stores)} stores")
                print(f"Monitoring for keywords: {', '.join(active_keywords)}")

                tasks = []
                for store_url in active_stores:
                    task = asyncio.create_task(
                        monitor_store(store_url, active_keywords, monitor, webhook, seen_products)
                    )
                    tasks.append(task)

                results = await asyncio.gather(*tasks, return_exceptions=True)
                total_new_products = sum(r for r in results if isinstance(r, int))

                print(f"\nCompleted monitoring cycle:")
                print(f"- New products found: {total_new_products}")
                print(f"- Stores with issues: {len(monitor.failed_stores)}")
                if monitor.failed_stores:
                    print("- Failed stores:", ", ".join(monitor.failed_stores))
                print(f"- Total products tracked: {len(seen_products)}")
                print(f"- Active stores: {len(active_stores)}")

                await asyncio.sleep(config.monitor_delay)

    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)

@app.route('/')
def home():
    """Homepage that shows the monitor status"""
    return "Shopify Monitor is running. Access the dashboard at /dashboard"

@app.route('/dashboard')
def redirect_to_dashboard():
    """Redirect to the main dashboard app"""
    return "Visit the web dashboard to manage the monitor"

@app.route('/status')
def status():
    """Return the monitor status"""
    return {"status": "running", "stores_count": len(SHOPIFY_STORES), "keywords_count": len(DEFAULT_KEYWORDS)}

if __name__ == "__main__":
    # Start the monitor in a background thread
    import threading
    monitor_thread = threading.Thread(target=lambda: asyncio.run(main()))
    monitor_thread.daemon = True
    monitor_thread.start()
    
    # Start the Flask server
    # Make sure to bind to 0.0.0.0 for Replit deployment
    app.run(host='0.0.0.0', port=5000)