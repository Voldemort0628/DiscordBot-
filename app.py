import asyncio
import sys
import os
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Store, Keyword, MonitorConfig
from forms import LoginForm, RegistrationForm, StoreForm, KeywordForm, ConfigForm
from discord_webhook import DiscordWebhook
import subprocess
import psutil
import time

def is_monitor_running(user_id):
    """Check if a specific user's monitor is running"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if ('python' in proc.info['name'] and 
                'main.py' in cmdline and 
                f"MONITOR_USER_ID={user_id}" in cmdline):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

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

@app.route('/')
@login_required
def dashboard():
    stores = Store.query.filter_by(user_id=current_user.id).all()
    keywords = Keyword.query.filter_by(user_id=current_user.id).all()
    config = MonitorConfig.query.filter_by(user_id=current_user.id).first()
    monitor_running = is_monitor_running(current_user.id)
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

    # Handle keyword actions (toggle/delete)
    if request.method == 'POST' and 'action' in request.form:
        try:
            keyword_id = request.form.get('keyword_id')
            if not keyword_id:
                flash('Invalid keyword ID', 'error')
                return redirect(url_for('manage_keywords'))

            keyword = Keyword.query.get_or_404(keyword_id)

            # Verify ownership
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

    # Handle new keyword creation
    elif form.validate_on_submit():
        try:
            # Check for duplicate
            existing = Keyword.query.filter_by(
                word=form.word.data,
                user_id=current_user.id
            ).first()

            if existing:
                flash('This keyword already exists in your list.')
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
            print(f"Error adding keyword: {e}")
            flash('Error adding keyword. Please try again.', 'error')

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
        if is_monitor_running(current_user.id):
            subprocess.Popen(['python', 'main.py', f"MONITOR_USER_ID={current_user.id}"])
            flash('Monitor restarted with new configuration')

        return redirect(url_for('dashboard'))

    # Pre-populate Discord webhook URL from user model
    form.discord_webhook_url.data = current_user.discord_webhook_url
    return render_template('config.html', form=form)


@app.route('/toggle_monitor', methods=['POST'])
@login_required
def toggle_monitor():
    try:
        # Check configuration first
        config = MonitorConfig.query.filter_by(user_id=current_user.id).first()
        if not config:
            flash('Please configure monitor settings first', 'error')
            return redirect(url_for('manage_config'))

        if not current_user.discord_webhook_url:
            flash('Please configure Discord webhook URL first', 'error')
            return redirect(url_for('manage_config'))

        # Check if this user's monitor is running
        if is_monitor_running(current_user.id):
            # Stop only this user's monitor
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    if ('python' in proc.info['name'] and 
                        'main.py' in cmdline and 
                        f"MONITOR_USER_ID={current_user.id}" in cmdline):
                        process = psutil.Process(proc.info['pid'])
                        process.kill()  # Use kill for immediate termination
                        time.sleep(0.5)  # Brief pause to ensure process is gone
                        flash('Monitor stopped successfully')
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    print(f"Error terminating process for user {current_user.id}: {e}")
        else:
            # Start a new monitor process for this user
            env = os.environ.copy()
            env['MONITOR_USER_ID'] = str(current_user.id)
            env['DISCORD_WEBHOOK_URL'] = current_user.discord_webhook_url

            # Use command line argument for better process identification
            cmd = ['python', 'main.py', f"MONITOR_USER_ID={current_user.id}"]
            subprocess.Popen(cmd, env=env)
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
        if not User.query.first():
            admin = User(username='admin')
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()

    # Get port from environment or use default
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)