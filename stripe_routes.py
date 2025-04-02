"""
Stripe integration routes for the VEC platform.
This file contains all routes related to Stripe payments and webhooks.
"""

import os
import stripe
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, session, flash
from functools import wraps

# Import your database connection function
from app import get_db_connection, login_required

# Initialize Stripe with your API key
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
stripe_publishable_key = os.environ.get("STRIPE_PUBLISHABLE_KEY")

# Create a blueprint for Stripe routes
stripe_routes = Blueprint('stripe', __name__)

@stripe_routes.route("/buy_credits")
@login_required
def buy_credits():
    """Display the credit purchase page with Stripe integration"""
    if "user_id" not in session:
        flash("You must be logged in to buy credits.", "warning")
        return redirect(url_for("login"))
    
    user_id = session["user_id"]
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Calculate user balance
    cursor.execute("""
        SELECT
            COALESCE((SELECT SUM(amount) FROM transactions WHERE receiver_id = %s), 0) AS total_received,
            COALESCE((SELECT SUM(amount) FROM transactions WHERE sender_id = %s), 0) AS total_sent
    """, (user_id, user_id))
    
    balance_result = cursor.fetchone()
    user_balance = balance_result[0] - balance_result[1]
    
    cursor.close()
    conn.close()
    
    return render_template(
        "buy_credits.html", 
        email=session.get("email", ""), 
        balance=user_balance,
        stripe_publishable_key=stripe_publishable_key
    )

@stripe_routes.route("/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    """Create a Stripe checkout session for purchasing VEC credits"""
    if "user_id" not in session:
        return jsonify({"error": "Not authenticated"}), 403

    data = request.get_json()
    package = data.get("package")

    # Map package to amount and price
    packages = {
        "100": {"credits": 100, "amount": 50000},  # $500.00 in cents
        "500": {"credits": 500, "amount": 250000}, # $2,500.00 in cents
        "1000": {"credits": 1000, "amount": 500000} # $5,000.00 in cents
    }

    if package not in packages:
        return jsonify({"error": "Invalid package selected"}), 400

    try:
        # Create a Stripe checkout session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": f"{packages[package]['credits']} VEC Credits",
                            "description": "Renewable Energy Credits"
                        },
                        "unit_amount": packages[package]["amount"],
                    },
                    "quantity": 1,
                },
            ],
            mode="payment",
            success_url=url_for("stripe.payment_success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for("stripe.payment_cancel", _external=True),
            metadata={
                "user_id": session["user_id"],
                "credits": packages[package]["credits"],
                "package": package
            }
        )
        
        return jsonify({"id": checkout_session.id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@stripe_routes.route("/webhook", methods=["POST"])
def webhook():
    """Handle Stripe webhooks, especially for completed payments"""
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        # Invalid payload
        return jsonify({"error": str(e)}), 400
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return jsonify({"error": str(e)}), 400

    # Handle the checkout.session.completed event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        
        # Get metadata
        user_id = session["metadata"]["user_id"]
        credits = int(session["metadata"]["credits"])
        
        # Process the payment (add credits to user)
        handle_successful_payment(user_id, credits)
    
    return jsonify({"status": "success"})

def handle_successful_payment(user_id, credits):
    """Add credits to user account after successful payment"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # System account that represents credit creation
        system_id = 1  # Adjust as needed
        
        # Record transaction
        cursor.execute(
            "INSERT INTO transactions (sender_id, receiver_id, amount, transaction_type) VALUES (%s, %s, %s, %s)",
            (system_id, user_id, credits, "purchase")
        )
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return True
    except Exception as e:
        print(f"Error processing payment: {e}")
        return False

@stripe_routes.route("/payment_success")
def payment_success():
    """Handle successful payments"""
    session_id = request.args.get("session_id")
    
    if session_id:
        try:
            # Verify the session (optional additional security)
            session = stripe.checkout.Session.retrieve(session_id)
            
            if session and session.payment_status == "paid":
                flash("Payment successful! Your VEC credits have been added to your account.", "success")
            else:
                flash("Payment is being processed. Credits will be added soon.", "info")
        except Exception as e:
            print(f"Error verifying session: {e}")
    else:
        flash("Payment was successful! Your credits will be added shortly.", "success")
    
    return redirect(url_for("dashboard"))

@stripe_routes.route("/payment_cancel")
def payment_cancel():
    """Handle canceled payments"""
    flash("Payment was canceled. No charges were made.", "warning")
    return redirect(url_for("stripe.buy_credits"))