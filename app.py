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

def init_db():
    conn = sqlite3.connect('workers.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS workers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  phone TEXT NOT NULL,
                  skill TEXT NOT NULL,
                  location TEXT NOT NULL,
                  years INTEGER,
                  photo TEXT,
                  rating REAL DEFAULT 0,
                  total_ratings INTEGER DEFAULT 0)''') # Added rating columns
    conn.commit()
    conn.close()

init_db()

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

@app.route('/search', methods=['GET', 'POST'])
def search():
    
    # GET FILTERS FROM URL
min_price = request.args.get('min_price', type=int)
max_price = request.args.get('max_price', type=int)
min_exp = request.args.get('min_exp', type=int)
min_rating = request.args.get('min_rating', type=float)

# APPLY FILTERS + ADD RATINGS
filtered_workers = []
for worker in workers:
    # Add default rating first - THIS IS YOUR OLD CODE
    worker['rating'] = worker.get('rating', 4.5)
    worker['reviews'] = worker.get('reviews', 12)
    
    # Filter logic - THIS IS THE NEW PART
    if min_price and worker.get('price', 0) < min_price:
        continue
    if max_price and worker.get('price', 9999) > max_price:
        continue
    if min_exp and worker.get('experience', 0) < min_exp:
        continue
    if min_rating and worker.get('rating', 0) < min_rating:
        continue
        
    filtered_workers.append(worker)

workers = filtered_workers  # Use filtered list
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
if __name__ == '__main__':
    app.run(debug=True)