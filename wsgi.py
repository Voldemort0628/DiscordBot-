import os
import sys
from app import create_app
from models import db, User
from werkzeug.security import generate_password_hash
from process_manager import ProcessManager
import time
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def init_database(app):
    """Initialize database and create admin user if needed"""
    try:
        with app.app_context():
            # Create all tables
            db.create_all()

            # Only create admin if no users exist
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                logger.info("Creating default admin user...")
                admin = User(username='admin')
                admin.password_hash = generate_password_hash('admin')  # Direct hash set for initial user
                db.session.add(admin)
                try:
                    db.session.commit()
                    logger.info("Created default admin user")
                except Exception as e:
                    logger.error(f"Error creating admin user: {e}")
                    db.session.rollback()
                    return False
            return True
    except Exception as e:
        logger.error(f"Database initialization error: {e}", exc_info=True)
        return False

def main():
    try:
        # Initialize process manager and cleanup
        logger.info("Initializing process manager...")
        ProcessManager.register_shutdown_handler()

        # Clean up existing processes on port 5000
        cleanup_attempts = 3
        for attempt in range(cleanup_attempts):
            if ProcessManager.cleanup_port():
                break
            logger.warning(f"Cleanup attempt {attempt + 1}/{cleanup_attempts} failed, retrying...")
            time.sleep(2)
        else:
            logger.error("Error: Could not clean up port 5000 after multiple attempts")
            return None

        # Double check port availability with increased timeout
        if not ProcessManager.wait_for_port_available(timeout=45):
            logger.error("Error: Port 5000 is still in use after cleanup")
            sys.exit(1)

        # Create the Flask app
        logger.info("Creating Flask application...")
        app = create_app()

        # Initialize database
        if not init_database(app):
            logger.error("Failed to initialize database")
            sys.exit(1)

        return app

    except Exception as e:
        logger.error(f"Failed to initialize application: {e}", exc_info=True)
        sys.exit(1)

app = main()

if __name__ == '__main__':
    if app:
        app.run(host='0.0.0.0', port=5000)
    else:
        logger.error("Error: Application failed to initialize properly")
        sys.exit(1)