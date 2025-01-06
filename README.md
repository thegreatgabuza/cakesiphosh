# Cake Siphosh

A modern bakery management system built with Flask and Firebase, featuring real-time order tracking, inventory management, and AI-powered analytics.

## Features

- 🛒 Customer Dashboard
  - Browse products with dynamic filtering
  - Real-time shopping cart
  - Secure checkout process
  - Order tracking
  - Birthday notifications

- 👨‍💼 Admin Dashboard
  - Order management
  - Inventory tracking
  - Product management
  - Customer insights
  - AI-powered analytics
  - Birthday management system

- 🤖 AI Features
  - Smart inventory predictions
  - Sales forecasting
  - Customer behavior analysis
  - Order feasibility assistant

- 💳 Payment Integration
  - Multiple payment methods
  - Secure payment processing
  - Payment proof upload option

## Tech Stack

- Backend: Python/Flask
- Database: Firebase Firestore
- Authentication: Firebase Auth
- Frontend: Bootstrap 5, Chart.js
- Icons: Bootstrap Icons
- AI Integration: OpenAI

## Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/cake-siphosh.git
cd cake-siphosh
```

2. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up Firebase:
   - Create a Firebase project
   - Download serviceAccountKey.json
   - Place it in the project root

5. Create .env file with required environment variables:
```
FLASK_APP=app.py
FLASK_ENV=development
OPENAI_API_KEY=your_openai_api_key
```

6. Run the application:
```bash
flask run
```

## Deployment on Render.com

1. Create a new Web Service on Render.com
2. Connect your GitHub repository
3. Configure the following settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   
4. Add the following environment variables:
   ```
   FLASK_APP=app.py
   FLASK_ENV=production
   OPENAI_API_KEY=your_openai_api_key
   ```

5. For Firebase credentials:
   - Go to Environment > Secret Files
   - Create a new secret file named `serviceAccountKey.json`
   - Paste your Firebase service account credentials
   - Set the environment variable: `FIREBASE_CREDENTIALS=serviceAccountKey.json`

6. Deploy your application

Note: Make sure your Firebase project's configuration allows requests from your Render.com domain.

## Environment Variables

- `FLASK_APP`: Main application file
- `FLASK_ENV`: Development/production environment
- `OPENAI_API_KEY`: OpenAI API key for AI features
- `FIREBASE_CREDENTIALS`: Path to serviceAccountKey.json

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details. 