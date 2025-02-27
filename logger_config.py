import logging
import logging.handlers
import os
from datetime import datetime
import json
from typing import Dict, Any

# Create logs directory if it doesn't exist
if not os.path.exists('logs'):
    os.makedirs('logs')

# Configure base logging format
base_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Configure JSON formatter for structured logging
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj: Dict[str, Any] = {
            'timestamp': datetime.utcfromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
            
        # Add extra fields
        if hasattr(record, 'extra_fields'):
            log_obj.update(record.extra_fields)
            
        return json.dumps(log_obj)

def setup_logger(name: str, log_file: str = None, level=logging.INFO) -> logging.Logger:
    """Setup a new logger instance with both console and file handlers"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Remove existing handlers to prevent duplicates
    logger.handlers = []
    
    # Console handler with basic formatting
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(base_formatter)
    logger.addHandler(console_handler)
    
    if log_file:
        # File handler with JSON formatting and rotation
        file_handler = logging.handlers.RotatingFileHandler(
            f'logs/{log_file}',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)
    
    return logger

# Setup main loggers
monitor_logger = setup_logger('monitor', 'monitor.log')
scraper_logger = setup_logger('scraper', 'scraper.log')
webhook_logger = setup_logger('webhook', 'webhook.log')
process_logger = setup_logger('process', 'process.log')

def log_error(logger: logging.Logger, error: Exception, context: Dict[str, Any] = None):
    """Enhanced error logging with context"""
    extra = {
        'extra_fields': {
            'error_type': error.__class__.__name__,
            'error_details': str(error),
            **(context or {})
        }
    }
    logger.error(f"Error occurred: {str(error)}", extra=extra, exc_info=True)

def log_scraping_error(url: str, error: Exception, context: Dict[str, Any] = None):
    """Specialized logging for scraping errors"""
    extra_context = {
        'url': url,
        'timestamp': datetime.utcnow().isoformat(),
        **(context or {})
    }
    log_error(scraper_logger, error, extra_context)

def log_webhook_error(webhook_url: str, error: Exception, context: Dict[str, Any] = None):
    """Specialized logging for webhook errors"""
    extra_context = {
        'webhook_url': webhook_url,
        'timestamp': datetime.utcnow().isoformat(),
        **(context or {})
    }
    log_error(webhook_logger, error, extra_context)
