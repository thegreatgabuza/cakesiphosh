from flask import render_template, request, redirect, url_for, flash, session, jsonify, abort
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from flask_login import login_required, login_user, logout_user, current_user
import uuid
import os
import pytz
import json
import random
import pandas as pd
import base64
from firebase_admin import firestore
import google.generativeai as genai
import traceback

from __init__ import app, db
from models import Order, Settings, Product, Ingredient, ProductIngredient, Cart, User, UserPreferences, Chat

# Set a secret key for the session
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your-secret-key-here')

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'txt'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    try:
        # Get all products with their metrics
        products = Product.get_all_with_counts()
        orders = Order.get_all()
        max_orders = Settings.get_max_orders()
        
        # Calculate metrics
        total_revenue = sum(order.get('total', 0) for order in orders)
        pending_orders = len([o for o in orders if o.get('status') == 'pending'])
        completed_orders = len([o for o in orders if o.get('status') == 'completed'])
        total_orders = len(orders)
        
        # Get low stock products
        low_stock_products = [p for p in products if p.get('stock', 0) <= 5]
        
        # Get today's orders
        today = datetime.now().date()
        today_orders = []
        for order in orders:
            created_at = order.get('created_at')
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    continue
            if isinstance(created_at, datetime) and created_at.date() == today:
                today_orders.append(order)

        # Calculate daily metrics
        daily_metrics = {
            'orders_count': len(today_orders),
            'revenue': sum(order.get('total', 0) for order in today_orders),
            'remaining_capacity': max(0, max_orders - len(today_orders))
        }
        
        # Process orders for display
        processed_orders = []
        for order in orders:
            # Convert created_at to datetime if it's a string
            created_at = order.get('created_at')
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = datetime.now()  # Fallback if date parsing fails

            # Get status colors
            status = order.get('status', 'pending')
            payment_status = order.get('payment_status', 'pending')
            
            status_colors = {
                'pending': 'warning',
                'processing': 'info',
                'completed': 'success',
                'cancelled': 'danger'
            }
            
            payment_status_colors = {
                'pending': 'warning',
                'pending_verification': 'info',
                'verified': 'success',
                'failed': 'danger'
            }

            processed_order = {
                'id': order.get('id'),
                'customer_name': order.get('customer_name', 'N/A'),
                'total': order.get('total', 0),
                'status': status,
                'payment_status': payment_status,
                'created_at': created_at,
                'status_color': status_colors.get(status, 'secondary'),
                'payment_status_color': payment_status_colors.get(payment_status, 'secondary')
            }
            processed_orders.append(processed_order)

        # Sort orders by created_at descending
        processed_orders.sort(key=lambda x: x['created_at'], reverse=True)
        
        return render_template('admin/dashboard.html',
            metrics={
                                 'daily': daily_metrics,
                'total_revenue': total_revenue,
                'pending_orders': pending_orders,
                'completed_orders': completed_orders,
                                 'total_orders': total_orders
                             },
                             orders=processed_orders,
                             low_stock_products=low_stock_products)
                             
    except Exception as e:
        print(f"Dashboard error: {e}")
        flash('Error loading dashboard', 'danger')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        max_orders = int(request.form.get('max_orders', 0))
        Settings.set_max_orders(max_orders)
        flash('Settings updated successfully')
        return redirect(url_for('admin_settings'))
    
    max_orders = Settings.get_max_orders()
    return render_template('admin/settings.html', max_orders=max_orders)

@app.route('/customer/place-order', methods=['POST'])
@login_required
def place_order():
    try:
        # Get form data
        form_data = request.form
        
        # Handle proof of payment
        proof_of_payment = {
            'data': request.form.get('proof_of_payment_data'),
            'file_type': request.form.get('file_type'),
            'file_name': request.form.get('file_name')
        }
        
        # Create order document
        order_data = {
            'customer_id': current_user.id,
            'customer_name': form_data.get('customer_name'),
            'delivery_method': form_data.get('delivery_method'),
            'delivery_address': form_data.get('delivery_address'),
            'contact_number': form_data.get('contact_number'),
            'total': float(form_data.get('total')),
            'status': 'pending',
            'date': datetime.now(),
            'proof_of_payment': proof_of_payment,
            # ... other order details
        }
        
        # Save to Firestore
        order_ref = db.collection('orders').document()
        order_ref.set(order_data)
        
        # Clear the cart
        # ... existing cart clearing code ...
        
        flash('Order placed successfully!', 'success')
        return redirect(url_for('orders'))
        
    except Exception as e:
        flash(f'Error placing order: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/customer/upload-payment-proof/<order_id>', methods=['POST'])
