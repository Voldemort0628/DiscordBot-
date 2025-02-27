import os
import sys
from app import create_app
from models import db, User
from werkzeug.security import generate_password_hash

def init_database(app):
    """Initialize database and create admin user if needed"""
    try:
        with app.app_context():
            # Create all tables
            db.create_all()

            # Only create admin if no users exist
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                print("Creating default admin user...")
                admin = User(username='admin')
                admin.password_hash = generate_password_hash('admin')  # Direct hash set for initial user
                db.session.add(admin)
                try:
                    db.session.commit()
                    print("Created default admin user")
                except Exception as e:
                    print(f"Error creating admin user: {e}")
                    db.session.rollback()
                    return False
            return True
    except Exception as e:
        print(f"Database initialization error: {e}", file=sys.stderr)
        return False

# Create the Flask app
app = create_app()

# Initialize database
if not init_database(app):
    print("Failed to initialize database")
    sys.exit(1)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)