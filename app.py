from flask import Flask, render_template, request, redirect, url_for, g
import sqlite3
import os
if os.path.exists("workers_v2.db"):
    os.remove("workers_v2.db")
    print("workers_v2.db deleted")
from werkzeug.utils import secure_filename
from PIL import Image


app = Flask(__name__)

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db_connection():
    conn = sqlite3.connect("workers_v2.db")
    conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

if os.path.exists('workers_v2.db'):
    os.remove('workers_v2.db')
    print("workers_v2.db deleted")

def init_db():
    conn = get_db_connection()
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
        phone TEXT,
        status TEXT DEFAULT 'pending'
    )''')
    c.execute('DROP TABLE IF EXISTS jobs')
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
    conn = sqlite3.connect('database.db')
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
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        skill = request.form['skill']
        location = request.form['location']
        years = request.form['years']

        photo_filename = 'default.png'
        if 'photo' in request.files:
            file = request.files['photo']
            if file.filename!= '' and allowed_file(file.filename):
                photo_filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], photo_filename))

        conn = sqlite3.connect('workers.db')
        c = conn.cursor()
        c.execute("INSERT INTO workers (name, phone, skill, location, years, photo) VALUES (?,?,?,?,?,?)",
                  (name, phone, skill, location, years, photo_filename))
        conn.commit()
        conn.close()
        return "Worker added! <a href='/'>Go Search</a>"

    return render_template('worker-signup.html')

def get_workers(profession=None, location=None):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # This gets all 10 columns: id, name, prof, location, price, exp, rating, total_ratings, photo, phone
    query = "SELECT id, name, profession, location, price, experience, rating, total_ratings, photo, phone FROM workers WHERE 1=1"
    params = []
    
    if profession:
        query += " AND profession LIKE ?"
        params.append(f"%{profession}%")
    
    if location:
        query += " AND location LIKE ?"
        params.append(f"%{location}%")
    
    c.execute(query, params)
    workers = c.fetchall()
    conn.close()
    return workers
    
@app.route('/search')
def search():
    query = request.args.get('query', '') 
    location = request.args.get('location', '') 
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    min_exp = request.args.get('min_exp', type=int)
    min_rating = request.args.get('min_rating', type=float)

    conn = get_db_connection()
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
    conn = sqlite3.connect('workers.db')
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

from PIL import Image  # ADD AT TOP
import os
from werkzeug.utils import secure_filename

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

        conn = get_db_connection()
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
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM workers WHERE id =?", (id,))
    worker = c.fetchone()
    conn.close()
    return render_template("worker.html", w=worker)

@app.route('/admin')
def admin():
    db = get_db_connection()
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
    db = get_db_connection()
    db.execute("UPDATE workers SET status='approved' WHERE id=?", (id,))
    db.commit()
    db.close()
    return redirect('/admin')

@app.route('/admin/delete/<int:id>')
def delete_worker(id):
    db = get_db_connection()
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
        
        db = get_db_connection()
        db.execute("INSERT INTO jobs (customer_name, phone, job_type, location, description, budget, status) VALUES (?,?,?,?,?,?,? 'open')",
                   (name, phone, job_type, location, description, budget))
        db.commit()
        db.close()
        return redirect('/jobs')
        
    return render_template('post_job.html')

@app.route('/jobs')
def jobs():
    db = get_db_connection()
    c = db.cursor()
    all_jobs = c.execute("SELECT * FROM jobs WHERE status='open' ORDER BY id DESC").fetchall()
    db.close()
    return render_template('jobs.html', jobs=all_jobs)

if __name__ == '__main__':
    app.run(debug=True)
