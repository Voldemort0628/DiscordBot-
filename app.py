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

    # Basic Configuration
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', os.urandom(24))
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

                # Use start_new_session to ensure the monitor runs independently
                subprocess.Popen(
                    ['python', 'main.py', f"MONITOR_USER_ID={current_user.id}"],
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

    return app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)