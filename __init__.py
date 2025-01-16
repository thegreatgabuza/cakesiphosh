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
    # Get the private key from environment and properly format it
    private_key = os.getenv('FIREBASE_PRIVATE_KEY')
    if not private_key:
        raise ValueError("FIREBASE_PRIVATE_KEY is not set in environment variables")
    
    # Remove quotes and replace literal \n with newlines
    private_key = private_key.replace('"', '').replace('\\n', '\n')
    
    # Get other required credentials
    project_id = os.getenv('FIREBASE_PROJECT_ID')
    if not project_id:
        raise ValueError("FIREBASE_PROJECT_ID is not set in environment variables")
        
    client_email = os.getenv('FIREBASE_CLIENT_EMAIL')
    if not client_email:
        raise ValueError("FIREBASE_CLIENT_EMAIL is not set in environment variables")
    
    # Create the credentials dictionary
    cred_dict = {
        "type": "service_account",
        "project_id": project_id,
        "private_key_id": os.getenv('FIREBASE_PRIVATE_KEY_ID'),
        "private_key": private_key,
        "client_email": client_email,
        "client_id": os.getenv('FIREBASE_CLIENT_ID'),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": os.getenv('FIREBASE_CLIENT_X509_CERT_URL')
    }
    
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase initialized successfully!")
    
except Exception as e:
    print(f"Firebase initialization error: {str(e)}")
    print("Environment variables available:")
    for key in ['FIREBASE_PROJECT_ID', 'FIREBASE_CLIENT_EMAIL', 'FIREBASE_PRIVATE_KEY_ID']:
        print(f"{key}: {'Set' if os.getenv(key) else 'Not set'}")
    raise

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.get(user_id)

# Import routes after app initialization
from routes import * 