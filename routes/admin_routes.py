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
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Check if user is admin
            cursor.execute("SELECT is_admin FROM users WHERE id = %s", (session["user_id"],))
            user = cursor.fetchone()
            
            if not user or not user[0]:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("auth_routes.dashboard"))
                
        except Exception as e:
            conn.rollback()
            flash(f"An error occurred: {e}", "danger")
            return redirect(url_for("auth_routes.dashboard"))
            
        finally:
            cursor.close()
            conn.close()
            
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

# ADMIN USERS
@admin_routes.route('/admin/users', methods=["GET"])
@admin_required
def admin_users():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cursor.execute("""
        SELECT id, email, first_name, last_name, is_admin
        FROM users
        ORDER BY id
    """)
    
    users = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template("admin_users.html", users=users)

# TOGGLE ADMIN STATUS
@admin_routes.route('/admin/toggle_admin/<int:user_id>', methods=["POST"])
@admin_required
def toggle_admin(user_id):
    # Don't allow toggling your own admin status
    if user_id == session["user_id"]:
        flash("You cannot change your own admin status.", "danger")
        return redirect(url_for("admin_routes.admin_users"))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get current admin status
    cursor.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("admin_routes.admin_users"))
    
    # Toggle admin status
    new_status = not user[0]
    cursor.execute("UPDATE users SET is_admin = %s WHERE id = %s", (new_status, user_id))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    flash(f"User admin status updated successfully.", "success")
    return redirect(url_for("admin_routes.admin_users"))