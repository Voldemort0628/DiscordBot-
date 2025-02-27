from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Store(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(200), unique=True, nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'))

class Keyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(100), unique=True, nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'))

class MonitorConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # Add user association
    rate_limit = db.Column(db.Float, default=1.0)
    monitor_delay = db.Column(db.Integer, default=30)
    max_products = db.Column(db.Integer, default=250)
    discord_webhook_url = db.Column(db.String(500))

class RetailScraper(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    retailer = db.Column(db.String(50), nullable=False)
    keyword = db.Column(db.String(100), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    last_check = db.Column(db.DateTime)
    check_frequency = db.Column(db.Integer, default=3600)
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'))

class Proxy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(45), nullable=False)  # IPv6 support
    port = db.Column(db.Integer, nullable=False)
    username = db.Column(db.String(100))
    password = db.Column(db.String(100))
    protocol = db.Column(db.String(10), default='http')  # http, https, socks5
    country = db.Column(db.String(2))  # ISO country code
    last_used = db.Column(db.DateTime)
    success_count = db.Column(db.Integer, default=0)
    failure_count = db.Column(db.Integer, default=0)
    enabled = db.Column(db.Boolean, default=True)
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'))