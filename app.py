import os
import secrets
import logging
from flask import Flask, render_template, redirect, url_for, flash, request, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Store, Keyword, MonitorConfig
from forms import LoginForm, RegistrationForm, StoreForm, KeywordForm, ConfigForm, VariantScraperForm
from discord_webhook import RateLimitedDiscordWebhook
import subprocess
import psutil
import time
from api_routes import api # Import the api blueprint
from requests_oauthlib import OAuth2Session

def is_monitor_running(user_id):
    """Check if a specific user's monitor is running"""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if ('python' in proc.info['name'] and 
                'main.py' in cmdline and 
                f"MONITOR_USER_ID={user_id}" in cmdline):
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24))
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # Initialize Flask extensions
    db.init_app(app)
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except Exception as e:
            print(f"Error loading user {user_id}: {e}")
            return None

    @app.route('/')
    @login_required
    def dashboard():
        try:
            stores = Store.query.filter_by(user_id=current_user.id).all()
            keywords = Keyword.query.filter_by(user_id=current_user.id).all()
            config = MonitorConfig.query.filter_by(user_id=current_user.id).first()
            monitor_running = is_monitor_running(current_user.id)
            return render_template('dashboard.html', 
                                stores=stores, 
                                keywords=keywords, 
                                config=config,
                                monitor_running=monitor_running)
        except Exception as e:
            print(f"Dashboard error: {e}")
            flash('Error loading dashboard. Please try again.')
            return redirect(url_for('login'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        print("Processing login request")  # Debug log
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))

        form = LoginForm()
        if form.validate_on_submit():
            try:
                print(f"Attempting login for user: {form.username.data}")  # Debug log
                user = User.query.filter_by(username=form.username.data).first()

                if user is None:
                    print(f"No user found with username: {form.username.data}")
                    flash('Invalid username or password')
                    return render_template('login.html', form=form)

                print(f"User found: {user.username}, verifying password")  # Debug log
                if user.check_password(form.password.data):
                    print(f"Password verified for user: {user.username}")  # Debug log
                    login_user(user)
                    next_page = request.args.get('next')
                    print(f"Redirecting to: {next_page or 'dashboard'}")  # Debug log
                    return redirect(next_page if next_page else url_for('dashboard'))
                else:
                    print(f"Invalid password for user: {user.username}")  # Debug log
                    flash('Invalid username or password')
            except Exception as e:
                print(f"Login error: {e}")
                db.session.rollback()
                flash('An error occurred during login. Please try again.')

        return render_template('login.html', form=form)

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))

        form = RegistrationForm()
        if form.validate_on_submit():
            try:
                user = User(username=form.username.data)
                user.set_password(form.password.data)
                db.session.add(user)
                db.session.commit()
                print(f"User registered successfully: {user.username}")  # Debug log
                flash('Registration successful! Please login.')
                return redirect(url_for('login'))
            except Exception as e:
                db.session.rollback()
                print(f"Registration error: {e}")
                flash('Error during registration. Please try again.')
                return redirect(url_for('register'))

        return render_template('register.html', form=form)
        

    @app.route('/stores', methods=['GET', 'POST'])
    @login_required
    def manage_stores():
        form = StoreForm()
        if request.method == 'POST' and 'action' in request.form:
            try:
                store_id = request.form.get('store_id')
                store = Store.query.get_or_404(store_id)

                if store.user_id != current_user.id:
                    flash('Access denied', 'error')
                    return redirect(url_for('manage_stores'))

                action = request.form['action']
                if action == 'toggle':
                    store.enabled = not store.enabled
                    db.session.commit()
                    flash(f"Store {'enabled' if store.enabled else 'disabled'}")
                elif action == 'delete':
                    db.session.delete(store)
                    db.session.commit()
                    flash('Store deleted')
            except Exception as e:
                db.session.rollback()
                print(f"Error processing store action: {e}")
                flash('Error processing store action. Please try again.', 'error')
            return redirect(url_for('manage_stores'))
        
        elif form.validate_on_submit():
            store = Store(
                url=form.url.data,
                enabled=form.enabled.data,
                user_id=current_user.id
            )
            db.session.add(store)
            db.session.commit()
            flash('Store added successfully')
            return redirect(url_for('manage_stores'))

        stores = Store.query.filter_by(user_id=current_user.id).all()
        return render_template('stores.html', form=form, stores=stores)

    @app.route('/keywords', methods=['GET', 'POST'])
    @login_required
    def manage_keywords():
        form = KeywordForm()
        if request.method == 'POST' and 'action' in request.form:
            try:
                keyword_id = request.form.get('keyword_id')
                keyword = Keyword.query.get_or_404(keyword_id)

                if keyword.user_id != current_user.id:
                    flash('Access denied', 'error')
                    return redirect(url_for('manage_keywords'))

                action = request.form['action']
                if action == 'toggle':
                    keyword.enabled = not keyword.enabled
                    db.session.commit()
                    flash(f"Keyword {'enabled' if keyword.enabled else 'disabled'}")
                elif action == 'delete':
                    db.session.delete(keyword)
                    db.session.commit()
                    flash('Keyword deleted')
            except Exception as e:
                db.session.rollback()
                print(f"Error processing keyword action: {e}")
                flash('Error processing keyword action. Please try again.', 'error')
            return redirect(url_for('manage_keywords'))

        elif form.validate_on_submit():
            try:
                existing = Keyword.query.filter_by(
                    word=form.word.data,
                    user_id=current_user.id
                ).first()

                if existing:
                    flash('This keyword already exists in your list.')
                    return redirect(url_for('manage_keywords'))

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
                print(f"Error adding keyword: {e}")
                flash('Error adding keyword. Please try again.', 'error')

        keywords = Keyword.query.filter_by(user_id=current_user.id).all()
        return render_template('keywords.html', form=form, keywords=keywords)

    @app.route('/config', methods=['GET', 'POST'])
    @login_required
    def manage_config():
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

            if is_monitor_running(current_user.id):
                subprocess.Popen(['python', 'main.py', f"MONITOR_USER_ID={current_user.id}"])
                flash('Monitor restarted with new configuration')

            return redirect(url_for('dashboard'))

        form.discord_webhook_url.data = current_user.discord_webhook_url
        return render_template('config.html', form=form)

    @app.route('/variants', methods=['GET', 'POST'])
    @login_required
    def variant_scraper():
        form = VariantScraperForm()
        variants = None
        cart_url = None

        if form.validate_on_submit():
            try:
                from shopify_monitor import ShopifyMonitor
                monitor = ShopifyMonitor()
                product_url = form.product_url.data

                # Input validation
                if not product_url:
                    flash('Please enter a valid product URL', 'error')
                    return render_template('variants.html', form=form)

                # Ensure URL has protocol
                if not product_url.lower().startswith(('http://', 'https://')):
                    product_url = 'https://' + product_url

                # Extract domain for cart URL
                from urllib.parse import urlparse
                parsed_url = urlparse(product_url)
                cart_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

                # Get variants
                variants_data = monitor.get_product_variants(product_url)
                variants = variants_data.get('variants', [])

                if not variants:
                    flash('No variants found or error accessing product data', 'warning')
            except Exception as e:
                flash(f'Error scraping variants: {str(e)}', 'error')
                print(f"Error in variant scraper: {e}")

        return render_template('variants.html', form=form, variants=variants, cart_url=cart_url)

    @app.route('/toggle_monitor', methods=['POST'])
    @login_required
    def toggle_monitor():
        try:
            config = MonitorConfig.query.filter_by(user_id=current_user.id).first()
            if not config:
                flash('Please configure monitor settings first', 'error')
                return redirect(url_for('manage_config'))

            if not current_user.discord_webhook_url:
                flash('Please configure Discord webhook URL first', 'error')
                return redirect(url_for('manage_config'))

            if is_monitor_running(current_user.id):
                # Stop only this user's monitor
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        cmdline = ' '.join(proc.info['cmdline'] or [])
                        if ('python' in proc.info['name'] and 
                            'main.py' in cmdline and 
                            f"MONITOR_USER_ID={current_user.id}" in cmdline):
                            process = psutil.Process(proc.info['pid'])
                            process.terminate()
                            try:
                                process.wait(timeout=3)
                            except psutil.TimeoutExpired:
                                process.kill()
                            flash('Monitor stopped successfully')
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            else:
                # Start a new monitor process for this user
                env = os.environ.copy()
                env['DISCORD_WEBHOOK_URL'] = current_user.discord_webhook_url
                env['MONITOR_USER_ID'] = str(current_user.id)  # Set environment variable explicitly

                # Use start_new_session to ensure the monitor runs independently
                process = subprocess.Popen(
                    ['python', 'start_monitor.py', str(current_user.id)],
                    env=env,
                    start_new_session=True
                )

                time.sleep(1)  # Brief pause to allow process to start
                if is_monitor_running(current_user.id):
                    flash('Monitor started successfully')
                else:
                    flash('Failed to start monitor. Check logs for details.', 'error')

            return redirect(url_for('dashboard'))
        except Exception as e:
            print(f"Error in toggle_monitor: {e}")
            flash(f'Error toggling monitor: {str(e)}', 'error')
            return redirect(url_for('dashboard'))

    # Discord OAuth2 configuration
    app.config['DISCORD_CLIENT_ID'] = os.environ.get('DISCORD_CLIENT_ID')
    app.config['DISCORD_CLIENT_SECRET'] = os.environ.get('DISCORD_CLIENT_SECRET')
    app.config['DISCORD_BOT_TOKEN'] = os.environ.get('DISCORD_BOT_TOKEN')

    # Set environment based on REPL_SLUG presence
    is_development = not bool(os.environ.get('REPL_SLUG'))
    os.environ['FLASK_ENV'] = 'development' if is_development else 'production'

    # Set redirect URI based on environment
    if is_development:
        app.config['DISCORD_REDIRECT_URI'] = 'http://localhost:5000/oauth-callback'
        logging.info('Running in development mode with local redirect URI')
    else:
        app.config['DISCORD_REDIRECT_URI'] = f'https://{os.environ.get("REPL_SLUG")}.{os.environ.get("REPL_OWNER")}.repl.dev/oauth-callback'
        logging.info('Running in production mode with Replit redirect URI')

    logging.info(f'Configured Discord redirect URI: {app.config["DISCORD_REDIRECT_URI"]}')

    DISCORD_AUTHORIZATION_BASE_URL = 'https://discord.com/api/oauth2/authorize'
    DISCORD_TOKEN_URL = 'https://discord.com/api/oauth2/token'

    @app.route('/discord-login')
    def discord_login():
        discord = OAuth2Session(
            app.config['DISCORD_CLIENT_ID'],
            redirect_uri=app.config['DISCORD_REDIRECT_URI'],
            scope=['identify']
        )
        authorization_url, state = discord.authorization_url(DISCORD_AUTHORIZATION_BASE_URL)
        session['oauth2_state'] = state
        return render_template('discord_login.html', auth_url=authorization_url)

    @app.route('/oauth-callback')
    def oauth_callback():
        try:
            discord = OAuth2Session(
                app.config['DISCORD_CLIENT_ID'],
                redirect_uri=app.config['DISCORD_REDIRECT_URI'],
                state=session.get('oauth2_state')
            )
            token = discord.fetch_token(
                DISCORD_TOKEN_URL,
                client_secret=app.config['DISCORD_CLIENT_SECRET'],
                authorization_response=request.url
            )

            # Get user info from Discord
            discord_user = discord.get('https://discord.com/api/users/@me').json()
            discord_user_id = discord_user['id']

            # Find or create user
            user = User.query.filter_by(discord_user_id=discord_user_id).first()
            if not user:
                # Create new user with Discord info
                username = f"{discord_user['username']}#{discord_user['discriminator']}"
                user = User(
                    username=username,
                    discord_user_id=discord_user_id,
                    enabled=True
                )
                # Set a random password since we won't use it
                user.set_password(secrets.token_urlsafe(32))
                db.session.add(user)
                db.session.commit()

            login_user(user)
            flash('Successfully logged in with Discord!')
            return redirect(url_for('dashboard'))

        except Exception as e:
            logging.error(f"OAuth callback error: {e}")
            flash('Failed to log in with Discord. Please try again.')
            return redirect(url_for('discord_login'))

    # Register the API blueprint
    app.register_blueprint(api, url_prefix='/api')

    return app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)