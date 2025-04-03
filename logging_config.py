# logging_config.py

import os
import logging
from logging.handlers import RotatingFileHandler
import json
from datetime import datetime

def configure_logging(app):
    """Configure logging for the Flask application."""
    
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.mkdir('logs')
    
    # Set up file handler for error logs
    error_file_handler = RotatingFileHandler(
        'logs/errors.log',
        maxBytes=10485760,  # 10MB
        backupCount=10
    )
    error_file_handler.setLevel(logging.ERROR)
    
    # Set up file handler for all logs
    all_file_handler = RotatingFileHandler(
        'logs/app.log',
        maxBytes=10485760,  # 10MB
        backupCount=10
    )
    all_file_handler.setLevel(logging.INFO)
    
    # Set up JSON file handler for structured logs
    class JSONFormatter(logging.Formatter):
        def format(self, record):
            log_record = {
                'timestamp': datetime.utcnow().isoformat(),
                'level': record.levelname,
                'module': record.module,
                'message': record.getMessage(),
                'path': record.pathname,
                'line': record.lineno
            }
            
            # Add exception info if present
            if record.exc_info:
                log_record['exception'] = self.formatException(record.exc_info)
            
            return json.dumps(log_record)
    
    json_file_handler = RotatingFileHandler(
        'logs/app.json',
        maxBytes=10485760,  # 10MB
        backupCount=10
    )
    json_file_handler.setLevel(logging.INFO)
    json_file_handler.setFormatter(JSONFormatter())
    
    # Set up formatter for text logs
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )
    error_file_handler.setFormatter(formatter)
    all_file_handler.setFormatter(formatter)
    
    # Add the handlers to the Flask app's logger
    app.logger.addHandler(error_file_handler)
    app.logger.addHandler(all_file_handler)
    app.logger.addHandler(json_file_handler)
    
    # Set overall log level based on environment
    if app.config['DEBUG']:
        app.logger.setLevel(logging.DEBUG)
    else:
        app.logger.setLevel(logging.INFO)
    
    # Log application startup
    app.logger.info(f"Application startup: {app.name}, DEBUG={app.config['DEBUG']}")
    
    return app

# Example usage in routes:
"""
@api_routes.route('/example')
def example_route():
    try:
        # Route logic here
        app.logger.info("Processed example route")
        return jsonify({"success": True})
    except Exception as e:
        app.logger.error(f"Error in example route: {str(e)}", exc_info=True)
        return jsonify({"error": "An error occurred"}), 500
"""