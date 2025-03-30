from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import psycopg2
import psycopg2.extras
from decimal import Decimal
import datetime

import json
import io
import csv
from flask import make_response
from decimal import Decimal

from psycopg2 import pool

# Create a connection pool (add this near the top after imports)
connection_pool = None

def initialize_connection_pool():
    global connection_pool
    connection_pool = pool.SimpleConnectionPool(
        minconn=5,
        maxconn=20,
        host="localhost",
        dbname="vec_ledger",
        user="postgres",
        password="JlzPlz59"  # Consider using environment variables for this
    )

# Modified get_db_connection function
def get_db_connection():
    global connection_pool
    if connection_pool is None:
        initialize_connection_pool()
    return connection_pool.getconn()

# Add function to return connection to the pool
def return_db_connection(conn):
    global connection_pool
    if connection_pool is not None:
        connection_pool.putconn(conn)

admin_routes = Blueprint('admin_routes', __name__, url_prefix='/admin')


@admin_routes.route('/dashboard')
@admin_required
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    # System health at a glance
    cursor.execute("""
        SELECT 
            (SELECT COUNT(*) FROM users) as user_count,
            (SELECT COUNT(*) FROM transactions WHERE transaction_date > NOW() - INTERVAL '24 hours') as transactions_24h,
            (SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '7 days') as new_users_7d,
            (SELECT SUM(amount) FROM burn_certificates WHERE burn_date > NOW() - INTERVAL '30 days') as burned_30d,
            (SELECT COUNT(*) FROM burn_certificates WHERE burn_date > NOW() - INTERVAL '24 hours') as certificates_24h
    """)
    
    stats = cursor.fetchone()
    
    # User growth over time (last 6 months)
    cursor.execute("""
        SELECT 
            DATE_TRUNC('month', created_at) as month,
            COUNT(*) as new_users
        FROM users
        WHERE created_at > NOW() - INTERVAL '6 months'
        GROUP BY DATE_TRUNC('month', created_at)
        ORDER BY month
    """)
    
    user_growth = cursor.fetchall()
    
    # Transaction volume trends
    cursor.execute("""
        SELECT 
            DATE_TRUNC('day', transaction_date) as day,
            transaction_type,
            SUM(amount) as daily_volume
        FROM transactions
        WHERE transaction_date > NOW() - INTERVAL '30 days'
        GROUP BY day, transaction_type
        ORDER BY day, transaction_type
    """)
    
    volume_data = cursor.fetchall()
    
    # Top users by activity
    cursor.execute("""
        SELECT 
            u.email,
            COUNT(t.*) as transaction_count,
            SUM(CASE WHEN t.sender_id = u.id THEN t.amount ELSE 0 END) as sent,
            SUM(CASE WHEN t.receiver_id = u.id THEN t.amount ELSE 0 END) as received
        FROM users u
        LEFT JOIN transactions t ON u.id = t.sender_id OR u.id = t.receiver_id
        WHERE t.transaction_date > NOW() - INTERVAL '30 days'
        GROUP BY u.id
        ORDER BY transaction_count DESC
        LIMIT 5
    """)
    
    top_users = cursor.fetchall()
    
    # Recent activity feed - combine transactions and certificates
    cursor.execute("""
        (SELECT 
            'transaction' as activity_type,
            t.id as activity_id,
            t.transaction_date as activity_date,
            u1.email as actor,
            u2.email as target,
            t.amount,
            t.transaction_type as action
        FROM transactions t
        JOIN users u1 ON t.sender_id = u1.id
        JOIN users u2 ON t.receiver_id = u2.id
        ORDER BY t.transaction_date DESC
        LIMIT 5)
        
        UNION ALL
        
        (SELECT
            'certificate' as activity_type,
            bc.id as activity_id,
            bc.burn_date as activity_date,
            u.email as actor,
            bc.recipient_name as target,
            bc.amount,
            'burn_certificate' as action
        FROM burn_certificates bc
        JOIN users u ON bc.user_id = u.id
        ORDER BY bc.burn_date DESC
        LIMIT 5)
        
        ORDER BY activity_date DESC
        LIMIT 10
    """)
    
    recent_activity = cursor.fetchall()
    
    cursor.close()
    return_db_connection(conn)
    
    return render_template("admin/dashboard.html", 
                          stats=stats,
                          user_growth=user_growth,
                          volume_data=volume_data,
                          top_users=top_users,
                          recent_activity=recent_activity)
   
