import os
import json
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
        # Try different credential sources in order of preference:
        # 1. Local firebase-key.json file (for local development)
        # 2. Environment variable FIREBASE_CONFIG (for cloud deployment)
        # 3. JSON string environment variable as fallback
        
        if os.path.exists('firebase-key.json'):
            # Use the JSON credentials file if it exists (local development)
            print("Attempting to initialize Firebase with credentials file...")
            cred = credentials.Certificate('firebase-key.json')
            firebase_admin.initialize_app(cred)
            print("Firebase initialized successfully with credentials file!")
        elif os.getenv('FIREBASE_CONFIG'):
            # If we have a JSON config string in environment variable (cloud deployment)
            print("Initializing Firebase with FIREBASE_CONFIG environment variable...")
            firebase_config = json.loads(os.getenv('FIREBASE_CONFIG'))
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred)
            print("Firebase initialized successfully with config environment variable!")
        else:
            # Try to construct credentials from individual environment variables
            print("Initializing Firebase with individual credential environment variables...")
            firebase_credentials = {
                "type": os.getenv("FIREBASE_TYPE", "service_account"),
                "project_id": os.getenv("FIREBASE_PROJECT_ID"),
                "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
                "private_key": os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n"),
                "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
                "client_id": os.getenv("FIREBASE_CLIENT_ID"),
                "auth_uri": os.getenv("FIREBASE_AUTH_URI", "https://accounts.google.com/o/oauth2/auth"),
                "token_uri": os.getenv("FIREBASE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
                "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_CERT_URL", 
                                                         "https://www.googleapis.com/oauth2/v1/certs"),
                "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_CERT_URL")
            }
            
            # Check if we have the minimum required credentials
            if firebase_credentials["project_id"] and firebase_credentials["private_key"] and firebase_credentials["client_email"]:
                cred = credentials.Certificate(firebase_credentials)
                firebase_admin.initialize_app(cred)
                print("Firebase initialized successfully with environment variables!")
            else:
                print("WARNING: Firebase credentials not found in environment variables.")
                print("The application will run with limited functionality.")
                print("Set up Firebase environment variables for full functionality.")
                # Initialize with a blank configuration for limited functionality
                firebase_admin.initialize_app()
                print("Firebase initialized with limited functionality.")
    else:
        print("Firebase already initialized, reusing existing connection")
    
    # Create Firestore client
    db = firestore.client()
    
except Exception as e:
    print(f"Firebase initialization error: {str(e)}")
    print("Application will continue with limited functionality.")
    # Don't raise the exception, allow the app to continue with limited functionality
    db = None

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