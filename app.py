
from functools import wraps
from flask import session, redirect, url_for

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_session import Session
import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash, check_password_hash
from decimal import Decimal
import os
import csv
from werkzeug.utils import secure_filename
from admin_routes import admin_routes


# Define Flask app
app = Flask(__name__, static_url_path='/static', static_folder='static')



# Configure Flask Sessions
app.secret_key = "supersecretkey"
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

app.register_blueprint(admin_routes)
import os
import psycopg2
import urllib.parse as urlparse

def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if db_url is None:
        raise ValueError("DATABASE_URL is not set.")
    return psycopg2.connect(db_url)



# Triggering redeploy on Railway

def init_db():
    with app.app_context():
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
                    password_hash VARCHAR(255) NOT NULL,
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
            
            # Create system users
            admin_password = generate_password_hash("admin123")
            system_password = generate_password_hash("system123")
            burn_password = generate_password_hash("burn123")
            
            cursor.execute("""
                INSERT INTO users (email, password_hash, first_name, last_name, is_admin) 
                VALUES ('system@vec-system.com', %s, 'System', 'Account', false)
            """, (system_password,))
            
            cursor.execute("""
                INSERT INTO users (email, password_hash, first_name, last_name, is_admin) 
                VALUES ('admin@vec-system.com', %s, 'Admin', 'Account', true)
            """, (admin_password,))
            
            cursor.execute("""
                INSERT INTO users (email, password_hash, first_name, last_name, is_admin) 
                VALUES ('burn@vec-system.com', %s, 'Burn', 'Account', false)
            """, (burn_password,))
            
            # Set initial fee structure
            cursor.execute("""
                INSERT INTO fee_structure (fee_type, rate) VALUES
                ('trading', 0.015),
                ('verification', 0.01),
                ('minting', 0.02)
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

@app.route("/marketplace")
def marketplace():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Get all open buy/sell orders
    cursor.execute("SELECT order_type, price, amount FROM orders WHERE status = 'open' ORDER BY price ASC")
    orders = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("marketplace.html", orders=orders)

@app.route("/test_db")
def test_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1")  # Or any small query
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return f"DB Connected! Result: {result}"


@app.route("/place_order", methods=["POST"])
def place_order():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

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

    # ✅ FIXED: Match orders after placing a new one
    match_orders()

    return jsonify({"message": "Order placed successfully!", "order_id": order_id})

# ✅ FIXED: Properly structured order matching function
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

# ✅ FIXED: Initialize the database properly

# ✅ FIXED: Ensure database initializes only on startup

# Then call it after defining it
with app.app_context():
    init_db()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        print(f"🔍 Attempting login for: {email}")

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            
            if user and check_password_hash(user["password_hash"], password):
                session["user_id"] = user["id"]
                session["email"] = user["email"]
                flash("Login successful!", "success")
                return redirect(url_for("dashboard"))
            else:
                flash("Invalid email or password.", "danger")
                
        except Exception as e:
            conn.rollback()
            print(f"Login error: {e}")
            flash("A database error occurred. Please try again.", "danger")
            
        finally:
            cursor.close()
            conn.close()
    
    return render_template("login.html")


@app.route("/")
def home():
    return redirect(url_for("login"))  # Redirects to the login page
@app.route("/logout")
def logout():
    session.clear()  # Clears session data (logs out user)
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        first_name = request.form["first_name"]
        last_name = request.form["last_name"]
        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (email, password_hash, first_name, last_name) VALUES (%s, %s, %s, %s)", 
                           (email, hashed_password, first_name, last_name))
            conn.commit()
            flash("Registration successful! You can now log in.", "success")
            return redirect(url_for("login"))
        except psycopg2.Error:
            flash("Email already registered.", "danger")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

    return render_template("register.html")

@app.route("/order_book")
def order_book():
    open_orders = Order.query.filter_by(status="open").order_by(Order.price).all()
    return jsonify([
        {
            "order_type": o.order_type,
            "price": o.price,
            "amount": o.amount
        } for o in open_orders
    ])


@app.route("/send_credits_page", methods=["GET"])
def send_credits_page():
    if "user_id" not in session:
        flash("You must be logged in to send credits.", "warning")
        return redirect(url_for("login"))
    
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
    
    return render_template("send_credits.html", email=session["email"], balance=user_balance)

# 3. Fix duplicate energy_data processing and implement the missing data processing functions
def process_transaction_data(filepath, user_id):
    with open(filepath, 'r') as csvfile:
        csvreader = csv.DictReader(csvfile)
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            for row in csvreader:
                try:
                    sender_email = row.get('sender_email')
                    receiver_email = row.get('receiver_email')
                    amount = float(row.get('amount', 0))
                    
                    # Find user IDs based on emails
                    cursor.execute("SELECT id FROM users WHERE email = %s", (sender_email,))
                    sender_result = cursor.fetchone()
                    
                    cursor.execute("SELECT id FROM users WHERE email = %s", (receiver_email,))
                    receiver_result = cursor.fetchone()
                    
                    if sender_result and receiver_result:
                        sender_id = sender_result[0]
                        receiver_id = receiver_result[0]
                        
                        # Record the transaction
                        cursor.execute("""
                            INSERT INTO transactions (sender_id, receiver_id, amount, transaction_type)
                            VALUES (%s, %s, %s, %s)
                        """, (sender_id, receiver_id, amount, 'imported'))
                        
                except Exception as e:
                    print(f"Error processing row: {e}")
                    continue
                    
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            print(f"Transaction import error: {e}")
            
        finally:
            cursor.close()
            conn.close()

def process_user_data(filepath):
    with open(filepath, 'r') as csvfile:
        csvreader = csv.DictReader(csvfile)
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            for row in csvreader:
                try:
                    email = row.get('email')
                    first_name = row.get('first_name')
                    last_name = row.get('last_name')
                    password = row.get('password')
                    
                    # Check if user already exists
                    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                    if cursor.fetchone():
                        print(f"User {email} already exists, skipping.")
                        continue
                    
                    # Create a hashed password
                    hashed_password = generate_password_hash(password)
                    
                    # Insert the new user
                    cursor.execute("""
                        INSERT INTO users (email, password_hash, first_name, last_name) 
                        VALUES (%s, %s, %s, %s)
                    """, (email, hashed_password, first_name, last_name))
                    
                except Exception as e:
                    print(f"Error processing user row: {e}")
                    continue
                    
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            print(f"User import error: {e}")
            
        finally:
            cursor.close()
            conn.close()

# 4. Fix process_energy_data function by removing the duplicated code
def process_energy_data(filepath, user_id):
    with open(filepath, 'r') as csvfile:
        csvreader = csv.DictReader(csvfile)
        conn = get_db_connection()
        cursor = conn.cursor()

        system_id = 1  # System account ID
        admin_id = 2   # Admin account ID for collecting fees

        # Get current fee rates
        cursor.execute("SELECT fee_type, rate FROM fee_structure ORDER BY effective_date DESC LIMIT 3")
        fees = {row[0]: row[1] for row in cursor.fetchall()}

        verification_fee = fees.get('verification', 0.01)  # Default to $0.01 per kWh if not found
        minting_fee_rate = fees.get('minting', 0.02)      # Default to 2% if not found

        for row in csvreader:
            try:
                kwh_produced = float(row.get('kwh_produced', 0))

                total_verification_fee = kwh_produced * verification_fee
                vec_credits_gross = kwh_produced / 10
                minting_fee = vec_credits_gross * minting_fee_rate
                vec_credits_net = vec_credits_gross - minting_fee

                cursor.execute(
                    "INSERT INTO transactions (sender_id, receiver_id, amount) VALUES (%s, %s, %s)",
                    (system_id, user_id, vec_credits_net)
                )
                cursor.execute(
                    "INSERT INTO transactions (sender_id, receiver_id, amount, transaction_type) VALUES (%s, %s, %s, %s)",
                    (system_id, admin_id, minting_fee, 'minting_fee')
                )

            except Exception as e:
                print(f"Error processing row: {e}")
                continue

        conn.commit()
        cursor.close()
        conn.close()



@app.route("/buy_credits", methods=["GET"])
def buy_credits():
    if "user_id" not in session:
        flash("You must be logged in to buy credits.", "warning")
        return redirect(url_for("login"))
    
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
    
    return render_template("buy_credits.html", email=session["email"], balance=user_balance)


@app.route("/send_credits", methods=["POST"])
def send_credits():
    if "user_id" not in session:
        flash("You must be logged in to send credits.", "warning")
        return redirect(url_for("login"))

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
        return redirect(url_for("send_credits"))

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
        return redirect(url_for("send_credits"))

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
    return redirect(url_for("dashboard"))


@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

# Add this route specifically for favicon
@app.route('/favicon.ico')
def favicon():
    return send_from_directory('static', 'favicon.ico')


@app.route("/dashboard-analytics")  # Renamed route
def dashboard_analytics():
    return render_template("dashboard-analytics.html")

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

@app.route("/admin/dashboard")
def admin_dashboard():
    if "user_id" not in session or session["user_id"] != 2:  # Assuming admin ID = 2
        flash("Unauthorized access.", "danger")
        return redirect(url_for("dashboard"))

    return render_template("admin_dashboard.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        flash("You must be logged in to view this page.", "warning")
        return redirect(url_for("login"))

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
        vec_price = get_current_vec_price()

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
        return redirect(url_for("login"))
        
    finally:
        cursor.close()
        conn.close()


@app.route("/process_purchase", methods=["POST"])
def process_purchase():
    if "user_id" not in session:
        flash("You must be logged in to complete this purchase.", "warning")
        return redirect(url_for("login"))
    
    package = request.form["package"]
    
    if package == "100":
        credits = 100
        amount = 500.00
    elif package == "500":
        credits = 500
        amount = 2500.00
    elif package == "1000":
        credits = 1000
        amount = 5000.00
    else:
        flash("Invalid package selected", "danger")
        return redirect(url_for("buy_credits"))

    user_id = session["user_id"]
    system_id = 1  # Assuming system account ID is 1

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # ✅ Fixed: Now executing the transaction properly
        cursor.execute(
            "INSERT INTO transactions (sender_id, receiver_id, amount) VALUES (%s, %s, %s)",
            (system_id, user_id, credits)
        )
        conn.commit()
        flash(f"Successfully purchased {credits} VEC credits for ${amount:.2f}!", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Purchase failed: {e}", "danger")
        
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("dashboard"))



UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create uploads directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if "user_id" not in session:
        flash("You must be logged in to upload data.", "warning")
        return redirect(url_for("login"))
    
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        upload_type = request.form.get('upload_type')
        
        # If user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Read and preview the CSV file
            preview_data = []
            with open(filepath, 'r') as csvfile:
                csvreader = csv.reader(csvfile)
                for row in csvreader:
                    preview_data.append(row)
                    if len(preview_data) >= 6:  # Preview only first 5 rows + header
                        break
            
            return render_template('upload.html', 
                                  email=session["email"],
                                  preview_data=preview_data,
                                  filename=filename,
                                  upload_type=upload_type)
    
    return render_template('upload.html', email=session["email"])

@app.route('/process_upload', methods=['POST'])
def process_upload():
    if "user_id" not in session:
        flash("You must be logged in to process uploads.", "warning")
        return redirect(url_for("login"))
    
    filename = request.form.get('filename')
    upload_type = request.form.get('upload_type')
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    if not os.path.exists(filepath):
        flash("File not found", "danger")
        return redirect(url_for('upload_file'))
    
    # Process based on upload type
    if upload_type == 'energy_production':
        process_energy_data(filepath, session["user_id"])
        flash("Energy production data imported successfully!", "success")
    elif upload_type == 'transaction_history':
        process_transaction_data(filepath, session["user_id"])
        flash("Transaction data imported successfully!", "success")
    elif upload_type == 'user_data':
        process_user_data(filepath)
        flash("User data imported successfully!", "success")
    else:
        flash("Unknown upload type", "danger")
    
    return redirect(url_for('dashboard'))


@app.route("/admin/fees", methods=["GET", "POST"])
def admin_fees():
    # Check if user is admin
    if "user_id" not in session or session["user_id"] != 2:  # Assuming admin_id is 2
        flash("Unauthorized access.", "danger")
        return redirect(url_for("dashboard"))
    
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


# 1. First, add a new route to app.py for burning VECs

@app.route("/burn_credits", methods=["GET", "POST"])
def burn_credits():
    if "user_id" not in session:
        flash("You must be logged in to burn credits.", "warning")
        return redirect(url_for("login"))
    
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
                burn_account_id = 4  # You'll need to create this account in your database
                
                # Insert transaction for burning (transferring to burn account)
                cursor.execute("""
                    INSERT INTO transactions (sender_id, receiver_id, amount, transaction_type) 
                    VALUES (%s, %s, %s, %s)
                """, (user_id, burn_account_id, amount, 'burn'))
                
                # Create certificate record
                cursor.execute("""
                    INSERT INTO burn_certificates (user_id, amount, recipient_name, recipient_email, burn_date)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (user_id, amount, certificate_name, certificate_email))
                
                conn.commit()
                
                # Calculate environmental impact for certificate
                kwh_equivalent = amount * 10  # 1 VEC = 10 kWh
                co2_avoided = kwh_equivalent * 0.7  # 0.7 kg CO2 per kWh
                
                flash(f"Successfully burned {amount} VEC credits! A certificate has been generated.", "success")
                return redirect(url_for("certificate", certificate_id=cursor.lastrowid))
                
            except Exception as e:
                conn.rollback()
                flash(f"An error occurred: {e}", "danger")
    
    cursor.close()
    conn.close()
    
    return render_template("burn_credits.html", balance=user_balance)

