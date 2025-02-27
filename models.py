from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)  # Increased from 120 to 255

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
    rate_limit = db.Column(db.Float, default=1.0)  # requests per second per store
    monitor_delay = db.Column(db.Integer, default=30)  # seconds between checks
    max_products = db.Column(db.Integer, default=250)

class RetailScraper(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    retailer = db.Column(db.String(50), nullable=False)  # 'target', 'walmart', 'bestbuy'
    keyword = db.Column(db.String(100), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    last_check = db.Column(db.DateTime)
    check_frequency = db.Column(db.Integer, default=3600)  # seconds between checks
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'))