@login_required
def upload_payment_proof(order_id):
    try:
        if 'payment_proof' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'})
            
        file = request.files['payment_proof']
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
            
        if file and allowed_file(file.filename):
            try:
                # Read file and convert to base64
                import base64
                file_content = file.read()
                base64_encoded = base64.b64encode(file_content).decode('utf-8')
                
                # Get file extension
                file_ext = os.path.splitext(file.filename)[1][1:].lower()
                
                # Create appropriate data URI based on file type
                if file_ext in ['pdf', 'doc', 'docx', 'txt']:
                    mime_types = {
                        'pdf': 'application/pdf',
                        'doc': 'application/msword',
                        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        'txt': 'text/plain'
                    }
                    data_uri = f"data:{mime_types.get(file_ext, 'application/octet-stream')};base64,{base64_encoded}"
                else:
                    data_uri = f"data:image/{file_ext};base64,{base64_encoded}"

                # Update order with proof of payment data directly in Firestore
                order_ref = db.collection('orders').document(order_id)
                order_ref.update({
                    'payment_status': 'pending_verification',
                    'payment_submitted_at': datetime.now(),
                    'proof_of_payment': {
                        'data': data_uri,
                        'file_name': file.filename,
                        'file_type': file_ext,
                        'uploaded_at': datetime.now()
                    }
                })
                
                return jsonify({
                    'success': True, 
                    'message': 'Payment proof uploaded successfully',
                    'url': data_uri,
                    'file_type': file_ext
                })
            except Exception as e:
                print(f"Error uploading payment proof: {e}")
                return jsonify({'success': False, 'error': str(e)})
        else:
            return jsonify({'success': False, 'error': 'Invalid file type'})
            
    except Exception as e:
        print(f"Error handling payment proof upload: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/')
def index():
    products = Product.get_all()
    return render_template('home.html', products=products)

@app.route('/pre-login', methods=['GET', 'POST'])
def pre_login():
    # Only allow access if coming from registration
    if 'registration_data' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Store preferences in session
        preferences = {
            'age_group': request.form.get('age_group'),
            'occasions': request.form.getlist('occasions'),
            'flavors': request.form.getlist('flavors'),
            'price_range': request.form.get('price_range'),
            'frequency': request.form.get('frequency'),
            'dietary': request.form.getlist('dietary')
        }
        
        try:
            # Get registration data
            reg_data = session['registration_data']
            
            # Create user in Firestore
            user_data = {
                'name': reg_data['name'],
                'email': reg_data['email'],
                'password_hash': generate_password_hash(reg_data['password'], method='scrypt'),
                'created_at': datetime.now(),
                'role': 'customer'  # Default role
            }
            
            # Add user to Firestore
            users_ref = db.collection('users')
            user_ref = users_ref.document()
            user_ref.set(user_data)
            
            # Create User object and log in
            user = User(
                id=user_ref.id,
                email=reg_data['email'],
                name=reg_data['name'],
                role='customer'
            )
            login_user(user)
            
            # Store preferences
            UserPreferences.create_or_update(user_ref.id, preferences)
            
            # Clear session data
            session.pop('registration_data', None)
            
            flash('Account created successfully!', 'success')
            return redirect(url_for('customer_dashboard'))
            
        except Exception as e:
            print(f"Registration error: {str(e)}")
            flash('Error creating account. Please try again.', 'danger')
            return redirect(url_for('login'))
            
    return render_template('pre_login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('customer_dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            # Get user from Firestore
            users_ref = db.collection('users')
            user_query = users_ref.where('email', '==', email).limit(1).stream()
            
            user_found = None
            for user_doc in user_query:
                user_found = {
                    'id': user_doc.id,
                    **user_doc.to_dict()
                }
                break
            
            if user_found:
                # For admin user with plain text password
                if email == 'admin@example.com' and password == 'admin123':
                    is_valid = True
                else:
                    # For other users, verify using werkzeug's check_password_hash
                    stored_hash = user_found.get('password_hash')
                    is_valid = check_password_hash(stored_hash, password)
                
                if is_valid:
                    user = User(
                        id=user_found['id'],
                        email=user_found['email'],
                        name=user_found.get('name', ''),
                        role=user_found.get('role', 'customer')
                    )
                    login_user(user)
            flash('Welcome back!', 'success')
            
            # Redirect based on role
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('customer_dashboard'))
            
            flash('Invalid email or password', 'danger')
            
        except Exception as e:
            print(f"Login error: {e}")
            flash('Invalid email or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    # Clear session
    session.pop('user', None)
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('index'))

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    try:
        # Create settings document if it doesn't exist
        settings_ref = db.collection('settings').document('orders')
        if not settings_ref.get().exists:
            settings_ref.set({
                'max_orders_per_day': 50  # default value
            })
        return 'Database setup complete'
    except Exception as e:
        return f'Error setting up database: {str(e)}', 500

@app.route('/customer/dashboard')
@login_required
def customer_dashboard():
    try:
        # Get customer's cart
        cart = Cart.get_cart(current_user.id)
        if not isinstance(cart, dict):
            cart = {'items': [], 'total': 0.0}
        
        # Ensure cart has the correct structure
        if not isinstance(cart.get('items'), list):
            cart['items'] = []
        if not isinstance(cart.get('total'), (int, float)):
            cart['total'] = 0.0
            
        print(f"Current cart: {cart}")
        
        # Get all products
        products = Product.get_all()
        print(f"Available products: {len(products)}")
        
        # Get personalized recommendations
        recommended_products = UserPreferences.get_recommendations(current_user.id, products)
        print(f"Recommended products: {len(recommended_products)}")
        
        return render_template('customer/dashboard.html',
                             cart=cart,
                             products=products,
                             recommended_products=recommended_products)
    except Exception as e:
        print(f"Error in customer dashboard: {e}")
        import traceback
        traceback.print_exc()
        return render_template('customer/dashboard.html',
                             cart={'items': [], 'total': 0.0},
                             products=[],
                             recommended_products=[])

def get_recommended_products(customer_id, all_products, max_recommendations=4):
    try:
        # Get customer's order history
        orders = Order.get_by_customer(customer_id)
        
        # Get products from order history
        ordered_products = set()
        for order in orders:
            ordered_products.update(order.get('items', []))
        
        # Get current cart items
        cart = Cart.get_cart(customer_id)
        cart_products = set(item['product_id'] for item in cart.get('items', []))
        
        # Filter out products already in cart
        available_products = [p for p in all_products if p['id'] not in cart_products]
        
        # Sort products by relevance (ordered before, then random)
        recommended = []
        
        # First, add products the customer has ordered before
        for product in available_products:
            if product['id'] in ordered_products:
                recommended.append(product)
                if len(recommended) >= max_recommendations:
                    return recommended
        
        # Then add random products until we reach max_recommendations
        import random
        remaining_products = [p for p in available_products if p not in recommended]
        random.shuffle(remaining_products)
        
        recommended.extend(remaining_products[:max_recommendations - len(recommended)])
        
        return recommended
    except Exception as e:
        print(f"Error getting recommendations: {e}")
        return []

# Add a setup route to initialize some products
@app.route('/setup/products')
def setup_products():
    try:
        # Sample products data with real images
        products = [
            {
                'name': 'Classic Black Forest',
                'price': 399.99,
                'description': 'Rich chocolate layers with cherries and cream',
                'image_url': '/static/images/blackforest.jpeg',
                'stock': 15
            },
            {
                'name': 'Premium Wedding Cake',
                'price': 2499.99,
                'description': 'Elegant multi-tiered wedding cake with fondant finish',
                'image_url': '/static/images/wedding.png',
                'stock': 5
            },
            {
                'name': 'Traditional Wedding Cake',
                'price': 1899.99,
                'description': 'Beautiful traditional design with intricate details',
                'image_url': '/static/images/weddingcaketraditional.jpeg',
                'stock': 5
            },
            {
                'name': 'Modern Wedding Cake',
                'price': 2199.99,
                'description': 'Contemporary design with elegant white finish',
                'image_url': '/static/images/weddingcake.jpeg',
                'stock': 5
            },
            {
                'name': 'Luxury Wedding Cake',
                'price': 2899.99,
                'description': 'Luxurious multi-tiered cake with gold accents',
                'image_url': '/static/images/weddingcake2.jpeg',
                'stock': 3
            },
            {
                'name': 'Classic Chocolate Cake',
                'price': 329.99,
                'description': 'Decadent chocolate cake with rich ganache',
                'image_url': '/static/images/chocolate.jpeg',
                'stock': 20
            },
            {
                'name': 'German Chocolate Delight',
                'price': 449.99,
                'description': 'Traditional German chocolate cake with coconut pecan frosting',
                'image_url': '/static/images/germanchoc.jpeg',
                'stock': 12
            },
            {
                'name': 'Fresh Fruit Cake',
                'price': 379.99,
                'description': 'Light sponge cake topped with fresh seasonal fruits',
                'image_url': '/static/images/fruitcake.jpeg',
                'stock': 15
            },
            {
                'name': 'Birthday Special Cake',
                'price': 449.99,
                'description': 'Colorful birthday cake with custom decorations',
                'image_url': '/static/images/birthdaycake2.jpeg',
                'stock': 20
            },
            {
                'name': 'Premium Birthday Cake',
                'price': 499.99,
                'description': 'Premium celebration cake with custom design',
                'image_url': '/static/images/birthdaycake3.jpeg',
                'stock': 15
            },
            {
                'name': 'Kids Birthday Cake',
                'price': 399.99,
                'description': 'Fun and colorful cake perfect for children',
                'image_url': '/static/images/birthdaycake4.jpg',
                'stock': 20
            },
            {
                'name': 'Assorted Cake Selection',
                'price': 459.99,
                'description': 'Various flavors in one beautiful cake',
                'image_url': '/static/images/cakes.jpeg',
                'stock': 10
            }
        ]
        
        print("Clearing existing products...")
        # Clear existing products first
        products_ref = db.collection('products')
        existing_products = products_ref.stream()
        for doc in existing_products:
            doc.reference.delete()
        
        print(f"Adding {len(products)} new products...")
        # Add new products
        for product in products:
            print(f"Adding product: {product['name']}")
            Product.create(product)
            
        print("Products initialization complete")
        return 'Products initialized successfully'
    except Exception as e:
        print(f"Error during product initialization: {e}")
        return f'Error setting up products: {str(e)}', 500

@app.route('/admin/products')
@admin_required
def admin_products():
    products = Product.get_all_with_counts()
    return render_template('admin/products.html', products=products)

@app.route('/admin/products/add', methods=['POST'])
@admin_required
def admin_add_product():
    if 'image' not in request.files:
        flash('No image file uploaded', 'error')
        return redirect(url_for('admin_products'))
    
    file = request.files['image']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('admin_products'))
    
    if file and allowed_file(file.filename):
        # Convert image to base64
        import base64
        file_content = file.read()
        base64_encoded = base64.b64encode(file_content).decode('utf-8')
        file_ext = os.path.splitext(file.filename)[1][1:].lower()
        data_uri = f"data:image/{file_ext};base64,{base64_encoded}"
        
        # Create product
        product_data = {
            'name': request.form.get('name'),
            'price': float(request.form.get('price')),
            'description': request.form.get('description'),
            'stock': int(request.form.get('stock')),
            'image_url': data_uri
        }
        
        Product.create(product_data)
        flash('Product added successfully')
    
    return redirect(url_for('admin_products'))

@app.route('/admin/products/<product_id>/edit', methods=['POST'])
@admin_required
def admin_edit_product(product_id):
    data = {
        'name': request.form.get('name'),
        'price': float(request.form.get('price')),
        'description': request.form.get('description'),
        'stock': int(request.form.get('stock'))
    }
    
    if 'image' in request.files and request.files['image'].filename:
        file = request.files['image']
        if allowed_file(file.filename):
            # Convert image to base64
            import base64
            file_content = file.read()
            base64_encoded = base64.b64encode(file_content).decode('utf-8')
            file_ext = os.path.splitext(file.filename)[1][1:].lower()
            data_uri = f"data:image/{file_ext};base64,{base64_encoded}"
            
            data['image_url'] = data_uri
    
    Product.update(product_id, data)
    flash('Product updated successfully')
    return redirect(url_for('admin_products'))

