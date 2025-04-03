# routes/api_routes.py

from flask import Blueprint, request, jsonify, session
import psycopg2
import psycopg2.extras
from decimal import Decimal
import os
from supabase import create_client
from utils import get_db_connection, login_required

# Create blueprint
api_routes = Blueprint('api', __name__, url_prefix='/api')

# SUPABASE SETUP
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# API ERROR RESPONSES
def api_error(message, status_code=400):
    return jsonify({"error": message}), status_code

def api_success(data, message="Success"):
    return jsonify({"message": message, "data": data})

# AUTHENTICATION MIDDLEWARE FOR API
def api_auth_required(f):
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return api_error("Authentication required", 401)
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

# CREDITS ENDPOINT
@api_routes.route('/credits')
def credits():
    try:
        data = supabase.table('users').select("email, balance").execute()
        return api_success(data.data)
    except Exception as e:
        return api_error(str(e))

# ORDER BOOK ENDPOINT
@api_routes.route('/order_book')
def order_book():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT order_type, price, amount
            FROM orders
            WHERE status = 'open'
            ORDER BY price ASC
        """)
        orders = cur.fetchall()

        return api_success([
            {
                "order_type": o[0],
                "price": float(o[1]),
                "amount": float(o[2])
            } for o in orders
        ])
    except Exception as e:
        return api_error(f"Database error: {str(e)}")
    finally:
        cur.close()
        conn.close()

# BURN CERTIFICATES ENDPOINT
@api_routes.route('/burn', methods=['POST'])
@api_auth_required
def burn_certificates():
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['amount', 'recipient_name', 'recipient_email']
    for field in required_fields:
        if field not in data:
            return api_error(f"Missing required field: {field}")
    
    amount = data.get('amount')
    recipient_name = data.get('recipient_name')
    recipient_email = data.get('recipient_email')
    certificate_hash = data.get('certificate_hash')

    # Validate amount
    try:
        amount = float(amount)
        if amount <= 0:
            return api_error("Amount must be greater than zero")
    except (ValueError, TypeError):
        return api_error("Invalid amount format")

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Check user balance
        user_id = session.get("user_id")
        cur.execute("""
            SELECT 
                COALESCE((SELECT SUM(amount) FROM transactions WHERE receiver_id = %s), 0) -
                COALESCE((SELECT SUM(amount) FROM transactions WHERE sender_id = %s), 0) AS balance
        """, (user_id, user_id))
        balance = cur.fetchone()[0]
        
        if balance < amount:
            return api_error("Insufficient balance")
        
        # Create burn certificate
        cur.execute("""
            INSERT INTO burn_certificates 
            (user_id, amount, recipient_name, recipient_email, certificate_hash)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, amount, recipient_name, recipient_email, certificate_hash))
        
        certificate_id = cur.fetchone()[0]
        
        # Record transaction (to burn account)
        BURN_ACCOUNT_ID = 4  # ID of the burn account
        cur.execute("""
            INSERT INTO transactions 
            (sender_id, receiver_id, amount, transaction_type)
            VALUES (%s, %s, %s, 'burn')
        """, (user_id, BURN_ACCOUNT_ID, amount))
        
        conn.commit()
        
        return api_success(
            {"certificate_id": certificate_id},
            "Burn recorded successfully"
        )
    
    except Exception as e:
        conn.rollback()
        return api_error(f"Server error: {str(e)}")
    
    finally:
        cur.close()
        conn.close()