@admin_routes.route('/users', methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST" and "bulk_action" in request.form:
        action = request.form["bulk_action"]
        selected_users = request.form.getlist("selected_users")
        
        if not selected_users:
            flash("No users selected.", "warning")
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            if action == "make_admin":
                # Don't allow changing own status
                selected_users = [int(uid) for uid in selected_users if int(uid) != session["user_id"]]
                if selected_users:
                    cursor.execute(
                        "UPDATE users SET is_admin = TRUE WHERE id = ANY(%s)",
                        (selected_users,)
                    )
                    
                    for user_id in selected_users:
                        log_admin_action(
                            admin_id=session["user_id"],
                            action="bulk_make_admin",
                            entity_type="user",
                            entity_id=user_id
                        )
                    
                    flash(f"{len(selected_users)} users granted admin privileges.", "success")
            
            elif action == "remove_admin":
                # Don't allow changing own status
                selected_users = [int(uid) for uid in selected_users if int(uid) != session["user_id"]]
                if selected_users:
                    cursor.execute(
                        "UPDATE users SET is_admin = FALSE WHERE id = ANY(%s)",
                        (selected_users,)
                    )
                    
                    for user_id in selected_users:
                        log_admin_action(
                            admin_id=session["user_id"],
                            action="bulk_remove_admin",
                            entity_type="user",
                            entity_id=user_id
                        )
                    
                    flash(f"{len(selected_users)} users had admin privileges removed.", "success")
            
            elif action == "export_email":
                cursor.execute(
                    "SELECT email FROM users WHERE id = ANY(%s)",
                    ([int(uid) for uid in selected_users],)
                )
                emails = [row[0] for row in cursor.fetchall()]
                
                log_admin_action(
                    admin_id=session["user_id"],
                    action="export_emails",
                    entity_type="user",
                    details={"count": len(emails)}
                )
                
                # Return CSV file
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["Email"])
                for email in emails:
                    writer.writerow([email])
                
                response = make_response(output.getvalue())
                response.headers["Content-Disposition"] = "attachment; filename=user_emails.csv"
                response.headers["Content-type"] = "text/csv"
                
                cursor.close()
                return_db_connection(conn)
                return response
            
            conn.commit()
            cursor.close()
            return_db_connection(conn)
    
    # Get users with filters and pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '')
    balance_min = request.args.get('balance_min', '', type=str)
    balance_max = request.args.get('balance_max', '', type=str)
    is_admin = request.args.get('is_admin', '')
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    # Build dynamic query
    query_conditions = ["1=1"]
    query_params = []
    
    if search:
        query_conditions.append("(u.email ILIKE %s OR u.first_name ILIKE %s OR u.last_name ILIKE %s)")
        search_pattern = f"%{search}%"
        query_params.extend([search_pattern, search_pattern, search_pattern])
    
    if is_admin:
        query_conditions.append("u.is_admin = %s")
        query_params.append(is_admin == 'yes')
    
    # Count total for pagination
    count_query = f"""
        SELECT COUNT(*)
        FROM users u
        WHERE {' AND '.join(query_conditions)}
    """
    
    cursor.execute(count_query, query_params)
    total_count = cursor.fetchone()[0]
    
    # Get paginated user data
    query = f"""
        WITH user_balances AS (
            SELECT 
                u.id,
                COALESCE((SELECT SUM(amount) FROM transactions WHERE receiver_id = u.id), 0) -
                COALESCE((SELECT SUM(amount) FROM transactions WHERE sender_id = u.id), 0) AS balance
            FROM users u
        )
        SELECT 
            u.id, u.email, u.first_name, u.last_name, u.is_admin,
            ub.balance
        FROM users u
        JOIN user_balances ub ON u.id = ub.id
        WHERE {' AND '.join(query_conditions)}
    """
    
    # Add balance range filters if provided
    balance_filter_added = False
    if balance_min:
        query += " AND ub.balance >= %s"
        query_params.append(Decimal(balance_min))
        balance_filter_added = True
    
    if balance_max:
        query += " AND ub.balance <= %s"
        query_params.append(Decimal(balance_max))
        balance_filter_added = True
    
    # If balance filters changed the query, we need to recount
    if balance_filter_added:
        cursor.execute(count_query + " AND ub.balance BETWEEN %s AND %s", 
                      query_params[:-2] + [Decimal(balance_min or 0), Decimal(balance_max or 9999999)])
        total_count = cursor.fetchone()[0]
    
    query += """
        ORDER BY u.id
        LIMIT %s OFFSET %s
    """
    
    query_params.append(per_page)
    query_params.append((page - 1) * per_page)
    
    cursor.execute(query, query_params)
    users = cursor.fetchall()
    
    cursor.close()
    return_db_connection(conn)
    
    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page
    has_next = page < total_pages
    has_prev = page > 1
    
    return render_template("admin/advanced.users.html", 
                          users=users,
                          page=page,
                          per_page=per_page,
                          total_pages=total_pages,
                          total_count=total_count,
                          has_next=has_next,
                          has_prev=has_prev,
                          search=search,
                          balance_min=balance_min,
                          balance_max=balance_max,
                          is_admin=is_admin)

