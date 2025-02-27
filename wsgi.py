import os
import sys
from app import create_app
from models import db, User
from werkzeug.security import generate_password_hash
from process_manager import ProcessManager
import time

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

def main():
    try:
        # Initialize process manager and cleanup
        print("Initializing process manager...")
        ProcessManager.register_shutdown_handler()

        # Clean up existing processes on port 5000
        cleanup_attempts = 3
        for attempt in range(cleanup_attempts):
            if ProcessManager.cleanup_port():
                break
            print(f"Cleanup attempt {attempt + 1}/{cleanup_attempts} failed, retrying...")
            time.sleep(2)
        else:
            print("Error: Could not clean up port 5000 after multiple attempts")
            return None

        # Double check port availability with increased timeout
        if not ProcessManager.wait_for_port_available(timeout=45):
            print("Error: Port 5000 is still in use after cleanup")
            sys.exit(1)

        # Create the Flask app
        print("Creating Flask application...")
        app = create_app()

        # Initialize database
        if not init_database(app):
            print("Failed to initialize database")
            sys.exit(1)

        return app

    except Exception as e:
        print(f"Failed to initialize application: {e}", file=sys.stderr)
        sys.exit(1)

app = main()

if __name__ == '__main__':
    if app:
        app.run(host='0.0.0.0', port=5000)
    else:
        print("Error: Application failed to initialize properly")
        sys.exit(1)