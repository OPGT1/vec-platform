# routes/certificate_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg2
import psycopg2.extras
from utils import get_db_connection, login_required

# Create blueprint
certificate_routes = Blueprint('certificate_routes', __name__)

# BURN CREDITS
@certificate_routes.route("/burn_credits", methods=["GET", "POST"])
@login_required
def burn_credits():
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    # Calculate user balance
    cursor.execute("""
        SELECT
            COALESCE((SELECT SUM(amount) FROM transactions WHERE receiver_id = %s), 0) AS total_received,
            COALESCE((SELECT SUM(amount) FROM transactions WHERE sender_id = %s), 0) AS total_sent
    """, (user_id, user_id))
    
    balance_result = cursor.fetchone()
    user_balance = balance_result["total_received"] - balance_result["total_sent"]
    
    if request.method == "POST":
        amount = float(request.form["amount"])
        certificate_name = request.form["certificate_name"]
        certificate_email = request.form["certificate_email"]
        
        if amount <= 0:
            flash("Amount must be greater than zero.", "danger")
        elif amount > user_balance:
            flash("Insufficient balance to burn credits.", "danger")
        else:
            try:
                # System account that represents "burned" credits
                BURN_ACCOUNT_ID = 4  # You'll need to create this account in your database
                
                # Insert transaction for burning (transferring to burn account)
                cursor.execute("""
                    INSERT INTO transactions (sender_id, receiver_id, amount, transaction_type) 
                    VALUES (%s, %s, %s, %s)
                """, (user_id, BURN_ACCOUNT_ID, amount, 'burn'))
                
                # Create certificate record
                cursor.execute("""
                    INSERT INTO burn_certificates (user_id, amount, recipient_name, recipient_email, burn_date)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (user_id, amount, certificate_name, certificate_email))
                
                conn.commit()
                
                # Get the ID of the newly created certificate
                certificate_id = cursor.lastrowid
                
                # Calculate environmental impact for certificate
                kwh_equivalent = amount * 10  # 1 VEC = 10 kWh
                co2_avoided = kwh_equivalent * 0.7  # 0.7 kg CO2 per kWh
                
                flash(f"Successfully burned {amount} VEC credits! A certificate has been generated.", "success")
                return redirect(url_for("certificate_routes.certificate", certificate_id=certificate_id))
                
            except Exception as e:
                conn.rollback()
                flash(f"An error occurred: {e}", "danger")
    
    cursor.close()
    conn.close()
    
    return render_template("burn_credits.html", balance=user_balance)

# CERTIFICATE VIEW
@certificate_routes.route("/certificate/<int:certificate_id>")
@login_required
def certificate(certificate_id):
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cursor.execute("""
        SELECT bc.*, u.email as user_email
        FROM burn_certificates bc
        JOIN users u ON bc.user_id = u.id
        WHERE bc.id = %s AND bc.user_id = %s
    """, (certificate_id, user_id))
    
    certificate = cursor.fetchone()
    
    if not certificate:
        flash("Certificate not found.", "danger")
        return redirect(url_for("auth_routes.dashboard"))
    
    # Calculate environmental impact
    kwh_equivalent = certificate["amount"] * 10  # 1 VEC = 10 kWh
    co2_avoided = kwh_equivalent * 0.7  # 0.7 kg CO2 per kWh
    
    cursor.close()
    conn.close()
    
    return render_template("certificate.html", 
                          certificate=certificate,
                          kwh_equivalent=kwh_equivalent,
                          co2_avoided=co2_avoided)

# MY CERTIFICATES
@certificate_routes.route("/my_certificates")
@login_required
def my_certificates():
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cursor.execute("""
        SELECT bc.*, u.email as user_email
        FROM burn_certificates bc
        JOIN users u ON bc.user_id = u.id
        WHERE bc.user_id = %s
        ORDER BY bc.burn_date DESC
    """, (user_id,))
    
    certificates = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template("my_certificates.html", certificates=certificates)

# PUBLIC BURN SUMMARY
@certificate_routes.route('/burn/summary', methods=['GET'])
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
            {"recipient_name": row[0], "recipient_email": row[1], "total_kwh": float(row[2])} 
            for row in results
        ]
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"message": f"Error fetching burn summary: {str(e)}"}), 500

# API BURN
@certificate_routes.route('/api/burn', methods=['POST'])
@login_required
def api_burn_certificates():
    data = request.get_json()
    amount = data.get('amount')
    recipient_name = data.get('recipient_name')
    recipient_email = data.get('recipient_email')
    certificate_hash = data.get('certificate_hash')

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO burn_certificates (user_id, amount, recipient_name, recipient_email, certificate_hash)
        VALUES (%s, %s, %s, %s, %s)
    """, (session.get("user_id"), amount, recipient_name, recipient_email, certificate_hash))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'message': 'Burn recorded successfully.'}), 200