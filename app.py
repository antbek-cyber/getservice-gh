from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
from PIL import Image
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask import request
from sqlalchemy import or_
from functools import wraps
import cloudinary
import cloudinary.uploader
import math
import io
from datetime import datetime
PAYSTACK_SECRET = os.environ.get('PAYSTACK_SECRET_KEY')

cloudinary.config(
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
  api_key = os.getenv('CLOUDINARY_API_KEY'),
  api_secret = os.getenv('CLOUDINARY_API_SECRET')
  
)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-change-this'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///getservice.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

from sqlalchemy import text

# Auto-add missing columns (for free plan without shell)
with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE worker ADD COLUMN IF NOT EXISTS fcm_token VARCHAR(300);"))
        db.session.commit()
        print("Auto-migration: fcm_token added")
    except Exception as e:
        db.session.rollback()
        print(f"Auto-migration skip: {e}")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
 


    


if __name__ == '__main__':
    app.run(debug=True)