@admin_routes.route('/fees', methods=["GET", "POST"])
@admin_required
def fees():
    if request.method == "POST":
        fee_type = request.form["fee_type"]
        rate = Decimal(request.form["rate"])
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO fee_structure (fee_type, rate) VALUES (%s, %s)",
            (fee_type, rate)
        )
        conn.commit()
        cursor.close()
        return_db_connection(conn)
        
        flash("Fee structure updated successfully!", "success")
    
    # Get current fee structure
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute("""
        SELECT id, fee_type, rate, effective_date
        FROM fee_structure
        ORDER BY fee_type, effective_date DESC
    """)
    fees = cursor.fetchall()
    cursor.close()
    return_db_connection(conn)
    
    return render_template("admin/fees.html", fees=fees)

@admin_routes.route('/transactions')
@admin_required
def transactions():
    # Get query parameters for filtering
    transaction_type = request.args.get('type', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    query = """
        SELECT t.id, u1.email AS sender, u2.email AS receiver,
               t.amount, t.transaction_type, t.transaction_date
        FROM transactions t
        JOIN users u1 ON t.sender_id = u1.id
        JOIN users u2 ON t.receiver_id = u2.id
        WHERE 1=1
    """
    
    params = []
    
    if transaction_type:
        query += " AND t.transaction_type = %s"
        params.append(transaction_type)
    
    if start_date:
        query += " AND t.transaction_date >= %s"
        params.append(start_date)
    
    if end_date:
        query += " AND t.transaction_date <= %s"
        params.append(end_date + " 23:59:59")
    
    query += " ORDER BY t.transaction_date DESC"
    
    cursor.execute(query, params)
    transactions = cursor.fetchall()
    
    # Get unique transaction types for the filter dropdown
    cursor.execute("SELECT DISTINCT transaction_type FROM transactions")
    transaction_types = [row[0] for row in cursor.fetchall()]
    
    conn.commit()
    cursor.close()
    return_db_connection(conn)
    
    return render_template("admin/transactions.html", 
                          transactions=transactions,
                          transaction_types=transaction_types,
                          selected_type=transaction_type,
                          start_date=start_date,
                          end_date=end_date)


# Add these routes to your admin_routes.py file

def log_admin_action(admin_id, action, entity_type, entity_id=None, details=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        INSERT INTO admin_audit_log 
            (admin_id, action, entity_type, entity_id, details, ip_address, user_agent)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            admin_id, 
            action, 
            entity_type, 
            entity_id, 
            json.dumps(details) if details else None,
            request.remote_addr,
            request.user_agent.string if request.user_agent else None
        )
    )
    
    conn.commit()
    cursor.close()
    return_db_connection(conn)

