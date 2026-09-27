import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
login_manager = LoginManager()
from sqlalchemy import text
import cloudinary
from extensions import db
from models import *

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
    db_url = os.getenv('DATABASE_URL', 'sqlite:///getservice.db')
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif "postgresql://" in db_url and "psycopg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'worker_login'

    cloudinary.config(
        cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
        api_key = os.getenv('CLOUDINARY_API_KEY'),
        api_secret = os.getenv('CLOUDINARY_API_SECRET')
    )

    # Create tables FIRST, then add columns
    with app.app_context():
        db.create_all()  # <-- THIS WAS MISSING - fixes "users does not exist"
        try:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN DEFAULT FALSE"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_permissions JSON DEFAULT '{}'"))
                conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE'))
                conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN DEFAULT FALSE'))
                conn.commit()
            print("Admin check OK")
        except Exception as e:
            print(f"Skip admin migration: {e}")

        try:
            import routes
            print("Routes loaded OK")
        except Exception as e:
            print(f"Routes load error: {e}")

    return app

app = create_app()

# TEMP SETUP ROUTE - DELETE AFTER YOU ARE ADMIN
@app.route('/setup-super-admin-xyz123')
def setup_super_admin():
    from flask import request
    email = request.args.get('email')
    if not email:
        return "Add ?email=antbek264@gmail.com to URL"
    try:
        from models import User
        user = User.query.filter_by(email=email).first()
        if not user:
            return f"User {email} not found. Register first on the website."
        user.is_admin = True
        user.is_super_admin = True
        user.role = 'admin'
        db.session.commit()
        return f"SUCCESS: {email} is now Super Admin! Delete this route now."
    except Exception as e:
        return f"Error: {e}"
