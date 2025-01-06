from dotenv import load_dotenv
import os
import firebase_admin
from firebase_admin import credentials, firestore

# Load environment variables
load_dotenv()

# Get OpenAI API key
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Initialize Firebase Admin SDK with service account
service_account_path = 'serviceAccountKey.json'
cred = credentials.Certificate(service_account_path)
firebase_admin.initialize_app(cred)

# Initialize Firestore
db = firestore.client()

# Flask configuration
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    UPLOAD_FOLDER = 'static/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size