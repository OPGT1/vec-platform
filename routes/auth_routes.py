# routes/auth_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg2
import psycopg2.extras
from utils import get_db_connection, login_required, supabase

# Create blueprint
auth_routes = Blueprint('auth_routes', __name__)

# SIGNUP
# SIGNUP
@auth_routes.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        email = request.form.get("email")
        password = request.form.get("password")

        try:
            result = supabase().auth.sign_up({"email": email, "password": password})

            if result.error:
                flash(result.error.message, "danger")
                return redirect(url_for("auth_routes.signup"))

            user_id = result.user.id
            session["user_id"] = user_id

            supabase().table("users").insert({
                "id": user_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "balance": 0,
                "is_admin": False
            }).execute()

            return redirect("/dashboard")
        except Exception as e:
            flash(f"An error occurred during signup: {str(e)}", "danger")
            return redirect(url_for("auth_routes.signup"))

    return render_template("signup.html")


# LOGIN
@auth_routes.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        try:
            result = supabase().auth.sign_in_with_password({
                "email": email,
                "password": password
            })

            if not result.user:
                flash("Invalid email or password", "danger")
                return redirect(url_for("auth_routes.login"))

            user_id = result.user.id
            session["user_id"] = user_id
            session["email"] = email

            return redirect("/dashboard")

        except Exception as e:
            flash(f"An error occurred during login: {str(e)}", "danger")
            return redirect(url_for("auth_routes.login"))

    return render_template("login.html")


        

# FORGOT PASSWORD
@auth_routes.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")
        
        # Check if email exists in your database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            
            if user:
                # In a real implementation, you would:
                # 1. Generate a reset token
                # 2. Store it in your database with an expiration time
                # 3. Send an email with a reset link
                
                # For now, we'll just show a success message
                flash("If an account exists with that email, we've sent password reset instructions.", "success")
            else:
                # Don't reveal that the email doesn't exist for security reasons
                flash("If an account exists with that email, we've sent password reset instructions.", "success")
                
            return redirect(url_for("auth_routes.login"))
            
        except Exception as e:
            conn.rollback()
            print(f"Password reset error: {e}")
            flash("An error occurred. Please try again later.", "danger")
            
        finally:
            cursor.close()
            conn.close()
    
    return render_template("forgot_password.html")

# DASHBOARD
@auth_routes.route("/dashboard")
@login_required
def dashboard():
    if "user_id" not in session:
        flash("You must be logged in to view this page.", "warning")
        return redirect(url_for("auth_routes.login"))

    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Get transactions data
        cursor.execute("""
            SELECT t.id, u1.first_name AS sender, u2.first_name AS receiver,
                   t.amount, TO_CHAR(t.transaction_date, 'YYYY-MM-DD HH24:MI:SS') AS transaction_date
            FROM transactions t
            JOIN users u1 ON t.sender_id = u1.id
            JOIN users u2 ON t.receiver_id = u2.id
            WHERE t.sender_id = %s OR t.receiver_id = %s
            ORDER BY t.transaction_date DESC
        """, (user_id, user_id))
        
        transactions = cursor.fetchall()
        
        # Calculate user balance
        cursor.execute("""
            SELECT 
                COALESCE((SELECT SUM(amount) FROM transactions WHERE receiver_id = %s), 0) AS total_received,
                COALESCE((SELECT SUM(amount) FROM transactions WHERE sender_id = %s), 0) AS total_sent
        """, (user_id, user_id))
        
        balance_result = cursor.fetchone()
        balance = balance_result["total_received"] - balance_result["total_sent"]
        
        # Get current VEC price
        cursor.execute("SELECT value, effective_date FROM prices ORDER BY effective_date DESC LIMIT 1")
        try:
            vec_price = cursor.fetchone()
        except:
            from datetime import datetime
            vec_price = {"value": 5.00, "effective_date": datetime.now()}

        # Environmental impact calculations
        total_kwh = float(balance) * 10  # Assuming 1 VEC = 10 kWh
        co2_avoided = round(total_kwh * 0.7, 1)  # 0.7 kg CO2 avoided per kWh
        tree_equivalent = round(co2_avoided / 20)  # 20 kg CO2 per tree per year
        homes_powered = round(total_kwh / 30)  # 30 kWh per home per day
        
        return render_template("dashboard.html", 
                               email=session["email"], 
                               transactions=transactions, 
                               balance=balance,
                               vec_price=vec_price,
                               co2_avoided=co2_avoided,
                               tree_equivalent=tree_equivalent,
                               homes_powered=homes_powered)
                               
    except Exception as e:
        conn.rollback()  # Roll back any failed transaction
        print(f"Dashboard error: {e}")
        flash("An error occurred while loading your dashboard. Please try again.", "danger")
        return redirect(url_for("auth_routes.login"))
        
    finally:
        cursor.close()
        conn.close()


