from flask import Flask, render_template, request, redirect, url_for, flash
import os
from PIL import Image
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask import request
from sqlalchemy import or_

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

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
 
@login_manager.user_loader
def load_user(user_id):
     return Worker.query.get(int(user_id))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))  

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80))
    category = db.Column(db.String(80))
    location = db.Column(db.String(120))

class Worker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_name = db.Column(db.String(80))  # ADD worker_
    worker_profession = db.Column(db.String(80)) # ADD worker_
    worker_location = db.Column(db.String(120)) # ADD worker_
    price = db.Column(db.Float)
    experience = db.Column(db.Integer)
    rating = db.Column(db.Float, default=0)
    total_ratings = db.Column(db.Integer, default=0)
    photo = db.Column(db.String(200), default='default.png')
    phone = db.Column(db.String(20), unique=True)
    password_hash = db.Column(db.String(128))
    worker_status = db.Column(db.String(20), default='pending') # ADD worker_

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(80))
    phone = db.Column(db.String(20))
    job_type = db.Column(db.String(80))
    worker_location = db.Column(db.String(120)) # ADD worker_ if needed
    description = db.Column(db.Text)
    job_status = db.Column(db.String(20), default='open') # ADD THIS

class WorkerProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('worker.id'), unique=True)
    bio = db.Column(db.Text)
    skills = db.Column(db.String(200))
    profile_pic = db.Column(db.String(100))

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
        profile_pic_url = 'default.png'

        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                profile_pic_url = f'/static/uploads/{filename}'

        try:
            # Use SQLAlchemy instead of raw sqlite
            new_worker = Worker(
                name=name,
                phone=phone,
                password_hash=hashed_pw,
                profession=job_type,
                location=location,
                experience=years,
                photo=profile_pic_url,
                status='pending'
            )
            db.session.add(new_worker)
            db.session.commit()
            flash('Signup successful! Wait for admin approval.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('Phone number already exists', 'danger')
            return redirect(url_for('signup'))
   
    return render_template('signup.html') 


@app.route('/search')
def search():
    query = request.args.get('q', '')
    location = request.args.get('location', '')
    workers = Worker.query.filter_by(worker_status='approved').all()
    return render_template('search_results.html', workers=workers)


    
@app.route('/rate/<int:worker_id>/<int:stars>')
def rate(worker_id, stars):
    worker = Worker.query.get(worker_id)
    
    if worker:
        current_total = worker.total_ratings
        current_rating = worker.rating
        
        new_total = current_total + 1
        new_rating = ((current_rating * current_total) + stars) / new_total
        
        worker.total_ratings = new_total
        worker.rating = new_rating
        
        db.session.commit()
    
    return redirect(request.referrer) # Go back to search page

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

        # Create new worker with SQLAlchemy
        new_worker = Worker(
            name=name,
            profession=profession,
            location=location,
            price=float(price),
            experience=int(experience),
            phone=phone,
            photo=filename,
            status='pending'
        )
        db.session.add(new_worker)
        db.session.commit()

        flash('Registration successful! Wait for admin approval.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

    
@app.route("/debug")
def debug():
    workers = get_workers()
    return f"<h1>Found {len(workers)} workers</h1><pre>{workers}</pre>"

@app.route('/worker/<int:id>')
def worker_profile(id):
    worker = Worker.query.get(id)
    return render_template("worker.html", w=worker)

@app.route('/admin')
def admin():
    total_workers = Worker.query.count()
    total_jobs = Job.query.count()
    pending_approvals = Worker.query.filter_by(status='pending').count()
    workers = Worker.query.order_by(Worker.id.desc()).all()
    
    return render_template('admin.html',
        total_workers=total_workers,
        total_jobs=total_jobs,
        pending_approvals=pending_approvals,
        workers=workers)

@app.route('/admin/approve/<int:id>')
def approve(id):
    worker = Worker.query.get(id)
    if worker:
        worker.status = 'approved'
        db.session.commit()
    return redirect('/admin')

@app.route('/admin/delete/<int:id>')
def delete_worker(id):
    worker = Worker.query.get(id)
    if worker:
        db.session.delete(worker)
        db.session.commit()
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

        new_job = Job(
            customer_name=name,
            phone=phone,
            job_type=job_type,
            location=location,
            budget=float(budget),
            status='open'
        )
        db.session.add(new_job)
        db.session.commit()

        flash('Job posted successfully!', 'success')
        return redirect(url_for('home'))

    return render_template('post_job.html')

@app.route('/jobs')
def view_jobs():
    jobs = Job.query.filter_by(job_status='open').all()
    return render_template('jobs.html', jobs=jobs)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        
        worker = Worker.query.filter_by(phone=phone).first()
        
        if worker and check_password_hash(worker.password_hash, password):
            login_user(worker)
            flash('Logged in successfully', 'success')
            
            if worker.status != 'approved':
                flash('Wait for admin approval', 'warning')
                return redirect(url_for('login'))
                
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid phone or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/approve_all')
def approve_all():
    Worker.query.update({Worker.worker_status: 'approved'})
    db.session.commit()
    return "All workers approved!"

@app.route('/worker/profile', methods=['GET', 'POST'])
@login_required
def edit_worker_profile():
    profile = WorkerProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        profile = WorkerProfile(user_id=current_user.id)
         #handle POST upload logic here later
    return render_template('worker_profile.html', profile=profile)

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
