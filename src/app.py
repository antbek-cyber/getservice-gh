import os
from flask import Flask
from sqlalchemy import text
import cloudinary
from extensions import db, login_manager
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
    from datetime import timedelta
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)
    app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=365)

    db.init_app(app)
    login_manager.init_app(app)

    cloudinary.config(
        cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
        api_key = os.getenv('CLOUDINARY_API_KEY'),
        api_secret = os.getenv('CLOUDINARY_API_SECRET')
    )

    with app.app_context():
        import routes 
        db.create_all()
        print("TABLES CREATED!")
    # THEN alter
        try:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN DEFAULT FALSE"))
                conn.commit()
        except Exception as e:
            print(f"Skip: {e}")
    return app

app = create_app()