# DASHBOARD ANALYTICS
@auth_routes.route("/dashboard-analytics")
@login_required
def dashboard_analytics():
    return render_template("dashboard-analytics.html")

# SEND CREDITS PAGE
@auth_routes.route("/send_credits_page", methods=["GET"])
@login_required
def send_credits_page():
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    # Calculate balance
    cursor.execute("""
        SELECT
            COALESCE((SELECT SUM(amount) FROM transactions WHERE receiver_id = %s), 0) AS total_received,
            COALESCE((SELECT SUM(amount) FROM transactions WHERE sender_id = %s), 0) AS total_sent
    """, (user_id, user_id))
    
    balance_result = cursor.fetchone()
    user_balance = balance_result["total_received"] - balance_result["total_sent"]
    
    cursor.close()
    conn.close()
    
    return render_template("send_credits.html", balance=user_balance)

# SEND CREDITS
@auth_routes.route("/send_credits", methods=["POST"])
@login_required
def send_credits():
    sender_id = session["user_id"]
    receiver_email = request.form["receiver_email"]
    amount_gross = float(request.form["amount"])

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if receiver exists
    cursor.execute("SELECT id FROM users WHERE email = %s", (receiver_email,))
    receiver = cursor.fetchone()

    if not receiver:
        flash("Receiver not found!", "danger")
        return redirect(url_for("auth_routes.send_credits_page"))

    receiver_id = receiver[0]
    
    # Get trading fee rate
    cursor.execute("SELECT rate FROM fee_structure WHERE fee_type = 'trading' ORDER BY effective_date DESC LIMIT 1")
    fee_result = cursor.fetchone()
    trading_fee_rate = fee_result[0] if fee_result else 0.015
    
    # Calculate fee
    fee_amount = amount_gross * float(trading_fee_rate)
    
    # Net amount after fee
    amount_net = amount_gross - fee_amount
    
    admin_id = 2  # Admin account ID for collecting fees

    # Check sender balance
    cursor.execute("""
        SELECT COALESCE((SELECT SUM(amount) FROM transactions WHERE receiver_id = %s), 0)
               - COALESCE((SELECT SUM(amount) FROM transactions WHERE sender_id = %s), 0)
        AS balance
    """, (sender_id, sender_id))
   
    sender_balance = cursor.fetchone()[0]

    if sender_balance < amount_gross:
        flash("Insufficient credits balance!", "danger")
        return redirect(url_for("auth_routes.send_credits_page"))

    # Insert transaction for net amount to receiver
    cursor.execute("INSERT INTO transactions (sender_id, receiver_id, amount) VALUES (%s, %s, %s)", 
                  (sender_id, receiver_id, amount_net))
    
    # Insert transaction for fee to admin
    cursor.execute("INSERT INTO transactions (sender_id, receiver_id, amount, transaction_type) VALUES (%s, %s, %s, %s)", 
                  (sender_id, admin_id, fee_amount, 'trading_fee'))
    
    conn.commit()
    cursor.close()
    conn.close()

    flash(f"Credits sent successfully! A trading fee of {fee_amount:.2f} VEC was applied.", "success")
    return redirect(url_for("auth_routes.dashboard"))