# GET CERTIFICATE ENDPOINT
@api_routes.route('/certificate/<int:certificate_id>')
def get_certificate(certificate_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        cur.execute("""
            SELECT 
                bc.id, bc.amount, bc.recipient_name, bc.recipient_email, 
                bc.burn_date, bc.certificate_hash,
                u.email as burner_email
            FROM burn_certificates bc
            JOIN users u ON bc.user_id = u.id
            WHERE bc.id = %s
        """, (certificate_id,))
        
        cert = cur.fetchone()
        
        if not cert:
            return api_error("Certificate not found", 404)
        
        # Calculate environmental impact
        kwh_equivalent = float(cert["amount"]) * 10
        co2_avoided = kwh_equivalent * 0.7
        
        return api_success({
            "id": cert["id"],
            "amount": float(cert["amount"]),
            "recipient_name": cert["recipient_name"],
            "recipient_email": cert["recipient_email"],
            "burn_date": cert["burn_date"].isoformat(),
            "burner_email": cert["burner_email"],
            "environmental_impact": {
                "kwh_equivalent": kwh_equivalent,
                "co2_avoided_kg": co2_avoided
            }
        })
    
    except Exception as e:
        return api_error(f"Server error: {str(e)}")
    
    finally:
        cur.close()
        conn.close()

# BURN SUMMARY ENDPOINT
@api_routes.route('/burn/summary')
def burn_summary():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT recipient_name, recipient_email, SUM(amount) as total
            FROM burn_certificates
            GROUP BY recipient_name, recipient_email
        ''')
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        data = [
            {
                "recipient_name": row[0], 
                "recipient_email": row[1], 
                "total_credits": float(row[2]),
                "total_kwh": float(row[2]) * 10,
                "total_co2_avoided_kg": float(row[2]) * 10 * 0.7
            } 
            for row in results
        ]
        
        return api_success(data)
    
    except Exception as e:
        return api_error(f"Error fetching burn summary: {str(e)}")

# PLACE ORDER ENDPOINT
@api_routes.route('/place_order', methods=["POST"])
@api_auth_required
def place_order():
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['order_type', 'price', 'amount']
    for field in required_fields:
        if field not in data:
            return api_error(f"Missing required field: {field}")
    
    user_id = session["user_id"]
    order_type = data.get("order_type")
    
    # Validate order type
    if order_type not in ["buy", "sell"]:
        return api_error("Order type must be 'buy' or 'sell'")
    
    # Validate price and amount
    try:
        price = Decimal(data.get("price"))
        amount = Decimal(data.get("amount"))
        
        if price <= 0:
            return api_error("Price must be greater than zero")
        if amount <= 0:
            return api_error("Amount must be greater than zero")
    except (ValueError, TypeError, InvalidOperation):
        return api_error("Invalid price or amount format")

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # If selling, check balance first
        if order_type == "sell":
            cursor.execute("""
                SELECT 
                    COALESCE((SELECT SUM(amount) FROM transactions WHERE receiver_id = %s), 0) -
                    COALESCE((SELECT SUM(amount) FROM transactions WHERE sender_id = %s), 0) AS balance
            """, (user_id, user_id))
            user_balance = cursor.fetchone()[0]

            if user_balance < amount:
                return api_error("Insufficient balance")

        # Insert new order
        cursor.execute("""
            INSERT INTO orders (user_id, order_type, price, amount, status)
            VALUES (%s, %s, %s, %s, 'open') RETURNING id
        """, (user_id, order_type, price, amount))

        order_id = cursor.fetchone()[0]
        conn.commit()
        
        # Import and call match_orders function
        from routes.marketplace_routes import match_orders
        match_orders()
        
        return api_success({"order_id": order_id}, "Order placed successfully")
    
    except Exception as e:
        conn.rollback()
        return api_error(f"Server error: {str(e)}")
    
    finally:
        cursor.close()
        conn.close()

# GET USER BALANCE ENDPOINT
@api_routes.route('/balance')
@api_auth_required
def get_balance():
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                COALESCE((SELECT SUM(amount) FROM transactions WHERE receiver_id = %s), 0) -
                COALESCE((SELECT SUM(amount) FROM transactions WHERE sender_id = %s), 0) AS balance
        """, (user_id, user_id))
        
        user_balance = float(cursor.fetchone()[0])
        
        return api_success({
            "balance": user_balance,
            "environmental_impact": {
                "kwh_equivalent": user_balance * 10,
                "co2_avoided_kg": user_balance * 10 * 0.7
            }
        })
    
    except Exception as e:
        return api_error(f"Server error: {str(e)}")
    
    finally:
        cursor.close()
        conn.close()