# 2. Add a certificate view route
@app.route("/certificate/<int:certificate_id>")
def certificate(certificate_id):
    if "user_id" not in session:
        flash("You must be logged in to view certificates.", "warning")
        return redirect(url_for("login"))
    
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
        return redirect(url_for("dashboard"))
    
    # Calculate environmental impact
    kwh_equivalent = certificate["amount"] * 10  # 1 VEC = 10 kWh
    co2_avoided = kwh_equivalent * 0.7  # 0.7 kg CO2 per kWh
    
    cursor.close()
    conn.close()
    
    return render_template("certificate.html", 
                          certificate=certificate,
                          kwh_equivalent=kwh_equivalent,
                          co2_avoided=co2_avoided)

# 3. Add a route to view all certificates
@app.route("/my_certificates")
def my_certificates():
    if "user_id" not in session:
        flash("You must be logged in to view certificates.", "warning")
        return redirect(url_for("login"))
    
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

# 4. SQL for creating the burn_certificates table (run this in your database)
"""
CREATE TABLE burn_certificates (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    amount DECIMAL(15,2) NOT NULL,
    recipient_name VARCHAR(255) NOT NULL,
    recipient_email VARCHAR(255) NOT NULL,
    burn_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    certificate_hash VARCHAR(64)
);
"""