@admin_routes.route('/audit_log')
@admin_required
def audit_log():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cursor.execute(
        """
        SELECT COUNT(*) FROM admin_audit_log
        """
    )
    total_count = cursor.fetchone()[0]
    
    cursor.execute(
        """
        SELECT 
            al.*,
            u.email as admin_email
        FROM admin_audit_log al
        JOIN users u ON al.admin_id = u.id
        ORDER BY al.created_at DESC
        LIMIT %s OFFSET %s
        """,
        (per_page, (page - 1) * per_page)
    )
    
    logs = cursor.fetchall()
    cursor.close()
    return_db_connection(conn)
    
    return render_template("admin/audit_log.html",
                          logs=logs,
                          page=page,
                          per_page=per_page,
                          total_count=total_count,
                          total_pages=(total_count + per_page - 1) // per_page)

@admin_routes.route('/burn_certificates')
@admin_required
def burn_certificates():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    # Get filter parameters
    recipient = request.args.get('recipient', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    # Build query with filters
    query = """
        SELECT bc.*, u.email as user_email
        FROM burn_certificates bc
        JOIN users u ON bc.user_id = u.id
        WHERE 1=1
    """
    
    params = []
    
    if recipient:
        query += " AND bc.recipient_name ILIKE %s"
        params.append(f"%{recipient}%")
    
    if start_date:
        query += " AND bc.burn_date >= %s"
        params.append(start_date)
    
    if end_date:
        query += " AND bc.burn_date <= %s"
        params.append(end_date + " 23:59:59")
    
    query += " ORDER BY bc.burn_date DESC"
    
    cursor.execute(query, params)
    certificates = cursor.fetchall()
    
    # Get total burned
    cursor.execute("SELECT SUM(amount) FROM burn_certificates")
    total_burned = cursor.fetchone()[0] or 0
    
    # Get burn rate data for chart
    cursor.execute("""
        SELECT 
            DATE_TRUNC('day', burn_date) as burn_day,
            SUM(amount) as daily_amount
        FROM burn_certificates
        GROUP BY burn_day
        ORDER BY burn_day
        LIMIT 30
    """)
    burn_stats = cursor.fetchall()
    
    burn_dates = [stat['burn_day'].strftime('%Y-%m-%d') for stat in burn_stats]
    burn_amounts = [float(stat['daily_amount']) for stat in burn_stats]
    
    conn.commit()
    cursor.close()
    return_db_connection(conn)
    
    return render_template("admin/burn_certificates.html", 
                          certificates=certificates,
                          total_burned=total_burned,
                          burn_dates=burn_dates,
                          burn_amounts=burn_amounts)

@admin_routes.route('/view_certificate/<int:certificate_id>')
@admin_required
def view_certificate(certificate_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cursor.execute("""
        SELECT bc.*, u.email as user_email
        FROM burn_certificates bc
        JOIN users u ON bc.user_id = u.id
        WHERE bc.id = %s
    """, (certificate_id,))
    
    certificate = cursor.fetchone()
    
    if not certificate:
        flash("Certificate not found.", "danger")
        return redirect(url_for("admin_routes.burn_certificates"))
    
    # Calculate environmental impact
    kwh_equivalent = certificate["amount"] * 10  # 1 VEC = 10 kWh
    co2_avoided = kwh_equivalent * 0.7  # 0.7 kg CO2 per kWh
    
    conn.commit()
    cursor.close()
    return_db_connection(conn)
    
    return render_template("admin/view_certificate.html", 
                          certificate=certificate,
                          kwh_equivalent=kwh_equivalent,
                          co2_avoided=co2_avoided)

@admin_routes.route('/token_supply')
@admin_required
def token_supply():
    # Get existing data
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    # Get total minted (all tokens created)
    cursor.execute("""
        SELECT SUM(amount) as total
        FROM transactions
        WHERE sender_id = 1  -- System account
        AND transaction_type != 'minting_fee'
    """)
    total_minted = cursor.fetchone()['total'] or 0
    
    # Get total burned
    cursor.execute("SELECT SUM(amount) FROM burn_certificates")
    total_burned = cursor.fetchone()[0] or 0
    
    # Get circulating supply (minted minus burned)
    circulating_supply = total_minted - total_burned
    
    # Projection period
    projection_months = request.args.get('projection', 6, type=int)
    
    # Get growth rates for projections
    cursor.execute("""
        WITH monthly_data AS (
            SELECT 
                DATE_TRUNC('month', transaction_date) as month,
                SUM(CASE WHEN sender_id = 1 AND transaction_type != 'minting_fee' 
                         THEN amount ELSE 0 END) as minted,
                0 as burned
            FROM transactions
            GROUP BY month
            
            UNION ALL
            
            SELECT
                DATE_TRUNC('month', burn_date) as month,
                0 as minted,
                SUM(amount) as burned
            FROM burn_certificates
            GROUP BY month
        ),
        monthly_totals AS (
            SELECT
                month,
                SUM(minted) as minted,
                SUM(burned) as burned
            FROM monthly_data
            GROUP BY month
            ORDER BY month
        ),
        growth_rates AS (
            SELECT
                AVG(
                    CASE 
                        WHEN LAG(minted) OVER (ORDER BY month) > 0 
                        THEN minted / LAG(minted) OVER (ORDER BY month)
                        ELSE 1
                    END
                ) as avg_mint_growth,
                AVG(
                    CASE 
                        WHEN LAG(burned) OVER (ORDER BY month) > 0 
                        THEN burned / LAG(burned) OVER (ORDER BY month)
                        ELSE 1
                    END
                ) as avg_burn_growth
            FROM monthly_totals
            WHERE month > NOW() - INTERVAL '6 months'
        )
        SELECT * FROM growth_rates
    """)
    
    growth_rates = cursor.fetchone()
    avg_mint_growth = float(growth_rates['avg_mint_growth'] if growth_rates and growth_rates['avg_mint_growth'] else 1.0)
    avg_burn_growth = float(growth_rates['avg_burn_growth'] if growth_rates and growth_rates['avg_burn_growth'] else 1.0)
    
    # Get latest monthly values
    cursor.execute("""
        SELECT
            COALESCE(
                (SELECT SUM(amount) FROM transactions 
                 WHERE transaction_date > DATE_TRUNC('month', NOW())
                 AND sender_id = 1 AND transaction_type != 'minting_fee'),
                0
            ) as current_month_minted,
            COALESCE(
                (SELECT SUM(amount) FROM burn_certificates
                 WHERE burn_date > DATE_TRUNC('month', NOW())),
                0
            ) as current_month_burned
    """)
    
    current_values = cursor.fetchone()
    latest_minted = float(current_values['current_month_minted'] if current_values else 0)
    latest_burned = float(current_values['current_month_burned'] if current_values else 0)
    
    # Generate projections
    projection_months_labels = []
    projected_minted = []
    projected_burned = []
    projected_supply = []
    
    current_date = datetime.datetime.now()
    running_supply = circulating_supply
    running_minted = latest_minted
    running_burned = latest_burned
    
    for i in range(projection_months):
        next_month = current_date + datetime.timedelta(days=30 * (i + 1))
        month_label = next_month.strftime("%Y-%m")
        
        # Apply growth rate
        running_minted = running_minted * avg_mint_growth
        running_burned = running_burned * avg_burn_growth
        
        # Update running supply
        running_supply = running_supply + running_minted - running_burned
        
        projection_months_labels.append(month_label)
        projected_minted.append(round(running_minted, 2))
        projected_burned.append(round(running_burned, 2))
        projected_supply.append(round(running_supply, 2))
    
    cursor.close()
    return_db_connection(conn)
    
    # Add to your template context
    return render_template("admin/token_supply.html",
                          total_minted=total_minted,
                          total_burned=total_burned,
                          circulating_supply=circulating_supply,
                          projection_months_labels=projection_months_labels,
                          projected_minted=projected_minted,
                          projected_burned=projected_burned,
                          projected_supply=projected_supply,
                          avg_mint_growth=avg_mint_growth,
                          avg_burn_growth=avg_burn_growth)

@admin_routes.route('/toggle_admin/<int:user_id>', methods=["POST"])
@admin_required
def toggle_admin(user_id):
    # Don't allow toggling your own admin status
    if user_id == session["user_id"]:
        flash("You cannot change your own admin status.", "danger")
        return redirect(url_for("admin_routes.users"))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get current admin status
    cursor.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("admin_routes.users"))
    
    # Toggle admin status
    new_status = not user[0]
    cursor.execute("UPDATE users SET is_admin = %s WHERE id = %s", (new_status, user_id))
    
    conn.commit()
    cursor.close()
    return_db_connection(conn)
    
    # Log the action
    log_admin_action(
        admin_id=session["user_id"],
        action="toggle_admin",
        entity_type="user",
        entity_id=user_id,
        details={"new_status": new_status}
    )
    
    flash(f"User admin status updated successfully.", "success")
    return redirect(url_for("admin_routes.users"))

@admin_routes.route('/impersonate/<int:user_id>')
@admin_required
def impersonate_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    # Check if user exists
    cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    
    cursor.close()
    return_db_connection(conn)
    
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("admin_routes.users"))
    
    # Store original admin info
    session['admin_user_id'] = session['user_id']
    session['admin_email'] = session['email']
    
    # Set session to impersonated user
    session['user_id'] = user_id
    session['email'] = user['email']
    session['is_impersonating'] = True
    
    # Log this action
    log_admin_action(
        admin_id=session['admin_user_id'],
        action="impersonate",
        entity_type="user",
        entity_id=user_id
    )
    
    flash(f"You are now viewing the system as {user['email']}. Click 'End Impersonation' to return to admin view.", "info")
    return redirect(url_for("dashboard"))

@admin_routes.route('/stop_impersonation')
def stop_impersonation():
    if 'admin_user_id' in session and session.get('is_impersonating'):
        # Restore admin session
        session['user_id'] = session['admin_user_id']
        session['email'] = session['admin_email']
        
        # Clean up session
        session.pop('admin_user_id', None)
        session.pop('admin_email', None)
        session.pop('is_impersonating', None)
        
        flash("You have returned to admin view.", "success")
        return redirect(url_for("admin_routes.dashboard"))
    
    return redirect(url_for("dashboard"))