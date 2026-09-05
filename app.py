

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
