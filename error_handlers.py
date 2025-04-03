# error_handlers.py

from flask import Blueprint, jsonify, render_template, request

error_handlers = Blueprint('errors', __name__)

# API error handler
class APIError(Exception):
    """Base class for API errors."""
    def __init__(self, message, status_code=400, payload=None):
        self.message = message
        self.status_code = status_code
        self.payload = payload
        super().__init__(self.message)

    def to_dict(self):
        error_dict = dict(self.payload or {})
        error_dict['error'] = self.message
        return error_dict

# Specific error types
class ResourceNotFoundError(APIError):
    """Resource not found."""
    def __init__(self, message="Resource not found", payload=None):
        super().__init__(message, 404, payload)

class UnauthorizedError(APIError):
    """Unauthorized access."""
    def __init__(self, message="Unauthorized", payload=None):
        super().__init__(message, 401, payload)

class ValidationError(APIError):
    """Validation error."""
    def __init__(self, message="Validation error", payload=None):
        super().__init__(message, 400, payload)

class DatabaseError(APIError):
    """Database error."""
    def __init__(self, message="Database error", payload=None):
        super().__init__(message, 500, payload)

# Register error handlers
@error_handlers.app_errorhandler(APIError)
def handle_api_error(error):
    """Handle API errors."""
    if request.path.startswith('/api'):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        return response
    else:
        # For web routes, render an error template
        return render_template('error.html', 
                              error_code=error.status_code,
                              error_message=error.message), error.status_code

@error_handlers.app_errorhandler(404)
def not_found_error(error):
    """Handle 404 errors."""
    if request.path.startswith('/api'):
        return jsonify({"error": "Resource not found"}), 404
    return render_template('error.html', error_code=404, 
                          error_message="Page not found"), 404

@error_handlers.app_errorhandler(500)
def internal_server_error(error):
    """Handle 500 errors."""
    if request.path.startswith('/api'):
        return jsonify({"error": "Internal server error"}), 500
    return render_template('error.html', error_code=500, 
                          error_message="Internal server error"), 500