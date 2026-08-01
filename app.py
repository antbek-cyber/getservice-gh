from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os
from werkzeug.utils import secure_filename


app = Flask(__name__)

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

if os.path.exists('database.db'):
    os.remove('database.db')
    print("Old database deleted")

def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS workers") # <-- FORCE DROP
    c.execute('''CREATE TABLE workers
                 (id INTEGER PRIMARY KEY,
                  name TEXT,
                  profession TEXT,
                  location TEXT,
                  price REAL,
                  experience INTEGER,
                  rating REAL,
                  total_ratings INTEGER,
                  photo TEXT,
                  phone TEXT)''')
    conn.commit()
    conn.close()
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS workers
                 (id INTEGER PRIMARY KEY,
                  name TEXT,
                  profession TEXT,
                  location TEXT,
                  price REAL,
                  experience INTEGER,
                  rating REAL,
                  total_ratings INTEGER,
                  photo TEXT,
                  phone TEXT)''')
    conn.commit()
    conn.close()

def seed_data():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # DELETE ALL OLD DATA FIRST
    c.execute("DELETE FROM workers")
    
    workers = [
        ('Kwame Mensah', 'Plumber', 'Kumasi', 80.0, 5, 4.5, 12, 'default.png', '0241234567'),
        ('Ama Boateng', 'Electrician', 'Accra', 100.0, 3, 4.8, 20, 'default.png', '0559876543'),
        ('Kofi Annan', 'Plumber', 'Kumasi', 70.0, 2, 4.0, 8, 'default.png', '0205554433')
    ]
    c.executemany("INSERT INTO workers (name, profession, location, price, experience, rating, total_ratings, photo, phone) VALUES (?,?,?,?,?,?,?,?,?)", workers)
    conn.commit()
    print("Database seeded with test workers")
    
    conn.close()

init_db()
seed_data() # <-- ADD THIS
 

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
    
 # GET FILTERS FROM URL
@app.route("/search")
def search():
    q = request.args.get("q")
    location = request.args.get("location")
    workers = get_workers(profession=q, location=location) # <-- THIS CALLS THE FUNCTION ABOVE
    return render_template("search.html", workers=workers)

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    filtered_workers = []  # <-- 1. ADD THIS

    c.execute("SELECT * FROM workers WHERE profession LIKE ? AND location LIKE ?", ('%' + query + '%', '%' + location + '%'))
    workers = c.fetchall()

    for worker in workers:
        if min_price and worker['price'] < min_price:
            continue
        if max_price and worker['price'] > max_price:
            continue
        if min_exp and worker['experience'] < min_exp:
            continue
        if min_rating and worker['rating'] < min_rating:
            continue
        
        filtered_workers.append(worker) # <-- 2. THIS ADDS TO THE LIST

    conn.close()
    
    workers = filtered_workers  
    return render_template('search.html', workers=workers) 

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

@app.route('/worker-signup', methods=['GET', 'POST'])
def worker_signup():
    if request.method == 'POST':
        worker = {
            'name': request.form['name'],
            'skill': request.form['skill'], 
            'location': request.form['location'],
            'phone': request.form['phone'],
            'experience': request.form.get('experience', '0')
        }
        workers.append(worker)
        print("New worker added:", workers) # This shows in Render logs
        
        return f"<h2>Thank you {worker['name']}! You are registered.</h2><a href='/'>Go Home</a>"
      
    return render_template('worker-signup.html')
@app.route("/debug")
def debug():
    workers = get_workers()
    return f"<h1>Found {len(workers)} workers</h1><pre>{workers}</pre>"
if __name__ == '__main__':
    app.run(debug=True)
