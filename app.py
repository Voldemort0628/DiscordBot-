from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Store, Keyword, MonitorConfig
from forms import LoginForm, StoreForm, KeywordForm, ConfigForm
from stores import SHOPIFY_STORES, DEFAULT_KEYWORDS
import os

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
    stores = Store.query.all()
    keywords = Keyword.query.all()
    config = MonitorConfig.query.first()
    return render_template('dashboard.html', stores=stores, keywords=keywords, config=config)

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
        store = Store(url=form.url.data, enabled=form.enabled.data, added_by=current_user.id)
        db.session.add(store)
        db.session.commit()
        flash('Store added successfully')
        return redirect(url_for('manage_stores'))
    stores = Store.query.all()
    return render_template('stores.html', form=form, stores=stores)

@app.route('/keywords', methods=['GET', 'POST'])
@login_required
def manage_keywords():
    form = KeywordForm()
    if form.validate_on_submit():
        keyword = Keyword(word=form.word.data, enabled=form.enabled.data, added_by=current_user.id)
        db.session.add(keyword)
        db.session.commit()
        flash('Keyword added successfully')
        return redirect(url_for('manage_keywords'))
    keywords = Keyword.query.all()
    return render_template('keywords.html', form=form, keywords=keywords)

@app.route('/config', methods=['GET', 'POST'])
@login_required
def manage_config():
    config = MonitorConfig.query.first()
    if not config:
        config = MonitorConfig()
        db.session.add(config)
        db.session.commit()

    form = ConfigForm(obj=config)
    if form.validate_on_submit():
        form.populate_obj(config)
        db.session.commit()
        flash('Configuration updated successfully')
        return redirect(url_for('dashboard'))
    return render_template('config.html', form=form)

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
                store = Store(url=store_url, enabled=True, added_by=1)  # admin user id is 1
                db.session.add(store)
            db.session.commit()

        # Populate default keywords if none exist
        if not Keyword.query.first():
            for word in DEFAULT_KEYWORDS:
                keyword = Keyword(word=word, enabled=True, added_by=1)  # admin user id is 1
                db.session.add(keyword)
            db.session.commit()

    app.run(host='0.0.0.0', port=5000)