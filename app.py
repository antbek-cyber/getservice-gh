from flask import Flask, render_template, request, redirect, url_for, flash
import os
from PIL import Image
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-change-this'

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# DATABASE SETUP FOR RENDER POSTGRES
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Worker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    image = db.Column(db.String(200))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))  

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, name, phone, user_type):
        self.id = id
        self.name = name
        self.phone = phone
        self.user_type = user_type

@login_manager.user_loader
def load_user(user_id):
    conn = db.session()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if user:
        return User(user['id'], user['name'], user['phone'], user['user_type'])
    return None


    conn = worker.query("workers_v2.db")
    conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

if os.path.exists('workers_v2.db'):
    os.remove('workers_v2.db')
    print("workers_v2.db deleted")

def init_db():
    conn = db.session() # Make sure this returns 'jobs.db'
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS workers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        profession TEXT,
        location TEXT,
        price REAL,
        experience INTEGER,
        rating REAL DEFAULT 0,
        total_ratings INTEGER DEFAULT 0,
        photo TEXT DEFAULT 'default.png',
        phone TEXT UNIQUE,
        password TEXT,
        status TEXT DEFAULT 'pending'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT,
        phone TEXT,
        job_type TEXT,
        location TEXT,
        description TEXT,
        budget TEXT,
        status TEXT DEFAULT 'open'
    )''')
    conn.commit()
    conn.close()

init_db()
            
def seed_data():
    conn = worker.query('database.db')
    c = conn.cursor()
    
    workers = [
        ('Kwame Mensah', 'Plumber', 'Kumasi', 80.0, 5, 4.5, 12, 'default.png', '0241234567'),
        ('Ama Boateng', 'Electrician', 'Accra', 100.0, 3, 4.8, 20, 'default.png', '0559876543'),
        ('Kofi Annan', 'Plumber', 'Kumasi', 70.0, 2, 4.0, 8, 'default.png', '0205554433')
    ]
    c.executemany("INSERT INTO workers (name, profession, location, price, experience, rating, total_ratings, photo, phone) VALUES (?,?,?,?,?,?,?,?,?)", workers)
    conn.commit()
    print("Database seeded with test workers")
    
    conn.close()

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    services = Service.query.all()
    return render_template('index.html', services=services)

@app.route('/add', methods=['POST'])
def add_service():
    name = request.form['name']
    category = request.form['category']
    location = request.form['location']
    new_service = Service(name=name, category=category, location=location)
    db.session.add(new_service)
    db.session.commit()
    flash('Service added successfully!')
    return redirect(url_for('index'))
    
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        password = request.form['password']
        job_type = request.form['job_type']
        location = request.form['location']
        years = request.form['years']

        hashed_pw = generate_password_hash(password)

        profile_pic_url = 'default.png' # <-- SET DEFAULT HERE
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                profile_pic_url = f'/static/uploads/{filename}'

        try: # <-- MOVED INSIDE POST
            conn = worker.query('jobs.db')
            c = conn.cursor()
            
            c.execute("""INSERT INTO workers 
                        (name, profession, location, phone, experience, photo, password, status)
                        VALUES (?,?,?,?,?,?,?,?)""",
                      (name, job_type, location, phone, years, profile_pic_url, hashed_pw, 'pending'))

            conn.commit()
            conn.close()
            return redirect('/login')
        except Exception as e:
            return f"Error: {e}"

    return render_template('signup.html') 
    
@app.route('/search')
def search():
    query = request.args.get('query', '') 
    location = request.args.get('location', '') 
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    min_exp = request.args.get('min_exp', type=int)
    min_rating = request.args.get('min_rating', type=float)

    conn = db.session()
    c = conn.cursor()
    
    c.execute("SELECT * FROM workers WHERE profession LIKE ? AND location LIKE ?", 
              ('%' + query + '%', '%' + location + '%'))
    workers = c.fetchall()

    filtered_workers = []
    for worker in workers:
        if min_price and worker['price'] < min_price:
            continue
        if max_price and worker['price'] > max_price:
            continue
        if min_exp and worker['experience'] < min_exp:
            continue
        if min_rating and worker['rating'] < min_rating:
            continue
        filtered_workers.append(worker)  # ADD TO LIST

    conn.close()
    return render_template('search.html', workers=filtered_workers)
    

@app.route('/rate/<int:worker_id>/<int:stars>')
def rate(worker_id, stars):
    conn = worker.query('workers.db')
    c = conn.cursor()
    c.execute("SELECT rating, total_ratings FROM workers WHERE id =?", (worker_id,))
    current = c.fetchone()

    new_total = current[1] + 1
    new_rating = ((current[0] * current[1]) + stars) / new_total

    c.execute("UPDATE workers SET rating =?, total_ratings =? WHERE id =?",
              (new_rating, new_total, worker_id))
    conn.commit()
    conn.close()
    return redirect(request.referrer) # Go back to search page
    # Temporary "database" - just a list for now
workers = []

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        profession = request.form['profession']
        location = request.form['location']
        price = request.form['price']
        experience = request.form['experience']
        phone = request.form['phone']

        photo = request.files['photo']
        if photo and photo.filename != '':
            filename = secure_filename(photo.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            photo.save(filepath)

            img = Image.open(filepath)
            img.thumbnail((200, 200))
            img.save(filepath, optimize=True, quality=85)
        else:
            filename = 'default.png'

        conn = db.session()
        cur = conn.cursor()
        cur.execute("INSERT INTO workers (name, profession, location, price, experience, phone, photo) VALUES (?,?,?,?,?,?,?)",
                    (name, profession, location, price, experience, phone, filename))
        conn.commit()
        cur.close()
        conn.close()

        return redirect('/')

    return render_template('register.html')
    
@app.route("/debug")
def debug():
    workers = get_workers()
    return f"<h1>Found {len(workers)} workers</h1><pre>{workers}</pre>"

@app.route("/worker/<int:id>")
def worker_profile(id):
    conn = worker.query('database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM workers WHERE id =?", (id,))
    worker = c.fetchone()
    conn.close()
    return render_template("worker.html", w=worker)

@app.route('/admin')
def admin():
    db = db.session()
    c = db.cursor()
    total_workers = c.execute("SELECT COUNT(*) FROM workers").fetchone()[0]
    total_jobs = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    pending_approvals = c.execute("SELECT COUNT(*) FROM workers WHERE status='pending'").fetchone()[0]
    workers = c.execute("SELECT * FROM workers ORDER BY id DESC").fetchall()
    return render_template('admin.html',
                           workers=workers,
                           total_workers=total_workers,
                           total_jobs=total_jobs,
                           pending_approvals=pending_approvals)

@app.route('/admin/approve/<int:id>')
def approve_worker(id):
    db = db.session()
    db.execute("UPDATE workers SET status='approved' WHERE id=?", (id,))
    db.commit()
    db.close()
    return redirect('/admin')

@app.route('/admin/delete/<int:id>')
def delete_worker(id):
    db = db.session()
    db.execute("DELETE FROM workers WHERE id=?", (id,))
    db.commit()
    db.close()
    return redirect('/admin')
@app.route('/post-job', methods=['GET', 'POST'])
def post_job():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        job_type = request.form['job_type']
        location = request.form['location']
        description = request.form['description']
        budget = request.form['budget']
        
        conn = db.session() 
        conn.execute("INSERT INTO jobs (customer_name, phone, job_type, location, description, budget, status) VALUES (?,?,?,?,?,?,?)",
                   (name, phone, job_type, location, description, budget, 'open'))
        conn.commit()
        conn.close()
        return redirect('/jobs')
    return render_template('post_job.html')

@app.route('/jobs')
def jobs():
    db = db.session()
    c = db.cursor()
    all_jobs = c.execute("SELECT * FROM jobs WHERE status='open' ORDER BY id DESC").fetchall()
    db.close()
    return render_template('jobs.html', jobs=all_jobs)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        conn = db.session()
        user = conn.execute('SELECT * FROM users WHERE phone = ?', (phone,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            login_user(User(user['id'], user['name'], user['phone'], user['user_type']))
            if user['user_type'] == 'worker':
                return redirect('/worker/dashboard')
            else:
                return redirect('/customer/dashboard')
        return "Invalid phone or password"
    return render_template('login.html')

@app.route('/worker/dashboard')
@login_required
def worker_dashboard():
    if current_user.user_type != 'worker':
        return "Access Denied"
    conn = db.session()
    profile = conn.execute('SELECT * FROM worker_profiles WHERE user_id = ?', (current_user.id,)).fetchone()
    conn.close()
    return render_template('worker_dashboard.html', profile=profile)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/worker/update', methods=['POST'])
@login_required
def update_worker():
    if current_user.user_type!= 'worker': return "Access Denied"

    job_type = request.form['job_type']
    location = request.form['location']
    fee = request.form['fee']
    bio = request.form['bio']

    profile_pic_path = None
    if 'profile_pic' in request.files:
        file = request.files['profile_pic']
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            profile_pic_path = '/static/uploads/' + filename

    conn = db.session()
    existing = conn.execute('SELECT * FROM worker_profiles WHERE user_id =?', (current_user.id,)).fetchone()
    if existing:
        conn.execute('UPDATE worker_profiles SET job_type=?, location=?, fee=?, bio=?, profile_pic=? WHERE user_id=?',
                     (job_type, location, fee, bio, profile_pic_path or existing['profile_pic'], current_user.id))
    else:
        conn.execute('INSERT INTO worker_profiles (user_id, job_type, location, fee, bio, profile_pic) VALUES (?,?,?,?,?,?)',
                     (current_user.id, job_type, location, fee, bio, profile_pic_path))
    conn.commit()
    conn.close()
    return redirect('/worker/dashboard')

if __name__ == '__main__':
    app.run(debug=True)
