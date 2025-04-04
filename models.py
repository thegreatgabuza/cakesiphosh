from datetime import datetime
from config import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from google.cloud import firestore
import firebase_admin
from firebase_admin import auth
import pytz
import uuid
import json
import random
import string

class Order:
    def __init__(self, id=None, customer_id=None, items=None, total=0, 
                 status="pending", payment_status="pending", 
                 payment_proof=None, delivery_method=None):
        self.id = id
        self.customer_id = customer_id
        self._order_items = items or []
        self.total = total
        self.status = status
        self.payment_status = payment_status
        self.payment_proof = payment_proof
        self.delivery_method = delivery_method
        self.created_at = datetime.now()

    @staticmethod
    def create(data):
        try:
            # Ensure required fields
            required_fields = ['customer_id', 'items', 'total', 'status', 'payment_status']
            for field in required_fields:
                if field not in data:
                    raise ValueError(f"Missing required field: {field}")

            # Validate items
            if not isinstance(data['items'], list) or not data['items']:
                raise ValueError("Order must contain at least one item")

            # Create order document
            doc_ref = db.collection('orders').document()
            
            # Add created_at if not present
            if 'created_at' not in data:
                data['created_at'] = datetime.now()
            
            # Add the order
            doc_ref.set(data)
            
            print(f"Created order: {doc_ref.id}")
            return doc_ref.id
            
        except Exception as e:
            print(f"Error creating order: {e}")
            raise

    @staticmethod
    def get_all():
        try:
            # Get all orders from Firestore
            orders_ref = db.collection('orders')
            orders_docs = orders_ref.stream()
            
            # Convert to list immediately to avoid iterator issues
            orders_list = []
            
            # Process each order
            for doc in orders_docs:
                try:
                    data = doc.to_dict()
                    print(f"Processing order {doc.id}")
                    
                    # Convert Firestore timestamp to datetime string
                    if 'created_at' in data:
                        created_at = data['created_at']
                        try:
                            if hasattr(created_at, 'timestamp'):
                                timestamp = created_at.timestamp()
                                data['created_at'] = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')
                            elif isinstance(created_at, str):
                                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                data['created_at'] = dt.strftime('%Y-%m-%d %H:%M')
                            else:
                                data['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
                        except Exception as e:
                            print(f"Error converting timestamp for order {doc.id}: {e}")
                            data['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
                    else:
                        data['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
                    
                    # Add color indicators for status badges
                    data['status_color'] = {
                        'pending': 'warning',
                        'payment_verified': 'info',
                        'preparing': 'primary',
                        'ready': 'success',
                        'completed': 'success',
                        'declined': 'danger'
                    }.get(data.get('status', 'pending'), 'secondary')
                    
                    data['payment_status_color'] = {
                        'pending': 'warning',
                        'submitted': 'info',
                        'verified': 'success',
                        'declined': 'danger'
                    }.get(data.get('payment_status', 'pending'), 'secondary')
                    
                    # Process items
                    order_items = data.get('items', [])
                    processed_items = []
                    
                    # Ensure items is a list
                    if not isinstance(order_items, list):
                        order_items = [order_items] if order_items else []
                    
                    # Process each item
                    for item in order_items:
                        try:
                            if isinstance(item, str):
                                # If item is just an ID, fetch the product details
                                product = Product.get_by_id(item)
                                if product:
                                    processed_items.append({
                                        'id': item,
                                        'name': product.get('name', 'Unknown Product'),
                                        'price': product.get('price', 0),
                                        'quantity': 1
                                    })
                            elif isinstance(item, dict):
                                # If item is already a dictionary with details
                                processed_items.append(item)
                        except Exception as e:
                            print(f"Error processing item in order {doc.id}: {e}")
                            continue
                    
                    data['order_items'] = processed_items
                    
                    # Add to orders list
                    orders_list.append({
                        'id': doc.id,
                        **data
                    })
                    
                except Exception as e:
                    print(f"Error processing order {doc.id}: {e}")
                    continue
            
            print(f"Successfully processed {len(orders_list)} orders")
            return orders_list
            
        except Exception as e:
            print(f"Error fetching orders: {e}")
            return []

    @staticmethod
    def get_by_customer(customer_id):
        try:
            # Query orders for this customer
            orders = db.collection('orders').where('customer_id', '==', customer_id).stream()
            orders_list = []
            
            for doc in orders:
                data = doc.to_dict()
                
                # Convert Firestore timestamp to datetime string
                if 'created_at' in data:
                    created_at = data['created_at']
                    try:
                        if hasattr(created_at, 'timestamp'):
                            timestamp = created_at.timestamp()
                            data['created_at'] = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')
                        elif isinstance(created_at, str):
                            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            data['created_at'] = dt.strftime('%Y-%m-%d %H:%M')
                        else:
                            data['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
                    except Exception as e:
                        print(f"Error converting timestamp for order {doc.id}: {e}")
                        data['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
                
                # Add color indicators for status badges
                data['status_color'] = {
                    'pending': 'warning',
                    'payment_verified': 'info',
                    'preparing': 'primary',
                    'ready': 'success',
                    'completed': 'success',
                    'cancelled': 'danger',
                    'declined': 'danger'
                }.get(data.get('status', 'pending'), 'secondary')
                
                data['payment_status_color'] = {
                    'pending': 'warning',
                    'submitted': 'info',
                    'verified': 'success',
                    'cancelled': 'danger',
                    'declined': 'danger'
                }.get(data.get('payment_status', 'pending'), 'secondary')
                
                # Process order items
                order_items = data.get('items', [])
                processed_items = []
                
                if isinstance(order_items, list):
                    for item in order_items:
                        if isinstance(item, dict):
                            # Item already has details
                            processed_items.append(item)
                        elif isinstance(item, str):
                            # Item is just an ID, fetch product details
                            product = Product.get_by_id(item)
                            if product:
                                processed_items.append({
                                    'id': item,
                                    'name': product.get('name', 'Unknown Product'),
                                    'price': product.get('price', 0),
                                    'quantity': 1
                                })
                
                data['order_items'] = processed_items
                
                # Add to orders list
                orders_list.append({
                    'id': doc.id,
                    **data
                })
            
            # Sort by created_at (newest first)
            orders_list.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            
            return orders_list
        except Exception as e:
            print(f"Error fetching customer orders: {e}")
            return []

    @staticmethod
    def get_by_id(order_id):
        try:
            doc = db.collection('orders').document(order_id).get()
            if doc.exists:
                return {'id': doc.id, **doc.to_dict()}
            return None
        except Exception as e:
            print(f"Error fetching order {order_id}: {e}")
            return None

    @staticmethod
    def update(order_id, data):
        try:
            db.collection('orders').document(order_id).update(data)
            return True
        except Exception as e:
            print(f"Error updating order: {e}")
            raise

class Settings:
    @staticmethod
    def get_max_orders():
        try:
            doc = db.collection('settings').document('orders').get()
            if doc.exists:
                return doc.to_dict().get('max_orders_per_day', 0)
            return 0
        except Exception as e:
            print(f"Error fetching settings: {e}")
            return 0

    @staticmethod
    def set_max_orders(max_orders):
        try:
            db.collection('settings').document('orders').set({
                'max_orders_per_day': max_orders
            })
        except Exception as e:
            print(f"Error setting max orders: {e}")
            raise 

class Product:
    def __init__(self, id=None, name=None, price=0, description=None, image_url=None, stock=0):
        self.id = id
        self.name = name
        self.price = price
        self.description = description
        self.image_url = image_url
        self.stock = stock

    @staticmethod
    def create(data):
        try:
            if db:
                product_id = str(uuid.uuid4())
                data['created_at'] = datetime.now()
                
                product_ref = db.collection('products').document(product_id)
                product_ref.set(data)
                
                # Return the newly created product with its ID
                return {**data, 'id': product_id}
            else:
                print("WARNING: Database not available, product creation skipped")
                # For development without Firebase
                product_id = str(uuid.uuid4())
                return {**data, 'id': product_id, 'created_at': datetime.now()}
        except Exception as e:
            print(f"Error creating product: {str(e)}")
            return None

    @staticmethod
    def get_all():
        try:
            products = db.collection('products').stream()
            return [{'id': doc.id, **doc.to_dict()} for doc in products]
        except Exception as e:
            print(f"Error fetching products: {e}")
            return []

    @staticmethod
    def get_orders_count(product_id):
        try:
            # Get all orders containing this product
            orders = db.collection('orders').stream()
            count = 0
            for order in orders:
                order_data = order.to_dict()
                if product_id in order_data.get('items', []):
                    count += 1
            return count
        except Exception as e:
            print(f"Error counting orders for product {product_id}: {e}")
            return 0

    @staticmethod
    def get_all_with_counts():
        try:
            products = db.collection('products').stream()
            print("Fetching products from Firestore")  # Debug print
            product_list = []
            for doc in products:
                product_data = {'id': doc.id, **doc.to_dict()}
                product_data['orders_count'] = Product.get_orders_count(doc.id)
                product_list.append(product_data)
            print(f"Found {len(product_list)} products")  # Debug print
            return product_list
        except Exception as e:
            print(f"Error in get_all_with_counts: {e}")  # Debug print
            return []

    @staticmethod
    def update(product_id, data):
        try:
            db.collection('products').document(product_id).update(data)
            return True
        except Exception as e:
            print(f"Error updating product: {e}")
            return False

    @staticmethod
    def delete(product_id):
        try:
            db.collection('products').document(product_id).delete()
            return True
        except Exception as e:
            print(f"Error deleting product: {e}")
            return False

    @staticmethod
    def get_by_id(product_id):
        try:
            if db:
                doc = db.collection('products').document(product_id).get()
                if doc.exists:
                    return {'id': doc.id, **doc.to_dict()}
            else:
                print("WARNING: Database not available, using mock data")
                # In development, return mock data
                if product_id == 'mock1':
                    return {
                        'id': 'mock1',
                        'name': 'Sample Cake',
                        'description': 'A delicious sample cake for testing',
                        'price': 299.99,
                        'category': 'birthday',
                        'image_url': '/static/images/products/sample.jpg',
                        'stock': 10,
                        'created_at': datetime.now() - timedelta(days=30)
                    }
            return None
        except Exception as e:
            print(f"Error fetching product {product_id}: {e}")
            return None

class Ingredient:
    @staticmethod
    def create(name, stock, unit='units', min_stock=10):
        try:
            doc_ref = db.collection('ingredients').document()
            doc_ref.set({
                'name': name,
                'stock': stock,
                'unit': unit,
                'min_stock': min_stock
            })
            return doc_ref.id
        except Exception as e:
            print(f"Error creating ingredient: {e}")
            return None

    @staticmethod
    def get(ingredient_id):
        try:
            doc = db.collection('ingredients').document(ingredient_id).get()
            if doc.exists:
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        except Exception as e:
            print(f"Error getting ingredient: {e}")
            return None

    @staticmethod
    def get_all():
        try:
            docs = db.collection('ingredients').stream()
            ingredients = []
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                ingredients.append(data)
            return ingredients
        except Exception as e:
            print(f"Error getting all ingredients: {e}")
            return []

    @staticmethod
    def update_stock(ingredient_id, new_stock):
        try:
            doc_ref = db.collection('ingredients').document(ingredient_id)
            doc_ref.update({'stock': new_stock})
            return True
        except Exception as e:
            print(f"Error updating ingredient stock: {e}")
            return False

    @staticmethod
    def delete(ingredient_id):
        try:
            db.collection('ingredients').document(ingredient_id).delete()
            return True
        except Exception as e:
            print(f"Error deleting ingredient: {e}")
            return False

    @staticmethod
    def get_low_stock():
        try:
            docs = db.collection('ingredients').stream()
            low_stock = []
            for doc in docs:
                data = doc.to_dict()
                if data['stock'] <= data.get('min_stock', 10):
                    data['id'] = doc.id
                    low_stock.append(data)
            return low_stock
        except Exception as e:
            print(f"Error getting low stock ingredients: {e}")
            return []

class ProductIngredient:
    @staticmethod
    def create(product_id, ingredient_id, amount):
        try:
            doc_ref = db.collection('product_ingredients').document()
            doc_ref.set({
                'product_id': product_id,
                'ingredient_id': ingredient_id,
                'amount': amount
            })
            return True
        except Exception as e:
            print(f"Error creating product ingredient: {e}")
            return False

    @staticmethod
    def get_by_product(product_id):
        try:
            docs = db.collection('product_ingredients').where('product_id', '==', product_id).stream()
            ingredients = []
            for doc in docs:
                ingredient_data = doc.to_dict()
                ingredient_data['id'] = doc.id
                ingredients.append(ingredient_data)
            return ingredients
        except Exception as e:
            print(f"Error getting product ingredients: {e}")
            return []

    @staticmethod
    def delete(product_id, ingredient_id):
        try:
            docs = db.collection('product_ingredients')\
                .where('product_id', '==', product_id)\
                .where('ingredient_id', '==', ingredient_id)\
                .stream()
            for doc in docs:
                doc.reference.delete()
            return True
        except Exception as e:
            print(f"Error deleting product ingredient: {e}")
            return False

    @staticmethod
    def update(product_id, ingredient_id, amount):
        try:
            docs = db.collection('product_ingredients')\
                .where('product_id', '==', product_id)\
                .where('ingredient_id', '==', ingredient_id)\
                .stream()
            for doc in docs:
                doc.reference.update({'amount': amount})
            return True
        except Exception as e:
            print(f"Error updating product ingredient: {e}")
            return False

class Cart:
    @staticmethod
    def get_cart(customer_id):
        try:
            print(f"Getting cart for customer: {customer_id}")
            doc = db.collection('carts').document(str(customer_id)).get()
            
            # Initialize default cart structure
            cart_dict = {
                'cart_items': [],
                'total': 0.0
            }
            
            if doc.exists:
                cart_data = doc.to_dict()
                print(f"Raw cart data: {cart_data}")
                
                # Process cart items to include product details
                items = cart_data.get('items', [])
                processed_items = []
                total = 0.0
                
                for item in items:
                    print(f"Processing cart item: {item}")
                    product = Product.get_by_id(item['product_id'])
                    if product:
                        item_data = {
                            'product_id': item['product_id'],
                            'name': product.get('name', 'Unknown Product'),
                            'price': float(product.get('price', 0)),
                            'image_url': product.get('image_url', ''),
                            'quantity': int(item.get('quantity', 1))
                        }
                        total += item_data['price'] * item_data['quantity']
                        processed_items.append(item_data)
                
                cart_dict['cart_items'] = processed_items
                cart_dict['total'] = float(total)
                
            print(f"Processed cart: {cart_dict}")
            return cart_dict
            
        except Exception as e:
            print(f"Error getting cart: {e}")
            return {'cart_items': [], 'total': 0.0}

    @staticmethod
    def add_item(customer_id, product_id):
        try:
            print(f"Adding item {product_id} to cart for customer {customer_id}")
            cart_ref = db.collection('carts').document(str(customer_id))
            cart = cart_ref.get()
            
            if cart.exists:
                cart_data = cart.to_dict()
                items = cart_data.get('items', [])
                
                # Check if product already in cart
                for item in items:
                    if item['product_id'] == product_id:
                        item['quantity'] = int(item.get('quantity', 1)) + 1
                        cart_ref.update({'items': items})
                        print("Updated quantity for existing item")
                        return True
                
                # Add new item
                items.append({
                    'product_id': product_id,
                    'quantity': 1
                })
                cart_ref.update({'items': items})
                print("Added new item to cart")
            else:
                # Create new cart
                cart_ref.set({
                    'items': [{
                        'product_id': product_id,
                        'quantity': 1
                    }]
                })
                print("Created new cart with item")
            return True
        except Exception as e:
            print(f"Error adding to cart: {e}")
            return False

    @staticmethod
    def update_quantity(customer_id, product_id, quantity):
        try:
            print(f"Updating quantity for item {product_id} to {quantity}")
            cart_ref = db.collection('carts').document(str(customer_id))
            cart = cart_ref.get()
            
            if cart.exists:
                cart_data = cart.to_dict()
                items = cart_data.get('items', [])
                
                for item in items:
                    if item['product_id'] == product_id:
                        item['quantity'] = max(1, int(quantity))
                        cart_ref.update({'items': items})
                        print("Updated quantity successfully")
                        return True
                        
            print("Cart or item not found")
            return False
        except Exception as e:
            print(f"Error updating cart quantity: {e}")
            return False

    @staticmethod
    def remove_item(customer_id, product_id):
        try:
            print(f"Removing item {product_id} from cart")
            cart_ref = db.collection('carts').document(str(customer_id))
            cart = cart_ref.get()
            
            if cart.exists:
                cart_data = cart.to_dict()
                items = cart_data.get('items', [])
                
                # Remove item with matching product_id
                items = [item for item in items if item['product_id'] != product_id]
                cart_ref.update({'items': items})
                print("Removed item successfully")
                return True
                
            print("Cart not found")
            return False
        except Exception as e:
            print(f"Error removing from cart: {e}")
            return False

class User(UserMixin):
    def __init__(self, id, email, password_hash, role='customer', name=None, phone=None, address=None, created_at=None):
        self.id = id
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.name = name
        self.phone = phone
        self.address = address
        self.created_at = created_at or datetime.now()
    
    @property
    def is_admin(self):
        """Return True if user has admin role"""
        return self.role == 'admin'
    
    def get_id(self):
        """Return the user ID as a unicode string for Flask-Login"""
        return str(self.id)
    
    def __repr__(self):
        return f'<User {self.email}, role={self.role}, admin={self.is_admin}>'

    @staticmethod
    def create(data):
        # Generate a unique ID for the user
        user_id = str(uuid.uuid4())
        
        # Hash the password before storing
        data['password'] = generate_password_hash(data['password'])
        
        # Add creation timestamp
        data['created_at'] = datetime.now()
        
        # Set default role if not provided
        if 'role' not in data:
            data['role'] = 'customer'
            
        # Save to Firestore
        try:
            if db:
                user_ref = db.collection('users').document(user_id)
                user_ref.set(data)
                return User.get(user_id)
            else:
                print("WARNING: Database not available, user creation skipped")
                # Return a mock user for development/testing without Firebase
                return User(user_id, data['email'], data['password'], data.get('role', 'customer'),
                           data.get('name'), data.get('phone'), data.get('address'), data['created_at'])
        except Exception as e:
            print(f"Error creating user: {str(e)}")
            return None
    
    @staticmethod
    def get(user_id):
        try:
            # Special case for admin user (important for session persistence)
            if user_id == 'admin':
                print("Special handling for admin user in User.get")
                return User(
                    id='admin',
                    email='admin@example.com',
                    password_hash=generate_password_hash('admin123'),
                    role='admin',
                    name='Admin User',
                    created_at=datetime.now()
                )
            
            if db:
                user_doc = db.collection('users').document(user_id).get()
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    return User(
                        id=user_id,
                        email=user_data.get('email'),
                        password_hash=user_data.get('password'),
                        role=user_data.get('role', 'customer'),
                        name=user_data.get('name'),
                        phone=user_data.get('phone'),
                        address=user_data.get('address'),
                        created_at=user_data.get('created_at')
                    )
            else:
                print("WARNING: Database not available, using mock data")
                # In development mode without Firebase, return a mock admin for testing
                if user_id == 'admin':
                    return User(
                        id='admin',
                        email='admin@example.com',
                        password_hash=generate_password_hash('admin123'),
                        role='admin',
                        name='Admin User',
                        created_at=datetime.now()
                    )
            return None
        except Exception as e:
            print(f"Error getting user: {str(e)}")
            # Last resort fallback for admin
            if user_id == 'admin':
                return User(
                    id='admin',
                    email='admin@example.com',
                    password_hash=generate_password_hash('admin123'),
                    role='admin',
                    name='Admin User',
                    created_at=datetime.now()
                )
            return None
    
    @staticmethod
    def get_by_email(email):
        try:
            if db:
                users_ref = db.collection('users').where('email', '==', email).limit(1).get()
                for user_doc in users_ref:
                    user_data = user_doc.to_dict()
                    return User(
                        id=user_doc.id,
                        email=user_data.get('email'),
                        password_hash=user_data.get('password'),
                        role=user_data.get('role', 'customer'),
                        name=user_data.get('name'),
                        phone=user_data.get('phone'),
                        address=user_data.get('address'),
                        created_at=user_data.get('created_at')
                    )
            else:
                print("WARNING: Database not available, using mock data")
                # In development mode without Firebase, return mock admin only
                if email == 'admin@example.com':
                    return User(
                        id='admin',
                        email='admin@example.com',
                        password_hash=generate_password_hash('admin123'),
                        role='admin',
                        name='Admin User',
                        created_at=datetime.now()
                    )
                elif email == 'test@example.com':
                    # Add a test user for demo/development purposes
                    return User(
                        id='test-user',
                        email='test@example.com',
                        password_hash=generate_password_hash('test123'),
                        role='customer',
                        name='Test User',
                        created_at=datetime.now()
                    )
            return None
        except Exception as e:
            print(f"Error finding user by email: {str(e)}")
            # As a last resort fallback, allow admin login for testing
            if email == 'admin@example.com':
                return User(
                    id='admin',
                    email='admin@example.com',
                    password_hash=generate_password_hash('admin123'),
                    role='admin',
                    name='Admin User',
                    created_at=datetime.now()
                )
            return None
    
    @staticmethod
    def authenticate(email, password):
        """Authenticate a user with email and password"""
        try:
            # Special case for admin (always allow admin login for emergencies)
            if email == 'admin@example.com' and password == 'admin123':
                return User(
                    id='admin',
                    email='admin@example.com',
                    password_hash=generate_password_hash('admin123'),
                    role='admin',
                    name='Admin User',
                    created_at=datetime.now()
                )
            
            # Try to get user by email
            user = User.get_by_email(email)
            if not user:
                print(f"No user found with email: {email}")
                return None
            
            # Verify password
            if check_password_hash(user.password_hash, password):
                return user
            else:
                print("Password verification failed")
                return None
        except Exception as e:
            print(f"Authentication error: {str(e)}")
            # Last resort fallback for admin
            if email == 'admin@example.com' and password == 'admin123':
                return User(
                    id='admin',
                    email='admin@example.com',
                    password_hash=generate_password_hash('admin123'),
                    role='admin',
                    name='Admin User',
                    created_at=datetime.now()
                )
            return None
    
    def update(self, data):
        try:
            if db:
                user_ref = db.collection('users').document(self.id)
                # Don't update password if it's not provided
                if 'password' in data and data['password']:
                    data['password'] = generate_password_hash(data['password'])
                elif 'password' in data:
                    del data['password']  # Remove empty password field
                
                # Update the user document
                user_ref.update(data)
                
                # Update the current user object
                for key, value in data.items():
                    setattr(self, key, value)
                
                return True
            else:
                print("WARNING: Database not available, update skipped")
                # Just update the current object in memory for development
                for key, value in data.items():
                    setattr(self, key, value)
                return True
        except Exception as e:
            print(f"Error updating user: {str(e)}")
            return False
    
    @staticmethod
    def get_all():
        try:
            if db:
                users = []
                users_ref = db.collection('users').get()
                for user_doc in users_ref:
                    user_data = user_doc.to_dict()
                    users.append({
                        'id': user_doc.id,
                        'email': user_data.get('email'),
                        'role': user_data.get('role', 'customer'),
                        'name': user_data.get('name'),
                        'phone': user_data.get('phone'),
                        'address': user_data.get('address'),
                        'created_at': user_data.get('created_at')
                    })
                return users
            else:
                print("WARNING: Database not available, using mock data")
                # Return mock data for development
                return [
                    {
                        'id': 'admin',
                        'email': 'admin@example.com',
                        'role': 'admin',
                        'name': 'Admin User',
                        'created_at': datetime.now()
                    },
                    {
                        'id': 'user1',
                        'email': 'user1@example.com',
                        'role': 'customer',
                        'name': 'Test Customer',
                        'phone': '123-456-7890',
                        'address': '123 Test St',
                        'created_at': datetime.now() - timedelta(days=5)
                    }
                ]
        except Exception as e:
            print(f"Error getting all users: {str(e)}")
            return []
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'role': self.role,
            'name': self.name,
            'phone': self.phone,
            'address': self.address,
            'created_at': self.created_at
        }

class UserPreferences:
    @staticmethod
    def create_or_update(user_id, preferences):
        try:
            # Add timestamp to preferences
            preferences['updated_at'] = datetime.now()
            
            # Convert list preferences to comma-separated strings for easier processing
            if 'occasions' in preferences:
                preferences['occasions'] = ','.join(preferences['occasions'])
            if 'flavors' in preferences:
                preferences['flavors'] = ','.join(preferences['flavors'])
            if 'dietary' in preferences:
                preferences['dietary'] = ','.join(preferences['dietary'])
            
            # Store in Firestore
            db.collection('user_preferences').document(user_id).set(preferences, merge=True)
            return True
        except Exception as e:
            print(f"Error storing preferences: {e}")
            return False

    @staticmethod
    def get_preferences(user_id):
        try:
            doc = db.collection('user_preferences').document(user_id).get()
            if doc.exists:
                prefs = doc.to_dict()
                # Convert comma-separated strings back to lists
                if 'occasions' in prefs:
                    prefs['occasions'] = prefs['occasions'].split(',')
                if 'flavors' in prefs:
                    prefs['flavors'] = prefs['flavors'].split(',')
                if 'dietary' in prefs:
                    prefs['dietary'] = prefs['dietary'].split(',')
                return prefs
            return None
        except Exception as e:
            print(f"Error getting preferences: {e}")
            return None

    @staticmethod
    def get_all_preferences():
        try:
            docs = db.collection('user_preferences').stream()
            all_prefs = []
            for doc in docs:
                prefs = doc.to_dict()
                prefs['user_id'] = doc.id
                # Convert comma-separated strings back to lists
                if 'occasions' in prefs:
                    prefs['occasions'] = prefs['occasions'].split(',')
                if 'flavors' in prefs:
                    prefs['flavors'] = prefs['flavors'].split(',')
                if 'dietary' in prefs:
                    prefs['dietary'] = prefs['dietary'].split(',')
                all_prefs.append(prefs)
            return all_prefs
        except Exception as e:
            print(f"Error getting all preferences: {e}")
            return []

    @staticmethod
    def _encode_preferences(preferences):
        """Convert preferences to numerical features for ML"""
        features = []
        
        # Age group encoding
        age_groups = ['under_18', '18_24', '25_34', '35_44', '45_plus']
        features.extend([1 if preferences.get('age_group') == ag else 0 for ag in age_groups])
        
        # Occasions encoding
        occasions = ['birthdays', 'weddings', 'anniversaries', 'casual']
        user_occasions = preferences.get('occasions', [])
        features.extend([1 if occ in user_occasions else 0 for occ in occasions])
        
        # Flavors encoding
        flavors = ['chocolate', 'vanilla', 'fruit', 'nutty']
        user_flavors = preferences.get('flavors', [])
        features.extend([1 if flav in user_flavors else 0 for flav in flavors])
        
        # Price range encoding
        price_ranges = ['budget', 'mid', 'premium', 'luxury']
        features.extend([1 if preferences.get('price_range') == pr else 0 for pr in price_ranges])
        
        # Purchase frequency encoding
        frequencies = ['rarely', 'occasionally', 'regularly', 'frequently']
        features.extend([1 if preferences.get('frequency') == freq else 0 for freq in frequencies])
        
        # Dietary preferences encoding
        dietary = ['none', 'vegetarian', 'gluten_free', 'sugar_free']
        user_dietary = preferences.get('dietary', [])
        features.extend([1 if diet in user_dietary else 0 for diet in dietary])
        
        return features

    @staticmethod
    def _encode_product(product):
        """Convert product attributes to numerical features for ML"""
        features = []
        
        # Extract text for analysis
        text = (product.get('name', '') + ' ' + product.get('description', '')).lower()
        
        # Price range encoding
        price = float(product.get('price', 0))
        features.extend([
            1 if price < 300 else 0,  # budget
            1 if 300 <= price <= 500 else 0,  # mid
            1 if 500 < price <= 1000 else 0,  # premium
            1 if price > 1000 else 0  # luxury
        ])
        
        # Occasion encoding
        features.extend([
            1 if 'birthday' in text else 0,
            1 if 'wedding' in text else 0,
            1 if 'anniversary' in text else 0,
            1 if any(word in text for word in ['casual', 'classic', 'regular']) else 0
        ])
        
        # Flavor encoding
        features.extend([
            1 if 'chocolate' in text else 0,
            1 if 'vanilla' in text else 0,
            1 if any(word in text for word in ['fruit', 'berry', 'citrus']) else 0,
            1 if any(word in text for word in ['nut', 'pecan', 'almond']) else 0
        ])
        
        # Dietary encoding
        features.extend([
            1,  # normal (all products are considered normal by default)
            1 if 'vegetarian' in text else 0,
            1 if 'gluten-free' in text or 'gluten free' in text else 0,
            1 if 'sugar-free' in text or 'sugar free' in text else 0
        ])
        
        return features

    @staticmethod
    def get_recommendations(user_id, all_products, max_recommendations=4):
        try:
            from sklearn.neighbors import NearestNeighbors
            import numpy as np
            
            # Get user preferences
            user_prefs = UserPreferences.get_preferences(user_id)
            if not user_prefs:
                return []

            # Encode user preferences
            user_features = UserPreferences._encode_preferences(user_prefs)
            
            # Encode all products
            product_features = [UserPreferences._encode_product(p) for p in all_products]
            
            if not product_features:
                return []
            
            # Convert to numpy arrays
            user_features = np.array(user_features).reshape(1, -1)
            product_features = np.array(product_features)
            
            # Initialize and fit NearestNeighbors
            nn = NearestNeighbors(n_neighbors=min(max_recommendations, len(all_products)), metric='cosine')
            nn.fit(product_features)
            
            # Find nearest neighbors
            distances, indices = nn.kneighbors(user_features)
            
            # Get recommended products
            recommended_products = [all_products[i] for i in indices[0]]
            
            # Add confidence scores
            for i, product in enumerate(recommended_products):
                product['recommendation_score'] = float(1 - distances[0][i])
            
            # Sort by score
            recommended_products.sort(key=lambda x: x['recommendation_score'], reverse=True)
            
            return recommended_products

        except Exception as e:
            print(f"Error getting ML recommendations: {e}")
            import traceback
            traceback.print_exc()
            return []

class Chat:
    @staticmethod
    def create(data):
        try:
            # Add timestamp if not present
            if 'timestamp' not in data:
                data['timestamp'] = datetime.now()
                
            # Store in Firestore
            doc_ref = db.collection('chat_interactions').document()
            doc_ref.set(data)
            return doc_ref.id
        except Exception as e:
            print(f"Error creating chat interaction: {e}")
            raise

    @staticmethod
    def get_user_history(user_id, limit=10):
        try:
            interactions = db.collection('chat_interactions')\
                .where('user_id', '==', user_id)\
                .order_by('timestamp', direction=firestore.Query.DESCENDING)\
                .limit(limit)\
                .stream()
            
            history = []
            for doc in interactions:
                data = doc.to_dict()
                history.extend([
                    {
                        'sender': 'user',
                        'message': data.get('user_message', ''),
                        'timestamp': data.get('timestamp').isoformat()
                    },
                    {
                        'sender': 'assistant',
                        'message': data.get('ai_response', ''),
                        'timestamp': data.get('timestamp').isoformat()
                    }
                ])
            return history
        except Exception as e:
            print(f"Error getting user chat history: {e}")
            return []

    @staticmethod
    def get_all_interactions():
        try:
            interactions = db.collection('chat_interactions')\
                .order_by('timestamp', direction=firestore.Query.DESCENDING)\
                .stream()
            return [{'id': doc.id, **doc.to_dict()} for doc in interactions]
        except Exception as e:
            print(f"Error getting chat interactions: {e}")
            return []
    
    @staticmethod
    def mark_as_resolved(interaction_id):
        try:
            db.collection('chat_interactions').document(interaction_id).update({
                'resolved': True,
                'resolved_at': datetime.now()
            })
            return True
        except Exception as e:
            print(f"Error marking chat as resolved: {e}")
            return False