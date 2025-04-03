# utils.py

import os
import psycopg2
import psycopg2.extras
from functools import wraps
from flask import session, redirect, url_for, flash
from supabase import create_client, Client

# Supabase client initialization
def get_supabase_client():
    """
    Create and return a Supabase client using environment variables.
    Returns a Supabase client instance.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables must be set")
    
    return create_client(url, key)

# Lazy-loaded Supabase client - only initialized when needed
_supabase_client = None

def supabase():
    """
    Get the Supabase client, initializing it if necessary.
    This is a singleton pattern - the client is only created once.
    """
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = get_supabase_client()
    return _supabase_client

def get_db_connection():
    """
    Create a connection to the PostgreSQL database.
    Returns a connection object.
    """
    # Get DB connection parameters from environment variables or use defaults
    db_url = os.environ.get("DATABASE_URL")
    
    if db_url:
        # If using a connection URL (e.g., from Railway, Heroku)
        conn = psycopg2.connect(db_url)
    else:
        # If using individual connection parameters
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            database=os.environ.get("DB_NAME", "postgres"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "postgres")
        )
    
    # Set autocommit to False to manage transactions manually
    conn.autocommit = False
    
    return conn

def login_required(f):
    """
    Decorator to ensure user is logged in before accessing a route.
    Redirects to login page if not logged in.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth_routes.login"))
        return f(*args, **kwargs)
    return decorated_function

def init_db():
    """
    Initialize the database schema if it doesn't exist.
    Creates all necessary tables and default records.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if users table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'users'
        )
    """)
    
    table_exists = cursor.fetchone()[0]
    
    if not table_exists:
        # Create users table
        cursor.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                balance DECIMAL(15,2) DEFAULT 0,
                is_admin BOOLEAN DEFAULT FALSE
            )
        """)
        
        # Create other necessary tables
        cursor.execute("""
            CREATE TABLE transactions (
                id SERIAL PRIMARY KEY,
                sender_id INTEGER REFERENCES users(id),
                receiver_id INTEGER REFERENCES users(id),
                amount DECIMAL(15,2) NOT NULL,
                transaction_type VARCHAR(50) DEFAULT 'transfer',
                transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE orders (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                order_type VARCHAR(10) NOT NULL,
                price DECIMAL(15,2) NOT NULL,
                amount DECIMAL(15,2) NOT NULL,
                status VARCHAR(20) DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE fee_structure (
                id SERIAL PRIMARY KEY,
                fee_type VARCHAR(50) NOT NULL,
                rate DECIMAL(10,5) NOT NULL,
                effective_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE burn_certificates (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                amount DECIMAL(15,2) NOT NULL,
                recipient_name VARCHAR(255) NOT NULL,
                recipient_email VARCHAR(255) NOT NULL,
                burn_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                certificate_hash VARCHAR(64)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE prices (
                id SERIAL PRIMARY KEY,
                value DECIMAL(15,2) NOT NULL,
                effective_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create system users
        cursor.execute("""
            INSERT INTO users (id, email, first_name, last_name, is_admin) 
            VALUES 
            (1, 'system@vec-system.com', 'System', 'Account', FALSE),
            (2, 'admin@vec-system.com', 'Admin', 'Account', TRUE),
            (4, 'burn@vec-system.com', 'Burn', 'Account', FALSE)
        """)
        
        # Set initial fee structure
        cursor.execute("""
            INSERT INTO fee_structure (fee_type, rate) VALUES
            ('trading', 0.015),
            ('verification', 0.01),
            ('minting', 0.02)
        """)
        
        # Set initial price
        cursor.execute("""
            INSERT INTO prices (value) VALUES (5.00)
        """)
        
        conn.commit()
        print("Database initialized successfully!")
    else:
        # If table exists, check if is_admin column exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_name = 'users' AND column_name = 'is_admin'
            )
        """)
        
        column_exists = cursor.fetchone()[0]
        
        if not column_exists:
            cursor.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE")
            cursor.execute("UPDATE users SET is_admin = TRUE WHERE id = 2")  # Admin account
            conn.commit()
            print("Added is_admin column to users table")
    
    cursor.close()
    conn.close()