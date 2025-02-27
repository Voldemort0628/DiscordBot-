import asyncio
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Store, Keyword, MonitorConfig, RetailScraper, Proxy
from forms import LoginForm, RegistrationForm, StoreForm, KeywordForm, ConfigForm, VariantScraperForm, RetailScraperForm, ProxyForm, ProxyImportForm
from stores import SHOPIFY_STORES, DEFAULT_KEYWORDS
from scrapers.target_scraper import TargetScraper  # Import the new Target scraper
import os
import json
import requests
from datetime import datetime
from discord_webhook import DiscordWebhook
import subprocess
import psutil

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def is_monitor_running():
    """Check if the monitor process is running"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'python' in proc.info['name'] and 'main.py' in ' '.join(proc.info['cmdline'] or []):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

@app.route('/')
@login_required
def dashboard():
    stores = Store.query.filter_by(user_id=current_user.id).all()
    keywords = Keyword.query.filter_by(user_id=current_user.id).all()
    config = MonitorConfig.query.filter_by(user_id=current_user.id).first()
    monitor_running = is_monitor_running()
    return render_template('dashboard.html', 
                         stores=stores, 
                         keywords=keywords, 
                         config=config,
                         monitor_running=monitor_running)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/stores', methods=['GET', 'POST'])
@login_required
def manage_stores():
    form = StoreForm()
    if form.validate_on_submit():
        store = Store(
            url=form.url.data,
            enabled=form.enabled.data,
            user_id=current_user.id
        )
        db.session.add(store)
        db.session.commit()
        flash('Store added successfully')
        return redirect(url_for('manage_stores'))

    # Show only user's stores
    stores = Store.query.filter_by(user_id=current_user.id).all()
    return render_template('stores.html', form=form, stores=stores)

@app.route('/keywords', methods=['GET', 'POST'])
@login_required
def manage_keywords():
    form = KeywordForm()
    if form.validate_on_submit():
        try:
            # Check if user already has this keyword
            existing = Keyword.query.filter_by(
                word=form.word.data,
                user_id=current_user.id
            ).first()

            if existing:
                flash('You already have this keyword added.')
                return redirect(url_for('manage_keywords'))

            # Create new keyword
            keyword = Keyword(
                word=form.word.data,
                enabled=form.enabled.data,
                user_id=current_user.id
            )
            db.session.add(keyword)
            db.session.commit()
            flash('Keyword added successfully')

        except Exception as e:
            db.session.rollback()
            flash('Error adding keyword. Please try again.')
            print(f"Keyword creation error: {e}")

        return redirect(url_for('manage_keywords'))

    # Show only user's keywords
    keywords = Keyword.query.filter_by(user_id=current_user.id).all()
    return render_template('keywords.html', form=form, keywords=keywords)

@app.route('/config', methods=['GET', 'POST'])
@login_required
def manage_config():
    # Get or create user-specific config
    config = MonitorConfig.query.filter_by(user_id=current_user.id).first()
    if not config:
        config = MonitorConfig(user_id=current_user.id)
        db.session.add(config)
        db.session.commit()

    form = ConfigForm(obj=config)
    if form.validate_on_submit():
        form.populate_obj(config)
        current_user.discord_webhook_url = form.discord_webhook_url.data
        db.session.commit()
        flash('Configuration updated successfully')

        # Restart monitor if it's running to pick up new webhook URL
        if is_monitor_running():
            subprocess.Popen(['python', 'main.py'])
            flash('Monitor restarted with new configuration')

        return redirect(url_for('dashboard'))

    # Pre-populate Discord webhook URL from user model
    form.discord_webhook_url.data = current_user.discord_webhook_url
    return render_template('config.html', form=form)

@app.route('/variants', methods=['GET', 'POST'])
@login_required
def variant_scraper():
    form = VariantScraperForm()
    variants = []
    cart_url = None

    if form.validate_on_submit():
        try:
            # Extract product handle from URL
            product_url = form.product_url.data
            store_url = '/'.join(product_url.split('/')[:-2])  # Remove /products/handle
            product_handle = product_url.split('/')[-1]

            # Fetch product data
            api_url = f"{store_url}/products/{product_handle}.json"
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()

            product_data = response.json()['product']
            variants = product_data['variants']
            cart_url = store_url + '/cart'

            flash('Successfully scraped product variants', 'success')
        except Exception as e:
            flash(f'Error scraping variants: {str(e)}', 'error')

    return render_template('variants.html', form=form, variants=variants, cart_url=cart_url)


@app.route('/toggle_monitor', methods=['POST'])
@login_required
def toggle_monitor():
    if is_monitor_running():
        # Stop all Python processes running main.py
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if 'python' in proc.info['name'] and 'main.py' in ' '.join(proc.info['cmdline'] or []):
                    psutil.Process(proc.info['pid']).terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        flash('Monitor stopped successfully')
    else:
        # Start the monitor
        subprocess.Popen(['python', 'main.py'])
        flash('Monitor started successfully')

    return redirect(url_for('dashboard'))

@app.route('/retail', methods=['GET', 'POST'])
@login_required
def retail_scraper():
    form = RetailScraperForm()
    results = []

    # Get user's webhook configuration
    config = MonitorConfig.query.filter_by(user_id=current_user.id).first()
    webhook = DiscordWebhook(webhook_url=config.discord_webhook_url) if config and config.discord_webhook_url else None

    if form.validate_on_submit():
        scraper = RetailScraper(
            retailer=form.retailer.data,
            keyword=form.keyword.data,
            check_frequency=form.check_frequency.data,
            enabled=form.enabled.data,
            added_by=current_user.id
        )
        db.session.add(scraper)
        db.session.commit()
        flash('Retail scraper added successfully')

    elif request.method == 'POST' and 'action' in request.form:
        scraper_id = request.form.get('scraper_id')
        scraper = RetailScraper.query.get(scraper_id)

        if scraper:
            action = request.form['action']
            if action == 'toggle':
                scraper.enabled = not scraper.enabled
                db.session.commit()
                flash(f"Scraper {'enabled' if scraper.enabled else 'disabled'}")
            elif action == 'delete':
                db.session.delete(scraper)
                db.session.commit()
                flash('Scraper deleted')
            elif action == 'scrape_now':
                try:
                    if scraper.retailer == 'target':
                        # Use the new Target scraper
                        target_scraper = TargetScraper()
                        results = target_scraper.search_products(scraper.keyword)

                        # Send results to Discord if webhook is configured
                        if webhook:
                            for result in results:
                                product_data = {
                                    'title': result.title,
                                    'price': result.price,
                                    'url': result.url,
                                    'image_url': result.image_url,
                                    'retailer': result.retailer.title()
                                }
                                webhook.send_product_notification(product_data)
                        else:
                            flash('Warning: Discord webhook URL not configured in settings')

                        scraper.last_check = datetime.utcnow()
                        db.session.commit()
                        flash(f'Target scrape completed - Found {len(results)} items')
                    else:
                        flash(f'Scraping for {scraper.retailer} is not yet implemented')

                except Exception as e:
                    error_msg = str(e)
                    print(f"Scraping error: {error_msg}")  # Log the error
                    flash(f'Error during scraping: {error_msg}', 'error')

    scrapers = RetailScraper.query.all()
    return render_template('retail_scraper.html', form=form, scrapers=scrapers, results=results)

@app.route('/proxies', methods=['GET', 'POST'])
@login_required
def manage_proxies():
    form = ProxyForm()
    import_form = ProxyImportForm()

    if form.validate_on_submit():
        proxy = Proxy(
            ip=form.ip.data,
            port=form.port.data,
            username=form.username.data,
            password=form.password.data,
            protocol=form.protocol.data,
            country=form.country.data,
            enabled=form.enabled.data,
            added_by=current_user.id
        )
        db.session.add(proxy)
        db.session.commit()
        flash('Proxy added successfully')
        return redirect(url_for('manage_proxies'))

    elif request.method == 'POST' and 'action' in request.form:
        proxy_id = request.form.get('proxy_id')
        proxy = Proxy.query.get(proxy_id)

        if proxy:
            action = request.form['action']
            if action == 'toggle':
                proxy.enabled = not proxy.enabled
                db.session.commit()
                flash(f"Proxy {'enabled' if proxy.enabled else 'disabled'}")
            elif action == 'delete':
                db.session.delete(proxy)
                db.session.commit()
                flash('Proxy deleted')
            elif action == 'test':
                # Test proxy connection
                try:
                    test_url = "http://httpbin.org/ip"
                    proxy_url = f"{proxy.protocol}://{proxy.username}:{proxy.password}@{proxy.ip}:{proxy.port}" if proxy.username and proxy.password else f"{proxy.protocol}://{proxy.ip}:{proxy.port}"
                    response = requests.get(test_url, proxies={
                        'http': proxy_url,
                        'https': proxy_url
                    }, timeout=10)
                    if response.status_code == 200:
                        proxy.success_count += 1
                        flash(f'Proxy test successful! Response: {response.json()}')
                    else:
                        proxy.failure_count += 1
                        flash('Proxy test failed: Bad response', 'error')
                except Exception as e:
                    proxy.failure_count += 1
                    flash(f'Proxy test failed: {str(e)}', 'error')
                proxy.last_used = datetime.utcnow()
                db.session.commit()

        return redirect(url_for('manage_proxies'))

    proxies = Proxy.query.all()
    return render_template('proxies.html', form=form, import_form=import_form, proxies=proxies)

@app.route('/import_proxies', methods=['POST'])
@login_required
def import_proxies():
    form = ProxyImportForm()
    if form.validate_on_submit():
        proxy_list = form.proxy_list.data.strip().split('\n')
        added = 0
        for proxy_line in proxy_list:
            try:
                parts = proxy_line.strip().split(':')
                if len(parts) == 2:  # ip:port format
                    ip, port = parts
                    username = password = None
                elif len(parts) == 4:  # ip:port:username:password format
                    ip, port, username, password = parts
                else:
                    continue

                proxy = Proxy(
                    ip=ip,
                    port=int(port),
                    username=username,
                    password=password,
                    protocol=form.protocol.data,
                    enabled=True,
                    added_by=current_user.id
                )
                db.session.add(proxy)
                added += 1
            except Exception as e:
                print(f"Error importing proxy {proxy_line}: {e}")
                continue

        db.session.commit()
        flash(f'Successfully imported {added} proxies')
    return redirect(url_for('manage_proxies'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            # Start a database transaction
            db.session.begin_nested()

            # Create the new user
            user = User(username=form.username.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()  # This will assign the user.id

            # Add default stores for the new user
            from stores import SHOPIFY_STORES
            for store_url in SHOPIFY_STORES:
                store = Store(
                    url=store_url, 
                    enabled=True, 
                    user_id=user.id
                )
                db.session.add(store)

            # Add default keywords for the new user
            from stores import DEFAULT_KEYWORDS
            for word in DEFAULT_KEYWORDS:
                try:
                    keyword = Keyword(
                        word=word, 
                        enabled=True, 
                        user_id=user.id
                    )
                    db.session.add(keyword)
                except Exception as e:
                    print(f"Error adding default keyword {word}: {e}")
                    continue

            # Create default configuration
            config = MonitorConfig(
                rate_limit=1.0,
                monitor_delay=30,
                max_products=250,
                user_id=user.id
            )
            db.session.add(config)

            # Commit all changes
            db.session.commit()
            flash('Registration successful! Please login.')
            return redirect(url_for('login'))

        except Exception as e:
            db.session.rollback()
            flash('Error during registration. Please try again.')
            print(f"Registration error: {e}")
            return redirect(url_for('register'))

    return render_template('register.html', form=form)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Create default admin user if none exists
        if not User.query.first():
            admin = User(username='admin')
            admin.set_password('admin')  # Change this in production
            db.session.add(admin)
            db.session.commit()

        # Populate default stores if none exist
        if not Store.query.first():
            for store_url in SHOPIFY_STORES:
                store = Store(url=store_url, enabled=True, added_by=1, user_id=1)  # admin user id is 1
                db.session.add(store)
            db.session.commit()

        # Populate default keywords if none exist
        if not Keyword.query.first():
            for word in DEFAULT_KEYWORDS:
                keyword = Keyword(word=word, enabled=True, added_by=1, user_id=1)  # admin user id is 1
                db.session.add(keyword)
            db.session.commit()

    app.run(host='0.0.0.0', port=5000)