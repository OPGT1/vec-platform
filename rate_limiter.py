# rate_limiter.py

import time
from flask import request, g, jsonify
from functools import wraps
import redis
import os

# Configure Redis client
redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

try:
    redis_client = redis.from_url(redis_url)
    redis_available = True
except:
    redis_available = False
    print("Warning: Redis not available. Using in-memory rate limiting (not suitable for production).")
    # Fallback to in-memory storage for rate limiting
    rate_limit_storage = {}

class RateLimiter:
    """Rate limiter to prevent API abuse."""
    
    def __init__(self, requests=100, window=60, key_prefix='rate_limit'):
        """
        Initialize rate limiter.
        
        Args:
            requests: Maximum number of requests allowed in the time window
            window: Time window in seconds
            key_prefix: Redis key prefix for rate limiting
        """
        self.requests = requests
        self.window = window
        self.key_prefix = key_prefix
    
    def get_key(self, key):
        """Get a rate limiting key for a specific identifier."""
        return f"{self.key_prefix}:{key}"
    
    def is_rate_limited(self, key):
        """
        Check if a key is rate limited.
        Returns True if rate limited, False otherwise.
        """
        if redis_available:
            return self._redis_is_rate_limited(key)
        else:
            return self._memory_is_rate_limited(key)
    
    def _redis_is_rate_limited(self, key):
        """Check rate limits using Redis."""
        redis_key = self.get_key(key)
        current_time = int(time.time())
        window_start = current_time - self.window
        
        # Use Redis pipeline for atomic operations
        pipe = redis_client.pipeline()
        
        # Remove old entries outside the current window
        pipe.zremrangebyscore(redis_key, 0, window_start)
        
        # Count requests in the current window
        pipe.zcard(redis_key)
        
        # Add the current request
        pipe.zadd(redis_key, {str(current_time): current_time})
        
        # Set expiration on the key
        pipe.expire(redis_key, self.window)
        
        # Execute all commands
        results = pipe.execute()
        
        # Get the count of requests in the window
        request_count = results[1]
        
        # Return True if rate limited
        return request_count > self.requests
    
    def _memory_is_rate_limited(self, key):
        """Check rate limits using in-memory storage."""
        memory_key = self.get_key(key)
        current_time = int(time.time())
        window_start = current_time - self.window
        
        # Initialize if key doesn't exist
        if memory_key not in rate_limit_storage:
            rate_limit_storage[memory_key] = []
        
        # Clean old entries
        rate_limit_storage[memory_key] = [
            t for t in rate_limit_storage[memory_key] if t > window_start
        ]
        
        # Check if rate limited
        if len(rate_limit_storage[memory_key]) >= self.requests:
            return True
        
        # Add current request
        rate_limit_storage[memory_key].append(current_time)
        
        return False

# Create default rate limiters
default_limiter = RateLimiter(requests=100, window=60)
strict_limiter = RateLimiter(requests=20, window=60)

def rate_limit(limiter=None, key_func=None):
    """
    Decorator for rate limiting routes.
    
    Args:
        limiter: RateLimiter instance to use (default: default_limiter)
        key_func: Function to get the rate limit key (default: IP address)
    """
    if limiter is None:
        limiter = default_limiter
    
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            # Get rate limit key
            if key_func:
                key = key_func()
            else:
                # Default to IP address
                key = request.remote_addr
            
            # Check rate limit
            if limiter.is_rate_limited(key):
                return jsonify({
                    "error": "Rate limit exceeded",
                    "message": "Too many requests. Please try again later."
                }), 429
            
            return f(*args, **kwargs)
        return wrapped
    return decorator

# Example usage in routes:
"""
@api_routes.route('/burn', methods=['POST'])
@rate_limit(limiter=strict_limiter)  # Stricter limit for expensive operations
@api_auth_required
def burn_certificates():
    # Route implementation
    pass

@api_routes.route('/order_book')
@rate_limit()  # Default rate limit
def order_book():
    # Route implementation
    pass
"""