@app.route('/admin/products/<product_id>/delete', methods=['POST'])
@admin_required
def admin_delete_product(product_id):
    Product.delete(product_id)
    return jsonify({'success': True})

@app.route('/admin/ingredients')
@login_required
@admin_required
def admin_ingredients():
    try:
        ingredients = Ingredient.get_all()
        print("Fetched ingredients:", ingredients)  # Debug log
        return render_template('admin/ingredients.html', ingredients=ingredients)
    except Exception as e:
        print(f"Error in admin_ingredients: {e}")  # Debug log
        flash('Error loading ingredients', 'error')
        return render_template('admin/ingredients.html', ingredients=[])

@app.route('/admin/ingredients/add', methods=['POST'])
@login_required
@admin_required
def admin_add_ingredient():
    try:
        data = {
            'name': request.form.get('name'),
            'quantity': float(request.form.get('quantity')),
            'unit': request.form.get('unit'),
            'min_stock_level': float(request.form.get('min_stock_level')),
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
        
        ingredient_id = Ingredient.create(data)
        if ingredient_id:
            flash('Ingredient added successfully', 'success')
        else:
            flash('Error adding ingredient', 'error')
            
    except Exception as e:
        flash(f'Error adding ingredient: {str(e)}', 'error')
        
    return redirect(url_for('admin_ingredients'))

@app.route('/admin/ingredients/<ingredient_id>/edit', methods=['POST'])
@login_required
@admin_required
def admin_edit_ingredient(ingredient_id):
    try:
        data = {
            'name': request.form.get('name'),
            'quantity': float(request.form.get('quantity')),
            'unit': request.form.get('unit'),
            'min_stock_level': float(request.form.get('min_stock_level')),
            'updated_at': datetime.now()
        }
        
        if Ingredient.update(ingredient_id, data):
            flash('Ingredient updated successfully', 'success')
        else:
            flash('Error updating ingredient', 'error')
            
    except Exception as e:
        flash(f'Error updating ingredient: {str(e)}', 'error')
        
    return redirect(url_for('admin_ingredients'))

@app.route('/admin/ingredients/<ingredient_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_ingredient(ingredient_id):
    try:
        if Ingredient.delete(ingredient_id):
            flash('Ingredient deleted successfully', 'success')
        else:
            flash('Error deleting ingredient', 'error')
            
    except Exception as e:
        flash(f'Error deleting ingredient: {str(e)}', 'error')
        
    return redirect(url_for('admin_ingredients'))

# Add a setup route for initial ingredients
@app.route('/setup/ingredients')
def setup_ingredients():
    try:
        # Check if ingredients already exist
        existing = Ingredient.get_all()
        if existing:
            return 'Ingredients already set up'

        # Sample ingredients data
        ingredients = [
            {
                'name': 'Flour',
                'quantity': 50000,  # 50kg
                'unit': 'g',
                'min_stock_level': 5000,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            },
            {
                'name': 'Sugar',
                'quantity': 40000,  # 40kg
                'unit': 'g',
                'min_stock_level': 4000,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            },
            {
                'name': 'Milk',
                'quantity': 40000,  # 40L
                'unit': 'ml',
                'min_stock_level': 4000,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            },
            {
                'name': 'Eggs',
                'quantity': 500,  # 500 pieces
                'unit': 'pcs',
                'min_stock_level': 50,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            },
            {
                'name': 'Butter',
                'quantity': 30000,  # 30kg
                'unit': 'g',
                'min_stock_level': 3000,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            },
            {
                'name': 'Vanilla Extract',
                'quantity': 5000,  # 5L
                'unit': 'ml',
                'min_stock_level': 500,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            },
            {
                'name': 'Baking Powder',
                'quantity': 10000,  # 10kg
                'unit': 'g',
                'min_stock_level': 1000,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            },
            {
                'name': 'Salt',
                'quantity': 5000,  # 5kg
                'unit': 'g',
                'min_stock_level': 500,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
        ]

        # Create each ingredient
        for ingredient_data in ingredients:
            Ingredient.create(ingredient_data)

        return 'Ingredients setup complete'
    except Exception as e:
        return f'Error setting up ingredients: {str(e)}', 500

@app.route('/cart/add/<product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    try:
        if Cart.add_item(current_user.id, product_id):
            cart = Cart.get_cart(current_user.id)
            return jsonify({'success': True, 'cart': cart})
        return jsonify({'success': False, 'error': 'Could not add item to cart'})
    except Exception as e:
        print(f"Error adding to cart: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/cart/update/<product_id>', methods=['POST'])
@login_required
def update_cart(product_id):
    try:
        data = request.get_json()
        quantity = int(data.get('quantity', 1))
        print(f"Updating cart: product={product_id}, quantity={quantity}")
        
        if Cart.update_quantity(current_user.id, product_id, quantity):
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Could not update cart'})
    except Exception as e:
        print(f"Error updating cart: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/cart/remove/<product_id>', methods=['POST'])
@login_required
def remove_from_cart(product_id):
    try:
        print(f"Removing product {product_id} from cart")
        if Cart.remove_item(current_user.id, product_id):
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Could not remove item from cart'})
    except Exception as e:
        print(f"Error removing from cart: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/cart/clear', methods=['POST'])
@login_required
def clear_cart():
    try:
        if Cart.clear_cart(current_user.id):
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Could not clear cart'})
    except Exception as e:
        print(f"Error clearing cart: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/api/chart-data')
@login_required
def get_chart_data():
    # Get time series data for charts
    last_30_days = datetime.now() - timedelta(days=30)
    orders_ref = db.collection('orders')
    
    # Get orders for last 30 days
    orders = orders_ref.where('created_at', '>=', last_30_days).get()
    
    # Convert to pandas DataFrame for easier date grouping
    orders_data = [{
        'date': order.to_dict()['created_at'],
        'amount': order.to_dict().get('amount', 0)
    } for order in orders]
    
    df = pd.DataFrame(orders_data)
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df['date'] = df['date'].dt.date
        
        # Group by date
        daily_orders = df.groupby('date').size().reset_index(name='count')
        daily_revenue = df.groupby('date')['amount'].sum().reset_index()
        
        return jsonify({
            'orders': [{
                'date': str(row['date']),
                'count': int(row['count'])
            } for _, row in daily_orders.iterrows()],
            'revenue': [{
                'date': str(row['date']),
                'total': float(row['amount'])
            } for _, row in daily_revenue.iterrows()]
        })
    else:
        return jsonify({
            'orders': [],
            'revenue': []
        })

@app.route('/admin/orders')
@login_required
@admin_required
def admin_orders():
    # Get status filter from query params
    status = request.args.get('status', 'all')
    
    try:
        # Get orders from the Order model
        orders_list = Order.get_all()
        
        # Debug print
        print("Raw orders:", orders_list)
        
        # Ensure orders_list is a list
        if not isinstance(orders_list, list):
            print("Warning: orders_list is not a list, converting to empty list")
            orders_list = []
        
        # Filter by status if needed
        if status != 'all':
            orders_list = [order for order in orders_list if order.get('status') == status]
        
        # Sort by created_at
        orders_list.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        print(f"Found {len(orders_list)} orders")
        if orders_list:
            print("First order sample:", orders_list[0])
        
        return render_template('admin/orders.html', orders=orders_list)
    except Exception as e:
        print(f"Error in admin_orders: {e}")
        print(f"Error type: {type(e)}")
        import traceback
        traceback.print_exc()
        flash('Error loading orders', 'error')
        return render_template('admin/orders.html', orders=[])

@app.route('/admin/orders/<order_id>/verify-payment', methods=['POST'])
@login_required
@admin_required
def verify_payment(order_id):
    try:
        action = request.json.get('action')
        comment = request.json.get('comment', '')
        
        if action not in ['verify', 'decline']:
            return jsonify({'success': False, 'error': 'Invalid action'})
        
        update_data = {
            'payment_status': 'verified' if action == 'verify' else 'declined',
            'status': 'payment_verified' if action == 'verify' else 'declined',
            'admin_comment': comment,
            'payment_verified_at': datetime.now()
        }
        
        # Update order in Firestore
        order_ref = db.collection('orders').document(order_id)
        order_ref.update(update_data)
        
        return jsonify({
            'success': True,
            'message': f'Payment {action}d successfully'
        })
    except Exception as e:
        print(f"Error verifying payment: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/orders/<order_id>/update-status', methods=['POST'])
@login_required
@admin_required
def update_order_status(order_id):
    try:
        data = request.get_json()
        order_ref = db.collection('orders').document(order_id)
        order = order_ref.get()
        
        if not order.exists:
            return jsonify({'success': False, 'error': 'Order not found'})
        
        update_data = {
            'status': data['status']
        }
        if data.get('comment'):
            update_data['admin_comment'] = data['comment']
        
        order_ref.update(update_data)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/orders/<order_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_order(order_id):
    try:
        # Delete order from Firestore
        order_ref = db.collection('orders').document(order_id)
        order = order_ref.get()
        
        if not order.exists:
            return jsonify({'success': False, 'error': 'Order not found'})
        
        order_ref.delete()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    try:
        users = User.get_all()
        return render_template('admin/users.html', users=users)
    except Exception as e:
        print(f"Error loading users: {e}")
        flash('Error loading users', 'error')
        return render_template('admin/users.html', users=[])

@app.route('/admin/users/add', methods=['POST'])
@login_required
@admin_required
def admin_add_user():
    try:
        data = request.get_json()
        
        # Check if email already exists
        if User.get_by_email(data['email']):
            return jsonify({'success': False, 'error': 'Email already exists'})
        
        # Create user
        user_data = {
            'email': data['email'],
            'password_hash': generate_password_hash(data['password']),
            'role': data['role'],
            'is_active': data['is_active'],
            'created_at': datetime.now()
        }
        
        User.create(user_data)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/users/<user_id>/edit', methods=['POST'])
@login_required
@admin_required
def admin_edit_user(user_id):
    try:
        data = request.get_json()
        
        # Check if email exists for different user
        existing_user = User.get_by_email(data['email'])
        if existing_user and existing_user.id != user_id:
            return jsonify({'success': False, 'error': 'Email already exists'})
        
        # Update user data
        update_data = {
            'email': data['email'],
            'role': data['role'],
            'is_active': data['is_active']
        }
        
        # Update password if provided
        if data.get('password'):
            update_data['password_hash'] = generate_password_hash(data['password'])
        
        User.update(user_id, update_data)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/users/<user_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    try:
        # Prevent self-deletion
        if user_id == current_user.id:
            return jsonify({'success': False, 'error': 'Cannot delete your own account'})
        
        User.delete(user_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/customer/orders')
@login_required
def customer_orders():
    try:
        print(f"Fetching orders for customer: {current_user.id}")
        orders = Order.get_by_customer(current_user.id)
        print(f"Found {len(orders)} orders")
        if orders:
            print("Sample order:", orders[0])
        return render_template('customer/orders.html', orders=orders)
    except Exception as e:
        print(f"Error fetching customer orders: {e}")
        import traceback
        traceback.print_exc()
        flash('Error loading orders', 'error')
        return render_template('customer/orders.html', orders=[])

@app.route('/customer/orders/<order_id>/cancel', methods=['POST'])
@login_required
def cancel_order(order_id):
    try:
        # Verify order belongs to customer
        order = Order.get_by_id(order_id)
        if not order or order.get('customer_id') != current_user.id:
            return jsonify({'success': False, 'error': 'Order not found'})
        
        # Only allow cancellation of pending orders
        if order.get('status') != 'pending':
            return jsonify({'success': False, 'error': 'Cannot cancel this order'})
        
        # Update order status
        Order.update(order_id, {
            'status': 'cancelled',
            'payment_status': 'cancelled'
        })
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/proof-of-payments')
@login_required
@admin_required
def admin_view_proof_of_payments():
    try:
        # Get orders with proof of payments
        orders = db.collection('orders').order_by('payment_submitted_at', direction='DESCENDING').stream()
        orders_list = []
        
        for order in orders:
            order_data = order.to_dict()
            if order_data.get('proof_of_payment'):  # Only include orders with payment proofs
                order_data['id'] = order.id
                orders_list.append(order_data)
        
        return render_template('admin/view_proofs.html', orders=orders_list)
    except Exception as e:
        print(f"Error loading payment proofs: {e}")
        flash('Error loading payment proofs', 'error')
        return render_template('admin/view_proofs.html', orders=[])

@app.route('/admin/proof-of-payments/upload', methods=['POST'])
@login_required
@admin_required
def admin_upload_proof():
    try:
        if 'proof_file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'})
            
        file = request.files['proof_file']
        order_id = request.form.get('order_id')
        
        if not file or not order_id:
            return jsonify({'success': False, 'error': 'Missing required data'})
            
        # Convert file to base64
        file_content = file.read()
        base64_encoded = base64.b64encode(file_content).decode('utf-8')
        file_ext = os.path.splitext(file.filename)[1][1:].lower()
        
        # Create data URI
        mime_types = {
            'pdf': 'application/pdf',
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        }
        
        if file_ext in mime_types:
            data_uri = f"data:{mime_types[file_ext]};base64,{base64_encoded}"
        else:
            data_uri = f"data:image/{file_ext};base64,{base64_encoded}"
            
        # Update order
        order_ref = db.collection('orders').document(order_id)
        order_ref.update({
            'proof_of_payment': {
                'data': data_uri,
                'file_name': file.filename,
                'file_type': file_ext,
                'uploaded_at': datetime.now()
            },
            'payment_status': 'pending_verification',
            'payment_submitted_at': datetime.now()
        })
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/proof-of-payments/<order_id>/update', methods=['POST'])
@login_required
@admin_required
def admin_update_proof(order_id):
    try:
        update_data = {}
        
        # Handle new file if uploaded
        if 'proof_file' in request.files and request.files['proof_file']:
            file = request.files['proof_file']
            file_content = file.read()
            base64_encoded = base64.b64encode(file_content).decode('utf-8')
            file_ext = os.path.splitext(file.filename)[1][1:].lower()
            
            mime_types = {
                'pdf': 'application/pdf',
                'doc': 'application/msword',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            }
            
            if file_ext in mime_types:
                data_uri = f"data:{mime_types[file_ext]};base64,{base64_encoded}"
            else:
                data_uri = f"data:image/{file_ext};base64,{base64_encoded}"
                
            update_data['proof_of_payment'] = {
                'data': data_uri,
                'file_name': file.filename,
                'file_type': file_ext,
                'uploaded_at': datetime.now()
            }
        
        # Update status and comment
        if 'payment_status' in request.form:
            update_data['payment_status'] = request.form['payment_status']
        if 'admin_comment' in request.form:
            update_data['admin_comment'] = request.form['admin_comment']
            
        # Update order
        order_ref = db.collection('orders').document(order_id)
        order_ref.update(update_data)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/proof-of-payments/<order_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_proof(order_id):
    try:
        order_ref = db.collection('orders').document(order_id)
        order_ref.update({
            'proof_of_payment': firestore.DELETE_FIELD,
            'payment_status': 'pending',
            'payment_submitted_at': firestore.DELETE_FIELD,
            'payment_verified_at': firestore.DELETE_FIELD,
            'admin_comment': firestore.DELETE_FIELD
        })
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# System prompt for the chatbot
SYSTEM_PROMPT = """You are a knowledgeable and friendly bakery assistant for Sweet Bakery. Your role is to help customers with their bakery-related inquiries and provide detailed, helpful responses.

Key Information:
1. Products:
   - Custom cakes (birthday, wedding, special occasions)
   - Cupcakes and pastries
   - Price range: 300-3000 PHP depending on size and design

2. Services:
   - Custom cake design and decoration
   - Special orders for events
   - Delivery within the city
   - 3-5 days advance notice required for custom orders

3. Policies:
   - Operating hours: 9 AM - 6 PM, Monday to Saturday
   - Payment methods: Bank transfer or cash
   - Delivery available within city limits
   - Free consultation for custom designs

4. Specialties:
   - Birthday cakes with custom themes
   - Wedding cakes (2-7 tiers)
   - Character cakes for children
   - Photo-printed cakes
   - Dietary options (gluten-free, sugar-free, vegan)

When responding:
- Be warm and friendly while maintaining professionalism
- Provide specific details about products and services
- If asked about prices, give ranges and explain factors affecting cost
- For custom orders, ask about preferences (size, flavor, design, occasion)
- If unsure about specific details, suggest contacting the store directly
- Offer relevant suggestions based on customer inquiries"""

# Initialize Gemini client with better error handling
try:
    api_key = os.getenv('GOOGLE_API_KEY')
    print("\nGoogle API Key Debug:")
    print(f"API Key exists: {bool(api_key)}")
    print(f"API Key length: {len(api_key) if api_key else 0}")
    
    if not api_key:
        raise ValueError("Google API key is not set in environment variables")
    
    # Clean the API key
    api_key = api_key.strip()  # Remove whitespace
    api_key = api_key.strip('"\'')  # Remove quotes
    
    print(f"API Key validation passed.")
    
    # Initialize Gemini client
    genai.configure(api_key=api_key)
    
    # Test the client with a simple completion
    print("Testing Gemini client with a simple request...")
    model = genai.GenerativeModel('gemini-pro')
    test_response = model.generate_content("Hello")
    print("Gemini client test successful!")
    print(f"Test response received: {test_response.text}")
    
except ValueError as ve:
    print(f"Google API Key Error: {str(ve)}")
    model = None
except Exception as e:
    print(f"Gemini Client Error: {str(e)}")
    print("Full error details:")
    traceback.print_exc()
    model = None

@app.route('/chat', methods=['GET'])
@login_required
def chat_interface():
    try:
        return render_template('chat.html')
    except Exception as e:
        print(f"Chat interface error: {str(e)}")
        traceback.print_exc()
        flash('Error loading chat interface', 'error')
        return redirect(url_for('index'))

@app.route('/chat/send', methods=['POST'])
def chat_with_ai():
    print("\n=== Starting chat request ===")
    
    if not model:
        error_msg = "Gemini client is not initialized. Please check your GOOGLE_API_KEY in .env file."
        print(f"Error: {error_msg}")
        return jsonify({
            'error': error_msg,
            'details': 'Make sure your .env file contains a valid Google API key'
        }), 500

    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        print(f"Processing message: {user_message}")
        
        if not user_message:
            return jsonify({'error': 'Message is required'}), 400

        # Initialize session if not already done
        if 'chat_history' not in session:
            session['chat_history'] = []

        # Get user preferences and recent orders for context if user is authenticated
        user_context = get_conversation_context(current_user.id, user_message) if current_user.is_authenticated else None
        
        # Get recent chat history (last 3 messages)
        chat_history = session.get('chat_history', [])[-3:]
        history_text = ""
        for msg in chat_history:
            history_text += f"{'User' if msg['sender'] == 'user' else 'Assistant'}: {msg['message']}\n"

        # Prepare prompt for Gemini
        system_context = SYSTEM_PROMPT + "\n\nPrevious conversation:\n" + history_text if history_text else SYSTEM_PROMPT
        full_prompt = f"{system_context}\n\nUser: {user_message}\nAssistant:"
        
        print("Sending request to Gemini API...")
        
        try:
            response = model.generate_content(full_prompt)
            
            ai_message = response.text.strip()
            print(f"Received response: {ai_message[:100]}...")
            
            if not ai_message:
                raise ValueError("Empty response from Gemini")
            
            # Update chat history
            current_time = datetime.now().isoformat()
            new_messages = [
                {'sender': 'user', 'message': user_message, 'timestamp': current_time},
                {'sender': 'assistant', 'message': ai_message, 'timestamp': current_time}
            ]
            
            # Store in session
            chat_history = session.get('chat_history', [])
            chat_history.extend(new_messages)
            session['chat_history'] = chat_history[-10:]  # Keep last 10 messages
            session.modified = True  # Ensure session is saved
            
            # Store in database if user is authenticated
            try:
                if current_user.is_authenticated:
                    Chat.create({
                        'user_id': current_user.id,
                        'user_message': user_message,
                        'ai_response': ai_message,
                        'timestamp': datetime.now(),
                        'resolved': False
                    })
            except Exception as db_error:
                print(f"Database error (non-critical): {str(db_error)}")
                traceback.print_exc()
                
            return jsonify({
                'response': ai_message,
                'history': chat_history
            })
            
        except Exception as api_error:
            error_msg = str(api_error)
            print(f"Gemini API Error: {error_msg}")
            print("Full error details:")
            traceback.print_exc()
            
            return jsonify({
                'error': 'Failed to get AI response',
                'details': str(api_error)
            }), 500
            
    except Exception as e:
        print(f"General chat error: {str(e)}")
        print("Full error details:")
        traceback.print_exc()
        return jsonify({
            'error': 'Failed to process request',
            'details': str(e)
        }), 500

@app.route('/chat/history', methods=['GET'])
def get_chat_history():
    try:
        # If user is authenticated, try to get history from database first
        if current_user.is_authenticated:
            history = Chat.get_user_history(current_user.id)
            if history:
                return jsonify({'history': history})
        
        # Fall back to session history for guests or if no database history
        history = session.get('chat_history', [])
        return jsonify({'history': history})
    except Exception as e:
        print(f"Error getting chat history: {str(e)}")
        return jsonify({'error': 'Failed to get chat history'}), 500

@app.route('/chat/clear', methods=['POST'])
def clear_chat():
    try:
        session.pop('chat_history', None)
        return jsonify({'message': 'Chat history cleared'})
    except Exception as e:
        print(f"Error clearing chat: {str(e)}")
        return jsonify({'error': 'Failed to clear chat'}), 500

@app.route('/admin/chat-interactions')
@login_required
@admin_required
def chat_interactions():
    interactions = Chat.get_all_interactions()
    return render_template('admin/chat_interactions.html', interactions=interactions)

@app.route('/admin/resolve-chat/<interaction_id>', methods=['POST'])
@login_required
@admin_required
def resolve_chat(interaction_id):
    if Chat.mark_as_resolved(interaction_id):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to mark as resolved'}), 500

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        
        try:
            # Check if user already exists
            users_ref = db.collection('users')
            existing_user = users_ref.where('email', '==', email).limit(1).get()
            if len(list(existing_user)) > 0:
                flash('An account with this email already exists.', 'danger')
                return redirect(url_for('login'))
            
            # Redirect to pre-login to collect preferences
            session['registration_data'] = {
                'email': email,
                'password': password,
                'name': name
            }
            return redirect(url_for('pre_login'))
            
        except Exception as e:
            print(f"Registration error: {str(e)}")
            flash('Error creating account. Please try again.', 'danger')
            
    return redirect(url_for('login'))

@app.route('/setup/admin', methods=['GET'])
def setup_admin():
    try:
        admin_email = "admin@example.com"
        admin_password = "admin123"
        admin_name = "Admin"

        # Check if admin exists in Firestore
        admin_query = db.collection('users').where('email', '==', admin_email).limit(1).stream()
        admin_exists = False
        for _ in admin_query:
            admin_exists = True
            break
        
        if admin_exists:
            return 'Admin user already exists'
            
        # Create admin user in Firestore
        admin_data = {
            'name': admin_name,
            'email': admin_email,
            'password_hash': generate_password_hash(admin_password, method='scrypt'),
            'role': 'admin',
            'created_at': datetime.now()
        }
        
        # Add admin to Firestore
        db.collection('users').document().set(admin_data)
        return 'Admin user created successfully'
            
    except Exception as e:
        print(f"Error creating admin: {e}")
        return f'Error creating admin: {str(e)}', 500

@app.route('/setup/seed-orders')
def seed_orders():
    try:
        # Sample customer demographics
        customers = [
            {"id": "cust1", "name": "John Smith", "gender": "Male", "age_group": "25-34", "location": "Makati"},
            {"id": "cust2", "name": "Maria Santos", "gender": "Female", "age_group": "35-44", "location": "Quezon City"},
            {"id": "cust3", "name": "David Chen", "gender": "Male", "age_group": "18-24", "location": "Pasig"},
            {"id": "cust4", "name": "Sarah Garcia", "gender": "Female", "age_group": "25-34", "location": "Taguig"},
            {"id": "cust5", "name": "Michael Lee", "gender": "Male", "age_group": "45+", "location": "Makati"},
            {"id": "cust6", "name": "Anna Cruz", "gender": "Female", "age_group": "18-24", "location": "Manila"},
            {"id": "cust7", "name": "James Wong", "gender": "Male", "age_group": "35-44", "location": "Pasay"},
            {"id": "cust8", "name": "Lisa Reyes", "gender": "Female", "age_group": "25-34", "location": "Mandaluyong"},
            {"id": "cust9", "name": "Robert Tan", "gender": "Male", "age_group": "45+", "location": "Makati"},
            {"id": "cust10", "name": "Emma Santos", "gender": "Female", "age_group": "18-24", "location": "Quezon City"}
        ]

        # Get all products
        products = Product.get_all()
        if not products:
            return 'No products found. Please seed products first.', 400

        # Create orders with different dates and statuses
        for i, customer in enumerate(customers):
            # Create 1-3 orders per customer
            for _ in range(random.randint(1, 3)):
                # Random order details
                num_items = random.randint(1, 3)
                order_items = []
                total = 0

                # Add random products to order
                for _ in range(num_items):
                    product = random.choice(products)
                    quantity = random.randint(1, 2)
                    item_total = float(product['price']) * quantity
                    total += item_total
                    order_items.append({
                        'product_id': product['id'],
                        'name': product['name'],
                        'price': float(product['price']),
                        'quantity': quantity
                    })

                # Random dates within last 30 days
                days_ago = random.randint(0, 30)
                order_date = datetime.now() - timedelta(days=days_ago)

                # Random status based on date
                if days_ago > 20:
                    status = random.choice(['completed', 'completed', 'completed', 'cancelled'])
                    payment_status = 'verified' if status == 'completed' else 'cancelled'
                elif days_ago > 10:
                    status = random.choice(['completed', 'preparing', 'ready'])
                    payment_status = 'verified'
                else:
                    status = random.choice(['pending', 'payment_verified', 'preparing'])
                    payment_status = random.choice(['pending', 'pending_verification', 'verified'])

                # Create order
                order_data = {
                    'customer_id': customer['id'],
                    'customer_name': customer['name'],
                    'customer_gender': customer['gender'],
                    'customer_age_group': customer['age_group'],
                    'customer_location': customer['location'],
                    'items': order_items,
                    'total': total,
                    'status': status,
                    'payment_status': payment_status,
                    'created_at': order_date,
                    'delivery_method': random.choice(['pickup', 'delivery']),
                    'performance_factors': {
                        'delivery_time': random.randint(20, 60),  # minutes
                        'customer_rating': random.randint(3, 5),
                        'order_accuracy': random.random() > 0.1,  # 90% accuracy
                        'customer_satisfaction': random.choice(['Very Satisfied', 'Satisfied', 'Neutral'])
                    }
                }

                # Save order to Firestore
                Order.create(order_data)

        return 'Successfully seeded orders with demographic data'
    except Exception as e:
        print(f"Error seeding orders: {e}")
        return f'Error seeding orders: {str(e)}', 500

@app.route('/admin/view-proofs/<order_id>')
@login_required
@admin_required
def admin_view_proofs(order_id):
    try:
        # Get order details from Firestore
        order_ref = db.collection('orders').document(order_id)
        order = order_ref.get()
        
        if not order.exists:
            flash('Order not found', 'danger')
            return redirect(url_for('admin_dashboard'))
            
        order_data = order.to_dict()
        order_data['id'] = order.id
        
        return render_template('admin/view_proofs.html', order=order_data)
        
    except Exception as e:
        print(f"Error viewing proofs: {e}")
        flash('Error loading order details', 'danger')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/dashboard-metrics')
@login_required
@admin_required
def admin_dashboard_metrics():
    try:
        # Get all products with their metrics
        orders = Order.get_all()
        max_orders = Settings.get_max_orders()
        
        # Calculate metrics
        total_revenue = sum(order.get('total', 0) for order in orders)
        pending_orders = len([o for o in orders if o.get('status') == 'pending'])
        completed_orders = len([o for o in orders if o.get('status') == 'completed'])
        total_orders = len(orders)
        
        # Get today's orders
        today = datetime.now().date()
        today_orders = []
        for order in orders:
            created_at = order.get('created_at')
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    continue
            if isinstance(created_at, datetime) and created_at.date() == today:
                today_orders.append(order)

        # Calculate daily metrics
        daily_metrics = {
            'orders_count': len(today_orders),
            'revenue': sum(order.get('total', 0) for order in today_orders),
            'remaining_capacity': max(0, max_orders - len(today_orders))
        }

        # Process orders for display
        processed_orders = []
        for order in orders:
            # Convert created_at to datetime if it's a string
            created_at = order.get('created_at')
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = datetime.now()  # Fallback if date parsing fails

            # Format created_at for display
            created_at_str = created_at.strftime('%Y-%m-%d %H:%M') if isinstance(created_at, datetime) else str(created_at)

            # Get status colors
            status = order.get('status', 'pending')
            payment_status = order.get('payment_status', 'pending')
            
            status_colors = {
                'pending': 'warning',
                'processing': 'info',
                'completed': 'success',
                'cancelled': 'danger'
            }
            
            payment_status_colors = {
                'pending': 'warning',
                'pending_verification': 'info',
                'verified': 'success',
                'failed': 'danger'
            }

            processed_order = {
                'id': order.get('id'),
                'customer_name': order.get('customer_name', 'N/A'),
                'total': order.get('total', 0),
                'status': status,
                'payment_status': payment_status,
                'created_at': created_at_str,
                'status_color': status_colors.get(status, 'secondary'),
                'payment_status_color': payment_status_colors.get(payment_status, 'secondary')
            }
            processed_orders.append(processed_order)

        # Sort orders by created_at descending
        processed_orders.sort(key=lambda x: x['created_at'], reverse=True)
        
        return jsonify({
            'metrics': {
                'daily': daily_metrics,
                'total_revenue': total_revenue,
                'pending_orders': pending_orders,
                'completed_orders': completed_orders,
                'total_orders': total_orders
            },
            'orders': processed_orders
        })
                             
    except Exception as e:
        print(f"Dashboard metrics error: {e}")
        return jsonify({'error': 'Error loading dashboard metrics'}), 500

@app.route('/admin/analytics')
@login_required
@admin_required
def admin_analytics():
    try:
        # Get all orders and products
        orders = Order.get_all()
        products = Product.get_all_with_counts()
        
        # Process historical data for predictions
        processed_products = []
        for product in products:
            # Calculate trend based on last 30 days of orders
            thirty_days_ago = datetime.now() - timedelta(days=30)
            product_orders = []
            
            for order in orders:
                created_at = order.get('created_at')
                # Convert string dates to datetime
                if isinstance(created_at, str):
                    try:
                        created_at = datetime.fromisoformat(created_at)
                    except ValueError:
                        continue
                
                # Check if order contains this product
                if created_at and created_at >= thirty_days_ago:
                    items = order.get('items', [])
                    # Ensure items is a list of dictionaries
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict) and item.get('product_id') == product.get('id'):
                                order['created_at'] = created_at  # Store converted datetime
                                product_orders.append(order)
                                break
            
            # Calculate trend percentage
            recent_orders = len([o for o in product_orders if o['created_at'] >= (datetime.now() - timedelta(days=15))])
            older_orders = len([o for o in product_orders if o['created_at'] < (datetime.now() - timedelta(days=15))])
            trend_percentage = ((recent_orders - older_orders) / max(older_orders, 1)) * 100
            
            # Determine trend direction
            trend_color = 'success' if trend_percentage > 0 else 'danger' if trend_percentage < 0 else 'secondary'
            trend_icon = 'arrow-up' if trend_percentage > 0 else 'arrow-down' if trend_percentage < 0 else 'arrow-right'
            
            # Calculate predicted demand and recommended stock
            daily_avg = len(product_orders) / 30
            predicted_demand = round(daily_avg * 7)  # 7-day prediction
            recommended_stock = round(predicted_demand * 1.2)  # 20% buffer
            
            processed_products.append({
                'name': product.get('name', 'Unknown Product'),
                'stock': product.get('stock', 0),
                'predicted_demand': predicted_demand,
                'recommended_stock': recommended_stock,
                'trend_percentage': round(trend_percentage),
                'trend_color': trend_color,
                'trend_icon': trend_icon
            })
        
        # Generate forecast dates and placeholder values
        today = datetime.now()
        forecast_dates = [(today + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
        
        # Calculate historical daily averages
        daily_totals = {}
        daily_counts = {}
        
        for order in orders:
            created_at = order.get('created_at')
            # Convert string dates to datetime
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    continue
            
            if created_at:
                day = created_at.strftime('%Y-%m-%d')
                total = order.get('total', 0)
                if isinstance(total, (int, float)):  # Ensure total is a number
                    daily_totals[day] = daily_totals.get(day, 0) + total
                    daily_counts[day] = daily_counts.get(day, 0) + 1
        
        # Calculate average daily revenue
        avg_daily_revenue = sum(daily_totals.values()) / max(len(daily_totals), 1)
        
        # Generate forecast with some variation
        forecast_values = [
            round(avg_daily_revenue * (1 + (random.random() - 0.5) * 0.2), 2)
            for _ in range(7)
        ]
        
        # Analyze peak order times
        hour_counts = {i: 0 for i in range(24)}
        for order in orders:
            created_at = order.get('created_at')
            # Convert string dates to datetime
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    continue
            
            if created_at:
                hour = created_at.hour
                hour_counts[hour] += 1
        
        peak_times_labels = [f"{i:02d}:00" for i in range(24)]
        peak_times_values = list(hour_counts.values())
        
        # Analyze demographics impact
        demographics = {}
        for order in orders:
            age_group = order.get('customer_age_group', 'Unknown')
            total = order.get('total', 0)
            if isinstance(total, (int, float)):  # Ensure total is a number
                demographics[age_group] = demographics.get(age_group, 0) + total
        
        # Ensure we have at least one demographic group
        if not demographics:
            demographics['Unknown'] = 0
        
        demographics_labels = list(demographics.keys())
        demographics_values = list(demographics.values())
        
        # Get AI insights
        ai_insights = generate_ai_insights(orders, products)
        
        return render_template(
            'admin/analytics.html',
            products=processed_products,
            forecast_dates=forecast_dates,
            forecast_values=forecast_values,
            peak_times_labels=peak_times_labels,
            peak_times_values=peak_times_values,
            demographics_labels=demographics_labels,
            demographics_values=demographics_values,
            ai_insights=ai_insights
        )
                             
    except Exception as e:
        print(f"Analytics error: {e}")
        flash('Error loading analytics', 'danger')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/refresh-insights')
@login_required
@admin_required
def refresh_insights():
    try:
        orders = Order.get_all()
        products = Product.get_all_with_counts()
        insights = generate_ai_insights(orders, products)
        return jsonify({'insights': insights})
    except Exception as e:
        print(f"Error refreshing insights: {e}")
        return jsonify({'error': 'Error refreshing insights'}), 500

def generate_ai_insights(orders, products):
    try:
        # Prepare data for analysis
        total_orders = len(orders)
        total_revenue = sum(order.get('total', 0) for order in orders)
        
        # Get recent trends
        thirty_days_ago = datetime.now() - timedelta(days=30)
        recent_orders = []
        
        for order in orders:
            created_at = order.get('created_at')
            # Convert string dates to datetime
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    continue
            if created_at and created_at >= thirty_days_ago:
                order['created_at'] = created_at
                recent_orders.append(order)
        
        # Analyze product performance
        product_performance = {}
        for order in recent_orders:
            items = order.get('items', [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        product_id = item.get('product_id')
                        if product_id:
                            product_performance[product_id] = product_performance.get(product_id, 0) + 1
        
        # Get top and bottom performing products
        sorted_products = sorted(product_performance.items(), key=lambda x: x[1], reverse=True)
        top_products = sorted_products[:3] if sorted_products else []
        bottom_products = sorted_products[-3:] if len(sorted_products) >= 3 else []
        
        # Get product names
        product_names = {str(p.get('id')): p.get('name', 'Unknown') for p in products}
        
        # Format product performance strings
        top_products_str = ', '.join(
            f"{product_names.get(str(pid), 'Unknown')} ({count} orders)" 
            for pid, count in top_products
        ) or "No data available"
        
        bottom_products_str = ', '.join(
            f"{product_names.get(str(pid), 'Unknown')} ({count} orders)" 
            for pid, count in bottom_products
        ) or "No data available"
        
        # Prepare prompt for Gemini
        prompt = f"""You are a business analytics expert specializing in bakery operations.
        Based on the following bakery data, provide 3-4 key business insights and recommendations:
        
        Recent Performance:
        - Total orders in last 30 days: {len(recent_orders)}
        - Average order value: R{total_revenue/max(total_orders, 1):.2f}
        
        Top Performing Products:
        {top_products_str}
        
        Areas for Improvement:
        {bottom_products_str}
        
        Provide actionable insights focusing on:
        1. Sales trends and opportunities
        2. Inventory optimization
        3. Customer behavior patterns
        4. Specific recommendations for improvement
        
        Format the response in HTML with bullet points."""
        
        # Get insights from Gemini
        if not model:
            return "<p class='text-danger'>Gemini client is not initialized. Please check your API key configuration.</p>"
            
        try:
            response = model.generate_content(prompt)
            
            if response.text:
                return response.text
            else:
                return "<p class='text-danger'>Error: Empty response from Gemini. Please try again later.</p>"
            
        except Exception as e:
            print(f"Error generating AI insights: {e}")
            return "<p class='text-danger'>Error generating insights. Please try again later.</p>"
            
    except Exception as e:
        print(f"Error generating AI insights: {e}")
        return "<p class='text-danger'>Error generating insights. Please try again later.</p>"

def check_order_feasibility(product_name, quantity):
    """Check if an order is feasible based on ingredients and capacity"""
    try:
        # Get product details
        products = Product.get_all()
        product = next((p for p in products if p['name'].lower() == product_name.lower()), None)
        
        if not product:
            return {
                'feasible': False,
                'reason': f"Product '{product_name}' not found in our catalog.",
                'suggestions': []
            }

        # Get current orders for today
        orders = Order.get_all()
        today = datetime.now().date()
        today_orders = [
            order for order in orders 
            if isinstance(order.get('created_at'), datetime) and order['created_at'].date() == today
        ]
        
        # Get max orders setting
        max_orders = Settings.get_max_orders()
        current_orders = len(today_orders)
        
        # Check capacity
        if current_orders + quantity > max_orders:
            remaining_capacity = max(0, max_orders - current_orders)
            return {
                'feasible': False,
                'reason': f"Exceeds daily capacity. We can only accept {remaining_capacity} more orders today.",
                'suggestions': [
                    f"Consider splitting the order across multiple days",
                    f"We can fulfill {remaining_capacity} today and the rest tomorrow"
                ]
            }
        
        # Check ingredients
        product_ingredients = ProductIngredient.get_by_product(product['id'])
        insufficient_ingredients = []
        
        for ingredient_data in product_ingredients:
            ingredient = Ingredient.get(ingredient_data['ingredient_id'])
            required_amount = ingredient_data['amount'] * quantity
            
            if ingredient['stock'] < required_amount:
                insufficient_ingredients.append({
                    'name': ingredient['name'],
                    'available': ingredient['stock'],
                    'required': required_amount
                })
        
        if insufficient_ingredients:
            suggestions = []
            max_possible = float('inf')
            
            for ing in insufficient_ingredients:
                possible_quantity = ing['available'] // (ing['required'] / quantity)
                max_possible = min(max_possible, possible_quantity)
                suggestions.append(f"Need {ing['required']} {ing['name']}, but only have {ing['available']}")
            
            if max_possible > 0:
                suggestions.append(f"We can make {int(max_possible)} {product_name}s with current ingredients")
            
            return {
                'feasible': False,
                'reason': "Insufficient ingredients",
                'suggestions': suggestions
            }
        
        return {
            'feasible': True,
            'reason': "We have enough ingredients and capacity",
            'details': {
                'product': product['name'],
                'quantity': quantity,
                'remaining_capacity': max_orders - (current_orders + quantity)
            }
        }
        
    except Exception as e:
        print(f"Error checking feasibility: {e}")
        return {
            'feasible': False,
            'reason': "Error checking feasibility",
            'suggestions': ["Please try again or contact support"]
        }

@app.route('/admin/ai-assistant', methods=['POST'])
@login_required
@admin_required
def ai_assistant():
    try:
        message = request.json.get('message', '')
        
        if not model:
            return jsonify({
                'response': "Gemini client is not initialized. Please check your API key configuration."
            }), 500
        
        # Use Gemini to understand the request
        response = model.generate_content(message)
        
        # Format response
        if response.text:
            return jsonify({
                'response': response.text
            })
        else:
            return jsonify({
                'response': "Sorry, I couldn't generate a response. Please try again."
            }), 500
            
    except Exception as e:
        print(f"AI Assistant error: {e}")
        return jsonify({
            'response': "Sorry, I encountered an error. Please try again."
        }), 500

@app.route('/admin/birthdays')
@login_required
@admin_required
def admin_birthdays():
    try:
        # Get all birthdays from Firestore
        birthdays_ref = db.collection('birthdays').stream()
        birthdays = []
        today = datetime.now(pytz.UTC)
        
        for doc in birthdays_ref:
            birthday_data = doc.to_dict()
            birthday_data['id'] = doc.id
            
            # Parse birthday date
            birthday_date = datetime.strptime(birthday_data['birthday'], '%Y-%m-%d')
            
            # Calculate next birthday
            next_birthday = birthday_date.replace(year=today.year)
            if next_birthday < today:
                next_birthday = next_birthday.replace(year=today.year + 1)
            
            # Calculate days until next birthday
            days_until = (next_birthday - today).days
            birthday_data['days_until'] = days_until
            
            birthdays.append(birthday_data)
        
        # Sort birthdays by days until next birthday
        birthdays.sort(key=lambda x: x['days_until'])
        
        # Calculate upcoming birthdays (next 30 days)
        upcoming_birthdays = [b for b in birthdays if b['days_until'] <= 30]
        
        # Calculate birthdays this month
        this_month_birthdays = [b for b in birthdays if datetime.strptime(b['birthday'], '%Y-%m-%d').month == today.month]
        
        # Calculate pending emails
        pending_emails = len([b for b in birthdays if not b.get('email_sent', False) and b['days_until'] <= 14])
        
        return render_template('admin/birthdays.html',
                             birthdays=birthdays,
                             upcoming_birthdays=upcoming_birthdays,
                             this_month_birthdays=this_month_birthdays,
                             pending_emails=pending_emails)
                             
    except Exception as e:
        print(f"Error loading birthdays: {e}")
        flash('Error loading birthdays', 'danger')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/birthdays/<birthday_id>')
@login_required
@admin_required
def get_birthday(birthday_id):
    try:
        birthday_ref = db.collection('birthdays').document(birthday_id)
        birthday = birthday_ref.get()
        
        if not birthday.exists:
            return jsonify({'error': 'Birthday not found'}), 404
            
        birthday_data = birthday.to_dict()
        birthday_data['id'] = birthday.id
        
        return jsonify(birthday_data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/birthdays/new', methods=['POST'])
@login_required
@admin_required
def add_birthday():
    try:
        birthday_data = {
            'name': request.form.get('name'),
            'surname': request.form.get('surname'),
            'email': request.form.get('email'),
            'birthday': request.form.get('birthday'),
            'created_at': datetime.now(pytz.UTC),
            'email_sent': False
        }
        
        birthday_ref = db.collection('birthdays').document()
        birthday_ref.set(birthday_data)
        
        if request.form.get('sendEmail') == 'true':
            # Send birthday email immediately
            send_birthday_email(birthday_ref.id)
        
        return jsonify({'success': True, 'id': birthday_ref.id})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/birthdays/<birthday_id>', methods=['PUT'])
@login_required
@admin_required
def update_birthday(birthday_id):
    try:
        birthday_ref = db.collection('birthdays').document(birthday_id)
        
        if not birthday_ref.get().exists:
            return jsonify({'error': 'Birthday not found'}), 404
            
        birthday_data = {
            'name': request.form.get('name'),
            'surname': request.form.get('surname'),
            'email': request.form.get('email'),
            'birthday': request.form.get('birthday'),
            'updated_at': datetime.now(pytz.UTC)
        }
        
        birthday_ref.update(birthday_data)
        
        if request.form.get('sendEmail') == 'true':
            # Send birthday email immediately
            send_birthday_email(birthday_id)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/birthdays/<birthday_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_birthday(birthday_id):
    try:
        birthday_ref = db.collection('birthdays').document(birthday_id)
        
        if not birthday_ref.get().exists:
            return jsonify({'error': 'Birthday not found'}), 404
            
        birthday_ref.delete()
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/birthdays/<birthday_id>/send-email', methods=['POST'])
@login_required
@admin_required
def send_birthday_email(birthday_id):
    try:
        birthday_ref = db.collection('birthdays').document(birthday_id)
        birthday = birthday_ref.get()
        
        if not birthday.exists:
            return jsonify({'error': 'Birthday not found'}), 404
            
        birthday_data = birthday.to_dict()
        
        # Get email content from request
        email_data = request.json
        subject = email_data.get('subject', '🎉 Happy Birthday Coming Soon!')
        message = email_data.get('message', '')
        offer = email_data.get('offer', '')
        
        # Replace variables in message
        message = message.replace('{name}', birthday_data['name'])
        message = message.replace('{birthday_date}', birthday_data['birthday'])
        message = message.replace('{days_until}', str(birthday_data.get('days_until', 0)))
        
        # TODO: Implement email sending logic using your preferred email service
        # For now, we'll just mark it as sent
        birthday_ref.update({
            'email_sent': True,
            'last_email_sent': datetime.now(pytz.UTC),
            'last_email_subject': subject,
            'last_email_message': message,
            'last_email_offer': offer
        })
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Scheduled task to check and send birthday emails (run daily)
def check_upcoming_birthdays():
    db = firestore.client()
    today = datetime.now(pytz.UTC)
    
    # Get all birthdays
    birthdays_ref = db.collection('birthdays')
    birthday_docs = birthdays_ref.stream()
    
    for doc in birthday_docs:
        birthday_data = doc.to_dict()
        # Parse the birthday string to a datetime object and make it timezone-aware
        birthday_date = datetime.fromisoformat(birthday_data['birthday'])
        if birthday_date.tzinfo is None:
            birthday_date = pytz.UTC.localize(birthday_date)
        
        # Calculate next birthday
        next_birthday = birthday_date.replace(year=today.year)
        if next_birthday.tzinfo is None:
            next_birthday = pytz.UTC.localize(next_birthday)
        
        if next_birthday < today:
            next_birthday = next_birthday.replace(year=today.year + 1)
        
        days_until = (next_birthday - today).days
        
        # Send email if birthday is in 14 days and email hasn't been sent
        if days_until == 14 and not birthday_data.get('email_sent', False):
            try:
                send_birthday_email(doc.id)
            except Exception as e:
                print(f"Error sending birthday email to {birthday_data['email']}: {str(e)}")
        
        # Reset email_sent flag for next year if birthday has passed
        if days_until > 300:  # Reset roughly 2 months after birthday
            try:
                doc.reference.update({'email_sent': False})
            except Exception as e:
                print(f"Error resetting email flag for {birthday_data['email']}: {str(e)}")

@app.route('/api/suggested-products', methods=['POST'])
def suggested_products():
    try:
        data = request.get_json()
        current_items = data.get('current_items', [])
        
        # Get all products
        all_products = Product.get_all()
        
        # Filter out products already in cart
        available_products = [p for p in all_products if p['id'] not in current_items]
        
        # Randomly select up to 3 products
        num_suggestions = min(3, len(available_products))
        suggested_products = random.sample(available_products, num_suggestions)
        
        return jsonify(suggested_products)
        
    except Exception as e:
        print(f"Error getting suggested products: {e}")
        return jsonify([]), 500

# Chat-related functions
def get_order_status(order_id):
    """Get the status of an order"""
    try:
        order = Order.get_by_id(order_id)
        if order:
            return {
                "status": order.status,
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                "total": order.total
            }
        return None
    except Exception as e:
        print(f"Error getting order status: {e}")
        return None

def get_product_info(product_name):
    """Get information about a product"""
    try:
        products = Product.search_by_name(product_name)
        if products:
            return [{
                "name": p.name,
                "price": p.price,
                "description": p.description,
                "available": p.is_available
            } for p in products]
        return None
    except Exception as e:
        print(f"Error getting product info: {e}")
        return None

# OpenAI function definitions
CHAT_FUNCTIONS = [
    {
        "name": "get_order_status",
        "description": "Get the current status of an order",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The ID of the order to look up"
                }
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "get_product_info",
        "description": "Get information about a product",
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "description": "The name of the product to look up"
                }
            },
            "required": ["product_name"]
        }
    }
]

def count_tokens(messages):
    """Estimate token count for messages"""
    # Rough estimation: 4 chars = 1 token
    total_chars = sum(len(str(msg)) for msg in messages)
    return total_chars // 4

def get_conversation_context(user_id, current_message):
    """Get relevant conversation context"""
    try:
        # Get user preferences
        prefs = UserPreferences.get_preferences(user_id)
        
        # Get recent order history
        recent_orders = Order.get_recent_by_user(user_id, limit=3)
        
        # Build context message
        context = f"User Preferences: {json.dumps(prefs)}\n"
        if recent_orders:
            context += f"Recent Orders: {json.dumps(recent_orders)}\n"
        
        return context
    except Exception as e:
        print(f"Error getting conversation context: {e}")
        return ""