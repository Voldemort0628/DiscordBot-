from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    discord_webhook_url = db.Column(db.String(500))
    discord_user_id = db.Column(db.String(20))  # Added to store Discord user ID
    enabled = db.Column(db.Boolean, default=True)

    # Relationships
    stores = db.relationship('Store', backref='user', lazy=True)
    keywords = db.relationship('Keyword', backref='user', lazy=True)
    scrapers = db.relationship('RetailScraper', backref='user', lazy=True)
    proxies = db.relationship('Proxy', backref='user', lazy=True)

    def set_password(self, password):
        if not password:
            raise ValueError("Password cannot be empty")
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not password or not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

class Store(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(200), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Keyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(100), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('word', 'user_id', name='uix_keyword_word_user'),
    )

class MonitorConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rate_limit = db.Column(db.Float, default=1.0)
    monitor_delay = db.Column(db.Integer, default=30)
    max_products = db.Column(db.Integer, default=250)
    # New configurable parameters
    min_cycle_delay = db.Column(db.Float, default=0.05)  # Minimum delay between cycles
    success_delay_multiplier = db.Column(db.Float, default=0.25)  # Delay multiplier when products found
    batch_size = db.Column(db.Integer, default=20)  # Number of stores to process in parallel
    initial_product_limit = db.Column(db.Integer, default=150)  # Initial number of products to fetch
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class RetailScraper(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    retailer = db.Column(db.String(50), nullable=False)
    keyword = db.Column(db.String(100), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    last_check = db.Column(db.DateTime)
    check_frequency = db.Column(db.Integer, default=3600)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Proxy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(45), nullable=False)
    port = db.Column(db.Integer, nullable=False)
    username = db.Column(db.String(100))
    password = db.Column(db.String(100))
    protocol = db.Column(db.String(10), default='http')
    country = db.Column(db.String(2))
    last_used = db.Column(db.DateTime)
    success_count = db.Column(db.Integer, default=0)
    failure_count = db.Column(db.Integer, default=0)
    enabled = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)