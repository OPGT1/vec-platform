# routes/marketplace_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg2
import psycopg2.extras
from decimal import Decimal
from utils import get_db_connection, login_required

# Create blueprint
marketplace_routes = Blueprint('marketplace_routes', __name__)

# MARKETPLACE
@marketplace_routes.route("/marketplace")
def marketplace():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Get all open buy/sell orders
    cursor.execute("SELECT order_type, price, amount FROM orders WHERE status = 'open' ORDER BY price ASC")
    orders = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("marketplace.html", orders=orders)

# PLACE ORDER
@marketplace_routes.route("/place_order", methods=["POST"])
@login_required
def place_order():
    user_id = session["user_id"]
    order_type = request.form["order_type"]
    price = Decimal(request.form["price"])
    amount = Decimal(request.form["amount"])

    conn = get_db_connection()
    cursor = conn.cursor()

    # If selling, check balance first
    if order_type == "sell":
        cursor.execute("SELECT balance FROM users WHERE id = %s", (user_id,))
        user_balance = cursor.fetchone()[0]

        if user_balance < amount:
            return jsonify({"error": "Insufficient balance"}), 400

    # Insert new order
    cursor.execute("""
        INSERT INTO orders (user_id, order_type, price, amount, status)
        VALUES (%s, %s, %s, %s, 'open') RETURNING id
    """, (user_id, order_type, price, amount))

    order_id = cursor.fetchone()[0]
    conn.commit()

    cursor.close()
    conn.close()

    # Match orders after placing a new one
    match_orders()

    return jsonify({"message": "Order placed successfully!", "order_id": order_id})

# MATCH ORDERS function
def match_orders():
    conn = get_db_connection()
    cursor = conn.cursor()

    trading_fee_rate = 0.015  
    admin_id = 2  # Admin account for fee collection

    cursor.execute("""
        SELECT b.id AS buy_id, s.id AS sell_id, 
               b.user_id AS buyer, s.user_id AS seller, 
               LEAST(b.amount, s.amount) AS trade_amount, s.price
        FROM orders b
        JOIN orders s ON b.price >= s.price
        WHERE b.order_type = 'buy' 
          AND s.order_type = 'sell'
          AND b.status = 'open' 
          AND s.status = 'open'
        ORDER BY s.price ASC, b.created_at ASC
    """)

    matches = cursor.fetchall()

    for match in matches:
        buy_id, sell_id, buyer, seller, trade_amount, trade_price = match

        fee_amount = trade_amount * trading_fee_rate
        seller_net_amount = trade_amount - fee_amount  

        cursor.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (trade_amount, buyer))
        cursor.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (seller_net_amount, seller))
        cursor.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (fee_amount, admin_id))  

        cursor.execute("UPDATE orders SET status = 'filled' WHERE id = %s", (buy_id,))
        cursor.execute("UPDATE orders SET status = 'filled' WHERE id = %s", (sell_id,))

        cursor.execute("""
            INSERT INTO transactions (sender_id, receiver_id, amount, transaction_type)
            VALUES (%s, %s, %s, 'market_trade')
        """, (buyer, seller, trade_amount))

        cursor.execute("""
            INSERT INTO transactions (sender_id, receiver_id, amount, transaction_type)
            VALUES (%s, %s, %s, 'trading_fee')
        """, (seller, admin_id, fee_amount))

    conn.commit()
    
    cursor.close()
    conn.close()

# ORDER BOOK
@marketplace_routes.route("/order_book")
def order_book():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT order_type, price, amount
        FROM orders
        WHERE status = 'open'
        ORDER BY price ASC
    """)
    orders = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify([
        {
            "order_type": o[0],
            "price": o[1],
            "amount": o[2]
        } for o in orders
    ])

# GET CURRENT VEC PRICE
def get_current_vec_price():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cursor.execute("SELECT value, effective_date FROM prices ORDER BY effective_date DESC LIMIT 1")
        price_data = cursor.fetchone()
        print(f"Retrieved price: {price_data}")
        return price_data
    except Exception as e:
        print(f"Error fetching price: {e}")
        conn.rollback()
        from datetime import datetime
        return {"value": 5.00, "effective_date": datetime.now()}
    finally:
        cursor.close()
        conn.close()

# CREDITS
@marketplace_routes.route('/credits')
def credits():
    try:
        from supabase import create_client
        import os
        
        # Supabase setup
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        data = supabase.table('users').select("email, balance").execute()
        return jsonify({"data": data.data})
    except Exception as e:
        return jsonify({"error": str(e)})