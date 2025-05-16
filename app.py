from flask import Flask, request, jsonify
import os
import paypalrestsdk
import json
from datetime import datetime
import uuid
import logging

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure PayPal SDK
# In production, these would be environment variables
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "YOUR_PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "YOUR_PAYPAL_CLIENT_SECRET")
PAYPAL_MODE = os.environ.get("PAYPAL_MODE", "sandbox")  # Use 'live' for production

# Configure PayPal SDK
paypalrestsdk.configure({
    "mode": PAYPAL_MODE,
    "client_id": PAYPAL_CLIENT_ID,
    "client_secret": PAYPAL_CLIENT_SECRET
})

# In-memory database for demo purposes
# In production, use a real database like PostgreSQL
centers_db = {}
donations_db = {}

# Load initial centers data
def init_centers_db():
    TARGET_CITIES = {
        "Canada": ["Vancouver", "Toronto", "Montreal"],
        "USA": ["San Francisco", "Los Angeles", "New York"]
    }
    FUNDING_GOAL_PER_CENTER = 200000  # $200k per center

    for country, cities in TARGET_CITIES.items():
        for city in cities:
            center_id = f"{city.lower().replace(' ', '_')}_{country.lower()}"
            centers_db[center_id] = {
                "id": center_id,
                "name": f"{city} Suicide Prevention Center",
                "location": {"city": city, "country": country},
                "funds_raised": 0,
                "goal": FUNDING_GOAL_PER_CENTER,
                "donors": 0,
                "last_donation": None,
                "created_at": datetime.now().isoformat()
            }
    
    logger.info(f"Initialized {len(centers_db)} centers in database")

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "message": "Suicide Prevention Fundraising API is running",
        "endpoints": [
            "/centers - GET all centers",
            "/centers/<center_id> - GET center details",
            "/process_donation - POST to process donation",
            "/create_payment - POST to create PayPal payment",
            "/execute_payment - POST to execute PayPal payment",
            "/donations - GET all donations (admin only)",
            "/donations/<donation_id> - GET donation details (admin only)"
        ]
    })

@app.route("/centers", methods=["GET"])
def get_all_centers():
    return jsonify({
        "status": "success",
        "centers": list(centers_db.values())
    })

@app.route("/centers/<center_id>", methods=["GET"])
def get_center(center_id):
    if center_id in centers_db:
        return jsonify({
            "status": "success",
            "center": centers_db[center_id]
        })
    else:
        return jsonify({
            "status": "error",
            "message": f"Center with ID {center_id} not found"
        }), 404

@app.route("/process_donation", methods=["POST"])
def process_donation():
    data = request.json
    
    # Validate request data
    required_fields = ["center_id", "amount", "donor_name", "payment_method"]
    for field in required_fields:
        if field not in data:
            return jsonify({
                "status": "error",
                "message": f"Missing required field: {field}"
            }), 400
    
    center_id = data["center_id"]
    amount = float(data["amount"])
    
    # Validate center exists
    if center_id not in centers_db:
        return jsonify({
            "status": "error",
            "message": f"Center with ID {center_id} not found"
        }), 404
    
    # Validate amount
    if amount < 10:
        return jsonify({
            "status": "error",
            "message": "Minimum donation amount is $10"
        }), 400
    
    try:
        # Create donation record
        donation_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        donation = {
            "id": donation_id,
            "center_id": center_id,
            "amount": amount,
            "donor_name": data["donor_name"],
            "payment_method": data["payment_method"],
            "status": "pending",
            "created_at": timestamp
        }
        
        # Store in our donation database
        donations_db[donation_id] = donation
        
        # Update center data
        centers_db[center_id]["funds_raised"] += amount
        centers_db[center_id]["donors"] += 1
        centers_db[center_id]["last_donation"] = timestamp
        
        logger.info(f"Processed donation {donation_id} for {amount} to {center_id}")
        
        return jsonify({
            "status": "success",
            "donation_id": donation_id,
            "message": f"Thank you for your donation of ${amount} to {centers_db[center_id]['name']}!",
            "center": centers_db[center_id]
        })
        
    except Exception as e:
        logger.error(f"Error processing donation: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error processing donation: {str(e)}"
        }), 500

