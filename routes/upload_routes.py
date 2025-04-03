# routes/upload_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import os
import csv
from werkzeug.utils import secure_filename
import psycopg2
import psycopg2.extras
from utils import get_db_connection, login_required

# Create blueprint
upload_routes = Blueprint('upload_routes', __name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv'}

# Create uploads directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# UPLOAD
@upload_routes.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_file():
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
            filepath = os.path.join(UPLOAD_FOLDER, filename)
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

# PROCESS UPLOAD
@upload_routes.route('/process_upload', methods=['POST'])
@login_required
def process_upload():
    filename = request.form.get('filename')
    upload_type = request.form.get('upload_type')
    
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    
    if not os.path.exists(filepath):
        flash("File not found", "danger")
        return redirect(url_for('upload_routes.upload_file'))
    
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
    
    return redirect(url_for('auth_routes.dashboard'))

# PROCESS ENERGY DATA
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

# PROCESS TRANSACTION DATA
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

# PROCESS USER DATA
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
                    
                    # Check if user already exists
                    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                    if cursor.fetchone():
                        print(f"User {email} already exists, skipping.")
                        continue
                   
                    # Insert the new user
                    cursor.execute("""
                        INSERT INTO users (email, first_name, last_name) 
                        VALUES (%s, %s, %s)
                    """, (email, first_name, last_name))
                    
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