# 5. Create a special "Burn" account in your database
"""
INSERT INTO users (email, password_hash, first_name, last_name, is_admin) 
VALUES ('burn@vec-system.com', '[generated_hash]', 'Burn', 'Account', false);

-- Note the ID of this account and use it as burn_account_id in the burn_credits route
"""

# Burn VECs Endpoint
@app.route('/burn', methods=['POST']) # For API/JS fetch
@jwt_required()
def burn_certificates():
    data = request.get_json()
    user_id = get_jwt_identity()

    amount = data.get('amount')
    recipient_name = data.get('recipient_name', '')
    recipient_email = data.get('recipient_email', '')
    certificate_hash = data.get('certificate_hash', '')

    if not amount:
        return jsonify({"message": "Amount is required."}), 400

    try:
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO burn_certificates (user_id, amount, recipient_name, recipient_email, certificate_hash)
            VALUES (%s, %s, %s, %s, %s)
        ''', (user_id, amount, recipient_name, recipient_email, certificate_hash))
        conn.commit()
        cur.close()
        return jsonify({"message": "VECs burned successfully."}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"message": f"Error burning VECs: {str(e)}"}), 500

# Public Burn Summary Endpoint
@app.route('/burn/summary', methods=['GET'])
def burn_summary():
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT recipient_name, recipient_email, SUM(amount) as total
            FROM burn_certificates
            GROUP BY recipient_name, recipient_email
        ''')
        results = cur.fetchall()
        cur.close()
        data = [
            {"recipient_name": row[0], "recipient_email": row[1], "total_kwh": float(row[2])} 
            for row in results
        ]
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"message": f"Error fetching burn summary: {str(e)}"}), 500

# Admin Burn Activity View
@app.route('/admin/burn-activity', methods=['GET']) # For form submission
@jwt_required()
def admin_burn_activity():
    user_id = get_jwt_identity()
    cur = conn.cursor()
    cur.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
    result = cur.fetchone()
    if not result or not result[0]:
        return jsonify({"message": "Unauthorized."}), 403

    try:
        cur.execute('''
            SELECT users.email, bc.amount, bc.recipient_name, bc.recipient_email, bc.burn_date, bc.certificate_hash
            FROM burn_certificates bc
            JOIN users ON bc.user_id = users.id
            ORDER BY bc.burn_date DESC
        ''')
        rows = cur.fetchall()
        cur.close()
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
        return jsonify({"message": f"Error fetching admin data: {str(e)}"}), 

@app.route('/burn', methods=['POST'])
@login_required
def burn_certificates():
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
    """, (user.id, amount, recipient_name, recipient_email, certificate_hash))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({'message': 'Burn recorded successfully.'}), 200

if __name__ == "__main__":
    app.run(debug=True)


