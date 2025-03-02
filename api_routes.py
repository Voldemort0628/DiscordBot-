from flask import Blueprint, jsonify, request
from models import db, User, Keyword
from flask_login import current_user
import logging
import hmac
import hashlib
import os

api = Blueprint('api', __name__)

def verify_bot_request():
    """Verify that the request is coming from our Discord bot"""
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return False
    expected_key = os.getenv('MONITOR_API_KEY')
    return hmac.compare_digest(api_key, expected_key)

@api.before_request
def verify_request():
    if not verify_bot_request():
        return jsonify({'error': 'Unauthorized'}), 401

@api.route('/status', methods=['GET'])
def get_status():
    try:
        user_id = request.args.get('user_id', type=int)
        if not user_id:
            return jsonify({'error': 'User ID required'}), 400
            
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
            
        return jsonify({
            'running': user.enabled,
            'user_id': user.id
        })
    except Exception as e:
        logging.error(f"Error in status endpoint: {e}")
        return jsonify({'error': 'Internal server error'}), 500

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