@app.route("/create_payment", methods=["POST"])
def create_payment():
    """Creates a PayPal payment"""
    data = request.json
    
    # Validate request data
    required_fields = ["center_id", "amount", "return_url", "cancel_url"]
    for field in required_fields:
        if field not in data:
            return jsonify({
                "status": "error",
                "message": f"Missing required field: {field}"
            }), 400
    
    center_id = data["center_id"]
    amount = float(data["amount"])
    return_url = data["return_url"]
    cancel_url = data["cancel_url"]
    
    # Validate center exists
    if center_id not in centers_db:
        return jsonify({
            "status": "error",
            "message": f"Center with ID {center_id} not found"
        }), 404
    
    try:
        # Create PayPal payment
        payment = paypalrestsdk.Payment({
            "intent": "sale",
            "payer": {
                "payment_method": "paypal"
            },
            "redirect_urls": {
                "return_url": return_url,
                "cancel_url": cancel_url
            },
            "transactions": [{
                "item_list": {
                    "items": [{
                        "name": f"Donation to {centers_db[center_id]['name']}",
                        "sku": center_id,
                        "price": str(amount),
                        "currency": "USD",
                        "quantity": 1
                    }]
                },
                "amount": {
                    "total": str(amount),
                    "currency": "USD"
                },
                "description": f"Donation to support {centers_db[center_id]['name']}"
            }]
        })
        
        # Create the payment in PayPal
        if payment.create():
            # Extract approval URL to redirect the user
            for link in payment.links:
                if link.rel == "approval_url":
                    approval_url = link.href
                    payment_id = payment.id
                    
                    logger.info(f"Created PayPal payment {payment_id} for {amount} to {center_id}")
                    
                    return jsonify({
                        "status": "success",
                        "payment_id": payment_id,
                        "approval_url": approval_url
                    })
        else:
            logger.error(f"Failed to create PayPal payment: {payment.error}")
            return jsonify({
                "status": "error",
                "message": "Failed to create PayPal payment",
                "details": payment.error
            }), 500
            
    except Exception as e:
        logger.error(f"Error creating PayPal payment: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error creating PayPal payment: {str(e)}"
        }), 500

@app.route("/execute_payment", methods=["POST"])
def execute_payment():
    """Executes a PayPal payment after user approval"""
    data = request.json
    
    # Validate request data
    required_fields = ["payment_id", "payer_id", "center_id", "donor_name"]
    for field in required_fields:
        if field not in data:
            return jsonify({
                "status": "error",
                "message": f"Missing required field: {field}"
            }), 400
    
    payment_id = data["payment_id"]
    payer_id = data["payer_id"]
    center_id = data["center_id"]
    donor_name = data["donor_name"]
    
    try:
        # Fetch the payment from PayPal
        payment = paypalrestsdk.Payment.find(payment_id)
        
        # Execute the payment
        if payment.execute({"payer_id": payer_id}):
            # Get transaction info
            amount = float(payment.transactions[0].amount.total)
            
            # Create donation record
            donation_id = str(uuid.uuid4())
            timestamp = datetime.now().isoformat()
            
            donation = {
                "id": donation_id,
                "center_id": center_id,
                "amount": amount,
                "donor_name": donor_name,
                "payment_method": "paypal",
                "payment_id": payment_id,
                "payer_id": payer_id,
                "status": "completed",
                "created_at": timestamp
            }
            
            # Store in our donation database
            donations_db[donation_id] = donation
            
            # Update center data
            centers_db[center_id]["funds_raised"] += amount
            centers_db[center_id]["donors"] += 1
            centers_db[center_id]["last_donation"] = timestamp
            
            logger.info(f"Executed PayPal payment {payment_id} for {amount} to {center_id}")
            
            return jsonify({
                "status": "success",
                "donation_id": donation_id,
                "message": f"Thank you for your donation of ${amount} to {centers_db[center_id]['name']}!",
                "center": centers_db[center_id]
            })
        else:
            logger.error(f"Failed to execute PayPal payment: {payment.error}")
            return jsonify({
                "status": "error",
                "message": "Failed to execute PayPal payment",
                "details": payment.error
            }), 500
            
    except Exception as e:
        logger.error(f"Error executing PayPal payment: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error executing PayPal payment: {str(e)}"
        }), 500

@app.route("/donations", methods=["GET"])
def get_all_donations():
    # In production, this would require authentication
    return jsonify({
        "status": "success",
        "donations": list(donations_db.values())
    })

@app.route("/donations/<donation_id>", methods=["GET"])
def get_donation(donation_id):
    # In production, this would require authentication
    if donation_id in donations_db:
        return jsonify({
            "status": "success",
            "donation": donations_db[donation_id]
        })
    else:
        return jsonify({
            "status": "error",
            "message": f"Donation with ID {donation_id} not found"
        }), 404

# Initialize the database when the app starts
@app.before_first_request
def before_first_request():
    init_centers_db()

if __name__ == "__main__":
    # Initialize the database
    init_centers_db()
    
    # Get port from environment variable or use default
    port = int(os.environ.get("PORT", 5000))
    
    # Run the app
    app.run(host="0.0.0.0", port=port)
