# app.py - Main application file

import os
from flask import Flask, redirect, url_for, session, send_from_directory
from flask_session import Session
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import utility functions
from utils import init_db

# Import routes
from routes.auth_routes import auth_routes
from routes.certificate_routes import certificate_routes
from routes.marketplace_routes import marketplace_routes
from routes.upload_routes import upload_routes
from routes.admin_routes import admin_routes

# Import API routes if they exist
try:
    from routes.api_routes import api_routes
    api_routes_available = True
except ImportError:
    api_routes_available = False
    print("API routes not available")

def create_app():
    """
    Application factory function.
    Creates and configures the Flask application.
    """
    # Create Flask app
    app = Flask(__name__, static_url_path='/static', static_folder='static')
    
    # Configure app
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-key")
    app.config["SESSION_TYPE"] = "filesystem"
    Session(app)
    
    # Register blueprints
    app.register_blueprint(auth_routes)
    app.register_blueprint(certificate_routes)
    app.register_blueprint(marketplace_routes)
    app.register_blueprint(admin_routes)
    app.register_blueprint(upload_routes)
    
    # Register API routes if available
    if api_routes_available:
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
    
    return app

# Create the application instance
app = create_app()

# Initialize the database if needed
try:
    with app.app_context():
        init_db()
        print("Database initialized")
except Exception as e:
    print(f"Error initializing database: {e}")

# Main entry point
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)