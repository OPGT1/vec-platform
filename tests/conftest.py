# tests/conftest.py

import pytest
import os
import sys
import tempfile

# Add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app as flask_app
from utils import get_db_connection

@pytest.fixture
def app():
    """Create and configure a Flask app for testing."""
    # Set testing config
    os.environ['FLASK_ENV'] = 'testing'
    
    # Create a temporary file to use as the test database
    with tempfile.NamedTemporaryFile() as db_file:
        # Configure the app for testing
        flask_app.config.update({
            'TESTING': True,
            'DATABASE_URL': f"postgresql://postgres:postgres@localhost/vec_test",
            'SUPABASE_URL': os.environ.get('SUPABASE_URL', 'dummy_url'),
            'SUPABASE_KEY': os.environ.get('SUPABASE_KEY', 'dummy_key'),
        })
        
        # Setup test database
        setup_test_db()
        
        yield flask_app

        # Teardown test database
        teardown_test_db()

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """A test CLI runner for the app."""
    return app.test_cli_runner()

def setup_test_db():
    """Set up test database tables."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create test tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            first_name VARCHAR(100),
            last_name VARCHAR(100),
            balance DECIMAL(15,2) DEFAULT 0,
            is_admin BOOLEAN DEFAULT FALSE
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            sender_id INTEGER REFERENCES users(id),
            receiver_id INTEGER REFERENCES users(id),
            amount DECIMAL(15,2) NOT NULL,
            transaction_type VARCHAR(50) DEFAULT 'transfer',
            transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS burn_certificates (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            amount DECIMAL(15,2) NOT NULL,
            recipient_name VARCHAR(255) NOT NULL,
            recipient_email VARCHAR(255) NOT NULL,
            burn_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            certificate_hash VARCHAR(64)
        )
    """)
    
    # Create test users
    cursor.execute("""
        INSERT INTO users (id, email, first_name, last_name, is_admin) 
        VALUES 
        (1, 'system@test.com', 'System', 'Test', FALSE),
        (2, 'admin@test.com', 'Admin', 'Test', TRUE),
        (3, 'user@test.com', 'User', 'Test', FALSE),
        (4, 'burn@test.com', 'Burn', 'Test', FALSE)
    """)
    
    conn.commit()
    cursor.close()
    conn.close()

def teardown_test_db():
    """Clean up test database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Drop all test tables
    cursor.execute("""
        DROP TABLE IF EXISTS burn_certificates;
        DROP TABLE IF EXISTS transactions;
        DROP TABLE IF EXISTS users;
    """)
    
    conn.commit()
    cursor.close()
    conn.close()

# Sample test file
# tests/test_api.py

def test_api_credits(client):
    """Test the /api/credits endpoint."""
    response = client.get('/api/credits')
    assert response.status_code == 200
    data = response.get_json()
    assert 'data' in data

def test_burn_certificate_creation(client):
    """Test creating a burn certificate."""
    # First log in as a test user
    with client.session_transaction() as sess:
        sess['user_id'] = 3  # User test ID
        sess['email'] = 'user@test.com'
    
    # Create a test certificate
    response = client.post('/api/burn', json={
        'amount': 10,
        'recipient_name': 'Test Recipient',
        'recipient_email': 'recipient@test.com'
    })
    
    assert response.status_code == 200
    data = response.get_json()
    assert 'data' in data
    assert 'certificate_id' in data['data']