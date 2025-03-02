import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
import secrets
import sys

# Add the root directory to the Python path to allow importing models
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)

from models import User, MonitorConfig, db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Get database URL from environment
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL must be set")

# Create database engine
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

def verify_discord_user(discord_user_id: str, discord_username: str) -> dict:
    """
    Create or verify a Discord user in the database
    Returns dict with status and message
    """
    session = Session()
    try:
        # Check if user already exists
        existing_user = session.query(User).filter_by(discord_user_id=discord_user_id).first()
        if existing_user:
            logging.info(f"Found existing user for Discord ID {discord_user_id}")
            return {
                'success': True,
                'message': 'Account already verified',
                'username': existing_user.username
            }

        # Create new user
        username = f"discord_{discord_username}"
        password = secrets.token_urlsafe(32)

        new_user = User(
            username=username,
            discord_user_id=discord_user_id,
            enabled=True
        )
        new_user.set_password(password)

        # First commit the user to get ID
        session.add(new_user)
        session.flush()

        # Create default monitor config
        config = MonitorConfig(
            user_id=new_user.id,
            rate_limit=1.0,
            monitor_delay=30,
            max_products=250,
            min_cycle_delay=0.05,
            success_delay_multiplier=0.25,
            batch_size=20,
            initial_product_limit=150
        )

        session.add(config)
        session.commit()

        logging.info(f"Successfully created new user {username} with Discord ID {discord_user_id}")

        return {
            'success': True,
            'message': 'Account verified successfully',
            'username': username
        }

    except Exception as e:
        session.rollback()
        logging.error(f"Error during verification for Discord ID {discord_user_id}: {str(e)}")
        return {
            'success': False,
            'message': f'Error during verification: {str(e)}'
        }
    finally:
        session.close()