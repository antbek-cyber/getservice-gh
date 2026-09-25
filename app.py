from flask import Flask
import os
import cloudinary
from extensions import db, login_manager

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
    db_url = os.getenv('DATABASE_URL', 'sqlite:///getservice.db')
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif "postgresql://" in db_url and "+psycopg" not in db_url:
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

    # --- ADD THIS BLOCK FOR ADMIN - START ---
    # Auto-add admin columns on free Render (no shell needed)
    from sqlalchemy import text
    with app.app_context():
        try:
            with db.engine.connect() as conn:
                # try both table names "user" and "users"
                for table in ['"user"', 'users', 'worker', 'customer']:
                    try:
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE'))
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN DEFAULT FALSE'))
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS admin_permissions JSON DEFAULT \'{{}}\''))
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT \'worker\''))
                    except:
                        pass
                conn.commit()
            print("Admin columns check done")
        except Exception as e:
            print(f"Admin auto-migration skipped: {e}")
    # --- ADD THIS BLOCK FOR ADMIN - END ---

    return app

app = create_app()

app = create_app()
import routes
import models

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run()
