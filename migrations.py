from flask_migrate import Migrate, init, migrate, upgrade
from app import create_app
from models import db

def init_migrations():
    """Initialize migrations directory"""
    app = create_app()
    Migrate(app, db)
    with app.app_context():
        init()  # Create migrations directory
        migrate()  # Create initial migration
        upgrade()  # Apply migration

if __name__ == '__main__':
    init_migrations()