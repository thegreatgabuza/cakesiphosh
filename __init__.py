import os
from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager
import firebase_admin
from firebase_admin import credentials, firestore

# Load environment variables
load_dotenv()

# Initialize Flask
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

# Initialize Firebase
try:
    # Check if Firebase is already initialized
    if not firebase_admin._apps:
        # Use the JSON credentials file directly instead of building the dict
        print("Attempting to initialize Firebase with credentials file...")
        cred = credentials.Certificate('firebase-key.json')
        firebase_admin.initialize_app(cred)
        print("Firebase initialized successfully!")
    else:
        print("Firebase already initialized, reusing existing connection")
    
    db = firestore.client()
    
except Exception as e:
    print(f"Firebase initialization error: {str(e)}")
    print("Check that firebase-key.json exists and contains valid credentials")
    raise

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Add custom template filters
@app.template_filter('zip')
def zip_filter(a, b):
    """Template filter to zip two lists together for iteration"""
    # Ensure both inputs are lists/iterables with fallbacks
    a = a if a is not None else []
    b = b if b is not None else []
    return zip(a, b)

@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.get(user_id)

# Import routes after app initialization
from routes import * 