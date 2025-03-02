import os
from flask import Blueprint, jsonify, request
from models import db, User, Keyword, MonitorConfig
from flask_login import current_user
import logging
import hmac
import hashlib

api = Blueprint('api', __name__)

def verify_bot_request():
    """Verify that the request is coming from our Discord bot"""
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return False
    expected_key = os.getenv('MONITOR_API_KEY')
    return hmac.compare_digest(str(api_key), str(expected_key))

@api.before_request
def verify_request():
    if not verify_bot_request():
        return jsonify({'error': 'Unauthorized'}), 401

@api.route('/status', methods=['GET'])
def get_status():
    try:
        user_id = request.args.get('user_id', type=int)
        discord_user_id = request.args.get('discord_user_id', type=str)

        if not discord_user_id:
            logging.error("Status request missing discord_user_id")
            return jsonify({'error': 'Discord user ID required'}), 400

        # First try to find user by Discord ID
        user = User.query.filter_by(discord_user_id=discord_user_id).first()

        if not user:
            logging.error(f"Status request for unregistered Discord user {discord_user_id}")
            return jsonify({'error': 'Your Discord account is not registered with the monitor'}), 404

        # Check if monitor is running using app.py's is_monitor_running function
        from app import is_monitor_running
        is_running = is_monitor_running(user.id)

        logging.info(f"Status request for user {user.id}: running={is_running}")
        return jsonify({
            'running': is_running,
            'user_id': user.id,
            'username': user.username
        })
    except Exception as e:
        logging.error(f"Error in status endpoint: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@api.route('/link_discord', methods=['POST'])
def link_discord_account():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        discord_user_id = data.get('discord_user_id')

        if not all([username, password, discord_user_id]):
            return jsonify({'error': 'Missing required fields'}), 400

        # Check if user already exists with this Discord ID
        user = User.query.filter_by(discord_user_id=discord_user_id).first()

        if user:
            return jsonify({
                'message': 'Discord account already linked',
                'user_id': user.id,
                'username': user.username
            })

        # Create new user
        user = User(
            username=username,
            discord_user_id=discord_user_id,
            enabled=True
        )
        user.set_password(password)

        # First commit the user to get an ID
        db.session.add(user)
        db.session.commit()

        # Now create the monitor config with the user's ID
        config = MonitorConfig(
            user_id=user.id,
            rate_limit=1.0,
            monitor_delay=30,
            max_products=250,
            min_cycle_delay=0.05,
            success_delay_multiplier=0.25,
            batch_size=20,
            initial_product_limit=150
        )
        db.session.add(config)
        db.session.commit()

        logging.info(f"Successfully created user {username} with Discord ID {discord_user_id}")

        return jsonify({
            'message': 'Discord account linked successfully',
            'user_id': user.id,
            'username': user.username
        })
    except Exception as e:
        logging.error(f"Error linking Discord account: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@api.route('/start', methods=['POST'])
def start_monitor():
    try:
        user_id = request.json.get('user_id')
        if not user_id:
            return jsonify({'error': 'User ID required'}), 400

        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        user.enabled = True
        db.session.commit()
        return jsonify({'message': 'Monitor started'})
    except Exception as e:
        logging.error(f"Error starting monitor: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@api.route('/stop', methods=['POST'])
def stop_monitor():
    try:
        user_id = request.json.get('user_id')
        if not user_id:
            return jsonify({'error': 'User ID required'}), 400

        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        user.enabled = False
        db.session.commit()
        return jsonify({'message': 'Monitor stopped'})
    except Exception as e:
        logging.error(f"Error stopping monitor: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@api.route('/keywords', methods=['GET'])
def get_keywords():
    try:
        user_id = request.args.get('user_id', type=int)
        if not user_id:
            return jsonify({'error': 'User ID required'}), 400

        keywords = Keyword.query.filter_by(user_id=user_id).all()
        return jsonify({
            'keywords': [
                {'word': k.word, 'enabled': k.enabled}
                for k in keywords
            ]
        })
    except Exception as e:
        logging.error(f"Error fetching keywords: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@api.route('/keywords', methods=['POST'])
def add_keyword():
    try:
        user_id = request.json.get('user_id')
        word = request.json.get('word')

        if not user_id or not word:
            return jsonify({'error': 'User ID and keyword required'}), 400

        keyword = Keyword(word=word, user_id=user_id, enabled=True)
        db.session.add(keyword)
        db.session.commit()
        return jsonify({'message': 'Keyword added'})
    except Exception as e:
        logging.error(f"Error adding keyword: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@api.route('/keywords', methods=['DELETE'])
def remove_keyword():
    try:
        user_id = request.json.get('user_id')
        word = request.json.get('word')

        if not user_id or not word:
            return jsonify({'error': 'User ID and keyword required'}), 400

        keyword = Keyword.query.filter_by(user_id=user_id, word=word).first()
        if keyword:
            db.session.delete(keyword)
            db.session.commit()
            return jsonify({'message': 'Keyword removed'})
        return jsonify({'error': 'Keyword not found'}), 404
    except Exception as e:
        logging.error(f"Error removing keyword: {e}")
        return jsonify({'error': 'Internal server error'}), 500