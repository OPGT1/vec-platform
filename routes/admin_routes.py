# routes/admin_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg2
import psycopg2.extras
from utils import get_db_connection, login_required

# Create blueprint
admin_routes = Blueprint('admin_routes', __name__)

# Helper function to check if user is admin
def admin_required(f):
    @login_required
    def decorated_function(*args, **kwargs):
        if session.get("user_id") != 2:  # Assuming admin ID is 2
            flash("Unauthorized access.", "danger")
            return redirect(url_for("auth_routes.dashboard"))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# ADMIN DASHBOARD
@admin_routes.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    return render_template("admin_dashboard.html")

# ADMIN FEES
@admin_routes.route("/admin/fees", methods=["GET", "POST"])
@admin_required
def admin_fees():
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        fee_type = request.form["fee_type"]
        rate = float(request.form["rate"])
        
        cursor.execute("INSERT INTO fee_structure (fee_type, rate) VALUES (%s, %s)", (fee_type, rate))
        conn.commit()
        flash("Fee structure updated successfully!", "success")
    
    # Get current fee structure
    cursor.execute("""
        SELECT DISTINCT ON (fee_type) 
            fee_type, rate, effective_date
        FROM fee_structure
        ORDER BY fee_type, effective_date DESC
    """)
    fees = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template("admin_fees.html", fees=fees)

# ADMIN BURN ACTIVITY
@admin_routes.route('/admin/burn-activity', methods=['GET'])
@admin_required
def admin_burn_activity():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Main query
        cur.execute('''
            SELECT users.email, bc.amount, bc.recipient_name, bc.recipient_email,
                   bc.burn_date, bc.certificate_hash
            FROM burn_certificates bc
            JOIN users ON bc.user_id = users.id
            ORDER BY bc.burn_date DESC
        ''')
        rows = cur.fetchall()

        data = [
            {
                "burner_email": row[0],
                "amount": float(row[1]),
                "recipient_name": row[2],
                "recipient_email": row[3],
                "burn_date": row[4].isoformat(),
                "certificate_hash": row[5]
            }
            for row in rows
        ]

        return jsonify(data), 200

    except Exception as e:
        return jsonify({"message": f"Error fetching admin data: {str(e)}"}), 500

    finally:
        cur.close()
        conn.close()

# SUPABASE TEST
@admin_routes.route("/supabase-test")
@admin_required
def supabase_test():
    import os
    from supabase import create_client, Client
    
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    try:
        response = supabase.table("new_table").select("*").limit(1).execute()
        return jsonify({"message": "Connection successful!", "data": response.data})
    except Exception as e:
        return jsonify({"error": str(e)})