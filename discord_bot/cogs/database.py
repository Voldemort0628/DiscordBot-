import logging
import secrets
import os
import psycopg2

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('discord_bot.log'),
        logging.StreamHandler()
    ]
)

def verify_discord_user(discord_user_id: str, discord_username: str) -> dict:
    """
    Create or verify a Discord user in the database
    Returns dict with status and message
    """
    try:
        # Connect to database
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        cur = conn.cursor()
        
        # First check if user exists
        cur.execute("""
            SELECT username FROM "user" 
            WHERE discord_user_id = %s;
        """, (discord_user_id,))
        
        result = cur.fetchone()
        if result:
            logging.info(f"Found existing user for Discord ID {discord_user_id}")
            return {
                'success': True,
                'message': 'Account already verified',
                'username': result[0]
            }

        # Create new user
        username = f"discord_{discord_username}"
        
        # Insert new user
        cur.execute("""
            INSERT INTO "user" (username, discord_user_id, enabled)
            VALUES (%s, %s, true)
            RETURNING id;
        """, (username, discord_user_id))
        
        user_id = cur.fetchone()[0]

        # Create monitor config
        cur.execute("""
            INSERT INTO monitor_config (
                user_id, rate_limit, monitor_delay, max_products,
                min_cycle_delay, success_delay_multiplier, batch_size, initial_product_limit
            )
            VALUES (
                %s, 1.0, 30, 250,
                0.05, 0.25, 20, 150
            );
        """, (user_id,))

        conn.commit()
        logging.info(f"Successfully created user {username} with Discord ID {discord_user_id}")

        return {
            'success': True,
            'message': 'Account verified successfully',
            'username': username
        }

    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Error during verification for Discord ID {discord_user_id}: {str(e)}")
        return {
            'success': False,
            'message': f'Error during verification: {str(e)}'
        }
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
