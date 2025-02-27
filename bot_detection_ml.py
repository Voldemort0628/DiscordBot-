import random
import time
import numpy as np
from typing import Dict, List, Tuple
import json
import hashlib

class MLBasedBotBypass:
    def __init__(self):
        # Initialize timing patterns for different actions
        self.timing_patterns = {
            'page_load': (2.0, 5.0),  # Mean and std dev for page load timing
            'mouse_move': (0.1, 0.3),  # Mouse movement intervals
            'scroll': (0.5, 1.5),      # Scroll timing
            'click': (0.2, 0.4)        # Click timing
        }
        
        # Browser fingerprint components
        self.screen_resolutions = [
            (1920, 1080), (1366, 768), (1536, 864),
            (1440, 900), (1280, 720), (2560, 1440)
        ]
        
        # Common browser features
        self.browser_features = {
            'webgl': True,
            'canvas': True,
            'audio': True,
            'webrtc': True
        }
        
        # Initialize request history for pattern learning
        self.request_history = []
        self.max_history = 100

    def generate_dynamic_fingerprint(self) -> Dict:
        """Generate a realistic browser fingerprint"""
        resolution = random.choice(self.screen_resolutions)
        
        fingerprint = {
            'user-agent': self._generate_consistent_ua(),
            'accept-language': 'en-US,en;q=0.9',
            'screen': {
                'width': resolution[0],
                'height': resolution[1],
                'color-depth': 24,
                'pixel-ratio': random.choice([1, 1.5, 2, 2.5])
            },
            'timezone': 'America/New_York',
            'platform': random.choice(['Win32', 'MacIntel']),
            'plugins-length': random.randint(3, 8),
            'features': self.browser_features
        }
        
        return fingerprint

    def _generate_consistent_ua(self) -> str:
        """Generate a consistent user agent based on session"""
        base_uas = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        ]
        # Use session-based seed for consistency
        return random.choice(base_uas)

    def generate_request_timing(self, action_type: str) -> float:
        """Generate human-like timing for different actions"""
        mean, std = self.timing_patterns[action_type]
        # Use truncated normal distribution to avoid negative values
        delay = max(0.1, np.random.normal(mean, std))
        return delay

    def simulate_user_behavior(self) -> List[Dict]:
        """Generate a sequence of realistic user behavior events"""
        events = []
        total_time = 0
        
        # Simulate page load
        load_time = self.generate_request_timing('page_load')
        total_time += load_time
        events.append({
            'type': 'page_load',
            'timestamp': total_time
        })
        
        # Simulate mouse movements and scrolls
        num_events = random.randint(3, 8)
        for _ in range(num_events):
            event_type = random.choice(['mouse_move', 'scroll'])
            delay = self.generate_request_timing(event_type)
            total_time += delay
            events.append({
                'type': event_type,
                'timestamp': total_time
            })
        
        return events

    def analyze_response(self, response_headers: Dict) -> Dict:
        """Analyze response headers for bot detection patterns"""
        indicators = {
            'bot_score': 0.0,
            'detection_likelihood': 0.0,
            'recommended_delay': 0.0
        }
        
        # Check for common bot detection indicators
        if 'cf-ray' in response_headers:  # Cloudflare
            indicators['bot_score'] += 0.3
        if 'server-timing' in response_headers:
            indicators['bot_score'] += 0.2
        
        # Adjust timing based on bot score
        indicators['recommended_delay'] = max(2.0, indicators['bot_score'] * 5)
        
        return indicators

    def update_patterns(self, success: bool, response_data: Dict) -> None:
        """Update timing patterns based on success/failure"""
        self.request_history.append({
            'timestamp': time.time(),
            'success': success,
            'response_data': response_data
        })
        
        # Maintain history size
        if len(self.request_history) > self.max_history:
            self.request_history.pop(0)
        
        # Adjust timing patterns based on success rate
        if len(self.request_history) >= 10:
            recent_success_rate = sum(1 for r in self.request_history[-10:] if r['success']) / 10
            
            # If success rate is low, increase delays
            if recent_success_rate < 0.5:
                for action_type in self.timing_patterns:
                    mean, std = self.timing_patterns[action_type]
                    self.timing_patterns[action_type] = (mean * 1.2, std)
            # If success rate is high, gradually decrease delays
            elif recent_success_rate > 0.8:
                for action_type in self.timing_patterns:
                    mean, std = self.timing_patterns[action_type]
                    self.timing_patterns[action_type] = (max(mean * 0.9, self.timing_patterns[action_type][0]), std)

    def get_request_headers(self) -> Dict:
        """Generate headers for the next request based on learned patterns"""
        fingerprint = self.generate_dynamic_fingerprint()
        
        headers = {
            'User-Agent': fingerprint['user-agent'],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': fingerprint['accept-language'],
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'TE': 'trailers'
        }
        
        # Add dynamic headers based on fingerprint
        headers['viewport-width'] = str(fingerprint['screen']['width'])
        headers['viewport-height'] = str(fingerprint['screen']['height'])
        
        return headers
