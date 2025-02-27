from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    discord_webhook_url = db.Column(db.String(500))
    enabled = db.Column(db.Boolean, default=True)

    # Relationships
    stores = db.relationship('Store', backref='user', lazy=True)
    keywords = db.relationship('Keyword', backref='user', lazy=True)
    scrapers = db.relationship('RetailScraper', backref='user', lazy=True)
    proxy_groups = db.relationship('ProxyGroup', backref='user', lazy=True)

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
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class RetailScraper(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    retailer = db.Column(db.String(50), nullable=False)
    keyword = db.Column(db.String(100), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    last_check = db.Column(db.DateTime)
    check_frequency = db.Column(db.Integer, default=3600)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class ProxyGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Relationships
    proxy_lists = db.relationship('ProxyList', backref='group', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('name', 'user_id', name='uix_proxygroup_name_user'),
    )

class ProxyList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    enabled = db.Column(db.Boolean, default=True)
    group_id = db.Column(db.Integer, db.ForeignKey('proxy_group.id'), nullable=False)

    # Relationships
    proxies = db.relationship('Proxy', backref='list', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('name', 'group_id', name='uix_proxylist_name_group'),
    )

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
    list_id = db.Column(db.Integer, db.ForeignKey('proxy_list.id'), nullable=False)