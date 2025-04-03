# app.py - Main application file

import os
from flask import Flask, redirect, url_for, session, send_from_directory
from flask_session import Session

# Import configuration
from config import get_config

# Import utility functions
from utils import init_db

# Import logging configuration
from logging_config import configure_logging

# Import error handlers
from error_handlers import error_handlers

# Import rate limiter
from rate_limiter import redis_available

# Import database migration manager
from migrations.migration_manager import MigrationManager

# Import routes
from routes.auth_routes import auth_routes
from routes.certificate_routes import certificate_routes
from routes.marketplace_routes import marketplace_routes
from routes.upload_routes import upload_routes
from routes.admin_routes import admin_routes
from routes.api_routes import api_routes

def create_app(config_name='default'):
    """
    Application factory function.
    Creates and configures the Flask application.
    """
    # Create Flask app
    app = Flask(__name__, static_url_path='/static', static_folder='static')
    
    # Load configuration
    app.config.from_object(get_config())
    
    # Configure session
    app.secret_key = app.config['SECRET_KEY']
    app.config['SESSION_TYPE'] = app.config['SESSION_TYPE']
    Session(app)
    
    # Configure logging
    configure_logging(app)
    
    # Register error handlers
    app.register_blueprint(error_handlers)
    
    # Register blueprints
    app.register_blueprint(auth_routes)
    app.register_blueprint(certificate_routes)
    app.register_blueprint(marketplace_routes)
    app.register_blueprint(admin_routes)
    app.register_blueprint(upload_routes)
    app.register_blueprint(api_routes)
    
    # Root route
    @app.route("/")
    def home():
        return redirect(url_for("auth_routes.login"))
    
    # Static files routes
    @app.route('/static/<path:filename>')
    def static_files(filename):
        return send_from_directory('static', filename)
    
    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory('static', 'favicon.ico')
    
    # Health check endpoint
    @app.route("/ping")
    def ping():
        return "pong", 200
    
    # Context processor for datetime
    from datetime import datetime
    @app.context_processor
    def inject_now():
        return {'now': datetime.utcnow()}
    
    # Check Redis availability
    @app.before_first_request
    def check_redis():
        if not redis_available:
            app.logger.warning("Redis not available - using in-memory rate limiting. Not suitable for production!")
    
    # Initialize database
    with app.app_context():
        init_db()
        
        # Apply database migrations
        try:
            migration_manager = MigrationManager()
            migration_manager.apply_pending_migrations()
        except Exception as e:
            app.logger.error(f"Error applying migrations: {e}")
    
    return app

# Create the application
app = create_app()

# In app.py, where you import redis_available
try:
    from rate_limiter import redis_available
except ImportError:
    redis_available = False

if __name__ == "__main__":
    # Run the application
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)