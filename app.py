import os
import asyncio
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Store, Keyword, MonitorConfig
from forms import LoginForm, RegistrationForm, StoreForm, KeywordForm, ConfigForm
import requests
from datetime import datetime
from discord_webhook import DiscordWebhook

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Configure monitor service URL based on environment
REPLIT_SLUG = os.environ.get('REPL_SLUG')
REPLIT_OWNER = os.environ.get('REPL_OWNER')
if REPLIT_SLUG and REPLIT_OWNER:
    # In production, use the monitor subdomain
    MONITOR_SERVICE_URL = f"https://{REPLIT_SLUG}-3000.{REPLIT_OWNER}.repl.co"
else:
    MONITOR_SERVICE_URL = "http://localhost:3000"

print(f"Monitor service URL: {MONITOR_SERVICE_URL}")  # Debug log

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def is_monitor_running():
    """Check if the monitor is running for the current user"""
    try:
        status_url = f"{MONITOR_SERVICE_URL}/status/{current_user.id}"
        print(f"Checking monitor status at: {status_url}")  # Debug log
        response = requests.get(status_url, timeout=5)
        if response.status_code == 200:
            status = response.json().get('status') == 'running'
            print(f"Monitor status: {status}")  # Debug log
            return status
        print(f"Status check failed with code: {response.status_code}")
        return False
    except Exception as e:
        print(f"Error checking monitor status: {e}")
        return False

@app.route('/toggle_monitor', methods=['POST'])
@login_required
def toggle_monitor():
    """Toggle monitor for the current user"""
    action = 'start' if not is_monitor_running() else 'stop'
    try:
        monitor_url = f"{MONITOR_SERVICE_URL}/{action}_monitor/{current_user.id}"
        print(f"Sending monitor {action} request to: {monitor_url}")  # Debug log
        response = requests.get(monitor_url, timeout=5)
        response.raise_for_status()
        flash(f'Monitor {action}ed successfully')
    except requests.exceptions.RequestException as e:
        error_msg = f'Error toggling monitor: {str(e)}'
        print(error_msg)  # Debug log
        flash(error_msg, 'error')
    return redirect(url_for('dashboard'))

@app.route('/')
@login_required
def dashboard():
    # Ensure user has config
    config = MonitorConfig.query.filter_by(user_id=current_user.id).first()
    if not config:
        config = MonitorConfig(
            user_id=current_user.id,
            rate_limit=1.0,
            monitor_delay=30,
            max_products=250
        )
        db.session.add(config)
        db.session.commit()

    # Get user's stores and keywords
    stores = Store.query.filter_by(added_by=current_user.id).all()
    keywords = Keyword.query.filter_by(added_by=current_user.id).all()

    # Debug logging
    print(f"User {current_user.id} has {len(stores)} stores and {len(keywords)} keywords")

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
    # Stop the user's monitor if it's running
    if is_monitor_running():
        try:
            requests.get(f"{MONITOR_SERVICE_URL}/stop_monitor/{current_user.id}", timeout=5)
        except Exception as e:
            print(f"Error stopping monitor during logout: {e}")
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
            added_by=current_user.id
        )
        db.session.add(store)
        db.session.commit()
        flash('Store added successfully')
        return redirect(url_for('manage_stores'))

    elif request.method == 'POST' and 'action' in request.form:
        store_id = request.form.get('store_id')
        store = Store.query.filter_by(id=store_id, added_by=current_user.id).first()
        if store:
            action = request.form['action']
            if action == 'toggle':
                store.enabled = not store.enabled
                db.session.commit()
                flash(f"Store {'enabled' if store.enabled else 'disabled'}")
            elif action == 'delete':
                db.session.delete(store)
                db.session.commit()
                flash('Store deleted')
        return redirect(url_for('manage_stores'))

    stores = Store.query.filter_by(added_by=current_user.id).all()
    return render_template('stores.html', form=form, stores=stores)

@app.route('/keywords', methods=['GET', 'POST'])
@login_required
def manage_keywords():
    form = KeywordForm()
    if form.validate_on_submit():
        keyword = Keyword(
            word=form.word.data,
            enabled=form.enabled.data,
            added_by=current_user.id
        )
        db.session.add(keyword)
        db.session.commit()
        flash('Keyword added successfully')
        return redirect(url_for('manage_keywords'))

    elif request.method == 'POST' and 'action' in request.form:
        keyword_id = request.form.get('keyword_id')
        keyword = Keyword.query.filter_by(id=keyword_id, added_by=current_user.id).first()
        if keyword:
            action = request.form['action']
            if action == 'toggle':
                keyword.enabled = not keyword.enabled
                db.session.commit()
                flash(f"Keyword {'enabled' if keyword.enabled else 'disabled'}")
            elif action == 'delete':
                db.session.delete(keyword)
                db.session.commit()
                flash('Keyword deleted')
        return redirect(url_for('manage_keywords'))

    keywords = Keyword.query.filter_by(added_by=current_user.id).all()
    return render_template('keywords.html', form=form, keywords=keywords)

@app.route('/config', methods=['GET', 'POST'])
@login_required
def manage_config():
    config = MonitorConfig.query.filter_by(user_id=current_user.id).first()
    form = ConfigForm(obj=config)
    if form.validate_on_submit():
        form.populate_obj(config)
        db.session.commit()
        flash('Configuration updated successfully')
        return redirect(url_for('dashboard'))
    return render_template('config.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        # Create default config for new user
        config = MonitorConfig(
            user_id=user.id,
            rate_limit=1.0,
            monitor_delay=30,
            max_products=250
        )
        db.session.add(config)
        db.session.commit()

        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Create default admin user if none exists
        if not User.query.first():
            admin = User(username='admin')
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()

    # ALWAYS serve the app on port 5000
    app.run(host='0.0.0.0', port=5000)