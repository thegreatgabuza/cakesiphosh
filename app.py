from flask import Flask
from flask_login import LoginManager
import firebase_admin
from firebase_admin import credentials, auth
from config import db

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'  # Change this to a secure secret key

# Add zip filter to Jinja2
app.jinja_env.filters['zip'] = zip

# Initialize Firebase Admin SDK if not already initialized
if not firebase_admin._apps:
    cred = credentials.Certificate('path/to/your/serviceAccountKey.json')  # Update this path
    firebase_admin.initialize_app(cred)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.get(user_id)

from routes import *

if __name__ == '__main__':
    app.run(debug=True) 