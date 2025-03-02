import logging
import secrets
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('discord_bot.log'),
        logging.StreamHandler()
    ]
)

def execute_sql_tool(query):
    # Replace this with your actual SQL execution function
    # This is a placeholder,  replace with your database connection logic.
    #  Example using psycopg2:
    import psycopg2
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute(query)
    results = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()
    return results



def verify_discord_user(discord_user_id: str, discord_username: str) -> dict:
    """
    Create or verify a Discord user in the database
    Returns dict with status and message
    """
    try:
        # First check if user exists
        query = f"""
        SELECT username FROM "user" WHERE discord_user_id = '{discord_user_id}';
        """
        result = execute_sql_tool(query)

        if result and result[0]:
            logging.info(f"Found existing user for Discord ID {discord_user_id}")
            return {
                'success': True,
                'message': 'Account already verified',
                'username': result[0][0]
            }

        # Create new user
        username = f"discord_{discord_username}"
        password = secrets.token_urlsafe(32)

        # Insert new user
        query = f"""
        INSERT INTO "user" (username, discord_user_id, enabled)
        VALUES ('{username}', '{discord_user_id}', true)
        RETURNING id;
        """
        result = execute_sql_tool(query)
        user_id = result[0][0]

        # Create monitor config
        query = f"""
        INSERT INTO monitor_config (
            user_id, rate_limit, monitor_delay, max_products,
            min_cycle_delay, success_delay_multiplier, batch_size, initial_product_limit
        )
        VALUES (
            {user_id}, 1.0, 30, 250,
            0.05, 0.25, 20, 150
        );
        """
        execute_sql_tool(query)

        logging.info(f"Successfully created user {username} with Discord ID {discord_user_id}")

        return {
            'success': True,
            'message': 'Account verified successfully',
            'username': username
        }

    except Exception as e:
        logging.error(f"Error during verification for Discord ID {discord_user_id}: {str(e)}")
        return {
            'success': False,
            'message': f'Error during verification: {str(e)}'
        }