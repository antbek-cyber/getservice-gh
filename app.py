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

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
 
@login_manager.user_loader
def load_user(user_id):
     return Worker.query.get(int(user_id))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20), default="customer")  # customer or admin


class Worker(UserMixin, db.Model):
    __tablename__ = 'worker'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80))
    profession = db.Column(db.String(80))
    location = db.Column(db.String(120))
    price = db.Column(db.Float)
    experience = db.Column(db.Integer)
    rating = db.Column(db.Float, default=0)
    total_ratings = db.Column(db.Integer, default=0)
    photo = db.Column(db.String(500), default='default.png')
    phone = db.Column(db.String(20), unique=True)
    password_hash = db.Column(db.String(500))
    is_approved = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default="pending")
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    bio = db.Column(db.Text, nullable=True)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    phone = db.Column(db.String(20), unique=True)
    password = db.Column(db.String(200))


class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80))
    category = db.Column(db.String(80))
    location = db.Column(db.String(120))


class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(80))
    phone = db.Column(db.String(20))
    job_type = db.Column(db.String(80))
    location = db.Column(db.String(120))
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='open')  

class WorkerProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('worker.id'), unique=True)
    bio = db.Column(db.Text)
    skills = db.Column(db.String(200))
    profile_pic = db.Column(db.String(100))

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    
    # CUSTOMER - now both phone + email
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    customer_email = db.Column(db.String(100))  
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True) 
    
    customer_location = db.Column(db.String(200))
    service_needed = db.Column(db.String(100))
    job_date = db.Column(db.String(50))
    details = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    payment_status = db.Column(db.String(20), default='pending')
    paystack_ref = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    worker = db.relationship('Worker', backref='bookings')
  
    total_amount = db.Column(db.Float, default=200.0)
    commission_amount = db.Column(db.Float, default=0.0)
    worker_payout = db.Column(db.Float, default=0.0)
    

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

@app.route('/join_choice')
def join_choice():
    return render_template('join_choice.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        password = request.form.get('password')
        job_type = request.form.get('job_type')
        location = request.form.get('location')
        years = request.form.get('years')

        file = request.files.get('profile_pic')
        photo = "default.png"
        try:
            if file and file.filename != '':
                result = cloudinary.uploader.upload(file)
                photo = result.get('secure_url', 'default.png')
        except:
            photo= "default.png"
       
        existing = Worker.query.filter_by(phone=phone).first()
        if existing:
          flash('Phone number already exists!')
          return redirect(url_for('signup'))

        hashed_pw = generate_password_hash(password)
        if request.form['password'] != request.form['confirm_password']:
            flash('Passwords do not match!')
            return redirect(url_for('signup'))
            
        try:
            new_worker = Worker(
                name=name,
                phone=phone,
                password_hash=hashed_pw,
                profession=job_type,
                location=location,
                experience=years,
                photo=photo,
                status='approved',
            )

            db.session.add(new_worker)
            db.session.commit()
            flash('Account created! Waiting for admin approval.')
            return redirect(url_for('login'))

        except Exception as e:
            db.session.rollback()
            import traceback
            print(f"!!! SIGNUP FAILED: {str(e)}")
            traceback.print_exc()
            flash(f'Error: {str(e)}')
            return redirect(url_for('signup'))

    return render_template('signup.html')


@app.route('/customer_register', methods=['GET','POST'])
def customer_register():
    if request.method == 'POST':
        email = request.form['email']
        phone = request.form['phone']
        name = request.form['name']
        pw = generate_password_hash(request.form['password'])
        # check if exists
        if Customer.query.filter((Customer.email==email)|(Customer.phone==phone)).first():
            return "Email or phone already used"
        c = Customer(name=name,email=email,phone=phone,password=pw)
        db.session.add(c)
        db.session.commit()
        session['customer_id']=c.id
        return redirect('/customer_dashboard')
    return render_template('customer_register.html')

@app.route('/login_choice')
def login_choice():
    return render_template('login_choice.html')


@app.route('/customer_login', methods=['GET','POST'])
def customer_login():
    if request.method == 'POST':
        print("FORM DATA:", request.form) 
        phone = request.form.get('phone') or request.form.get('email') or request.form.get('customer_phone') or request.form.get('username')
        if not phone:
            return "Missing phone/email field. Form sent: " + str(list(request.form.keys())), 400
        
        customer = Customer.query.filter( (Customer.phone==phone) | (Customer.email==phone) ).first()
        if customer:
            session['customer_id'] = customer.id
            return redirect(f"/book/{session.pop('next_booking', 1)}")
        return "Customer not found for: " + phone
    
    return render_template('customer_login.html')

@app.route('/customer_dashboard')
def customer_dashboard():
    if 'customer_id' not in session:
        return redirect('/customer_login')
    c = Customer.query.get(session['customer_id'])
    if not c:
        session.pop('customer_id', None)
        return redirect('/customer_login')
    bookings = Booking.query.filter(
        (Booking.customer_email==c.email) | (Booking.customer_phone==c.phone) | (Booking.customer_id==c.id)
    ).order_by(Booking.id.desc()).all()
    return render_template('customer_dashboard.html', bookings=bookings, customer=c)

@app.route('/customer_logout')
def customer_logout():
    session.pop('customer_id', None)
    return redirect('/')


@app.route('/search')
def search():
    q = request.args.get('q','').strip()
    user_lat = request.args.get('lat', type=float)
    user_lng = request.args.get('lng', type=float)
    
    try:
        # 1. Get only approved workers
        query = Worker.query.filter_by(is_approved=True)
        
        if q:
            query = query.filter(
                db.or_(
                    Worker.name.ilike(f'%{q}%'),
                    Worker.profession.ilike(f'%{q}%'),
                    Worker.location.ilike(f'%{q}%')
                )
            )
        
        workers = query.all()

        # 2. GPS Distance calculation (your old code)
        if user_lat and user_lng:
            for w in workers:
                if w.latitude and w.longitude:
                    w.distance = haversine(user_lat, user_lng, w.latitude, w.longitude)
                else:
                    w.distance = 9999
            # Sort nearest first
            workers = sorted(workers, key=lambda x: x.distance)
        else:
            for w in workers:
                w.distance = None

        return render_template('results.html', workers=workers, query=q)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f'SEARCH GPS ERROR: {e}<br><pre>{traceback.format_exc()}</pre>'
    

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
    
    return redirect(request.referrer) 



@app.route('/admin')
def admin_dashboard():
    key = request.args.get('key')
    if key != 'admin123':
        return "Unauthorized - use ?key=admin123", 401

    try:
        all_workers = Worker.query.order_by(Worker.id.desc()).all()
        all_bookings = Booking.query.all() if 'Booking' in globals() else []

        print(f"ADMIN: Found {len(all_workers)} workers")
        for w in all_workers:
            print(f" - {w.id}: {w.name} | {w.profession} | {w.status}")

        return render_template('admin.html',
            workers=all_workers,
            bookings=all_bookings
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"ADMIN ERROR: {e}<br><pre>{traceback.format_exc()}</pre>"


@app.route('/approve/<int:id>')
def approve_worker(id):
    key = request.args.get('key')
    if key != 'admin123':
        return "Unauthorized", 401
    worker = Worker.query.get(id)
    if worker:
        worker.is_approved = True
        worker.status = 'approved'
        db.session.commit()
    return redirect('/admin?key=admin123')


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
    jobs = Job.query.filter_by(status='open').all() 
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
                
            return redirect(url_for('worker_dashboard'))
        else:
            flash('Invalid phone or password', 'danger')
    
    return render_template('login.html')


@app.route('/dashboard', methods=['GET','POST'])
@app.route('/worker_dashboard', methods=['GET','POST'])
@login_required
def worker_dashboard():
    if request.method == 'POST':
        try:
            if 'profile_pic' in request.files:
                file = request.files['profile_pic']
                if file and file.filename != '':
                    print(f"Uploading: {file.filename}")
                    result = cloudinary.uploader.upload(file, folder="getservicegh/profile")
                    current_user.photo = result['secure_url']
                    print(f"Saved: {result['secure_url']}")

            current_user.skill = request.form.get('skill')
            current_user.location = request.form.get('location')
            current_user.fee = request.form.get('fee')
            current_user.bio = request.form.get('bio')
            
            db.session.commit()
            print("UPDATE SUCCESS")
            flash('Profile updated!', 'success')
        except Exception as e:
            print(f"ERROR: {e}")
            db.session.rollback()
            flash(f'Error: {e}', 'danger')
        
        return redirect(url_for('worker_dashboard'))

    bookings = Booking.query.filter_by(worker_id=current_user.id).order_by(Booking.id.desc()).all()
    return render_template('worker_dashboard.html', worker=current_user, bookings=bookings)


@app.route('/worker_profile', methods=['GET','POST'])
@login_required
def worker_profile():
    if request.method == 'POST':
        try:
            # Profile pic -> Cloudinary
            if 'profile_pic' in request.files:
                file = request.files['profile_pic']
                if file and file.filename != '' and allowed_file(file.filename):
                    result = cloudinary.uploader.upload(file, folder="getservicegh/profile")
                    current_user.profile_pic = result['secure_url']  # now saves https:// link

            # Work pics -> Cloudinary
            if 'work_pics' in request.files:
                files = request.files.getlist('work_pics')
                urls = []
                for f in files:
                    if f and f.filename != '' and allowed_file(f.filename):
                        res = cloudinary.uploader.upload(f, folder="getservicegh/work")
                        urls.append(res['secure_url'])
                if urls:
                    old = current_user.work_images or ""
                    current_user.work_images = old + "," + ",".join(urls) if old else ",".join(urls)

            current_user.skill = request.form.get('skill')
            current_user.location = request.form.get('location')
            current_user.fee = request.form.get('fee')
            current_user.bio = request.form.get('bio')
            db.session.commit()
            flash('Profile updated!', 'success')
        except Exception as e:
            print(f"Upload error: {e}")
            flash(f'Upload failed: {e}', 'danger')

        return redirect(url_for('worker_dashboard'))
    
    return redirect(url_for('worker_dashboard'))


@app.route('/book/<int:worker_id>')
def book_worker(worker_id):
    if 'customer_id' not in session:
        session['next_booking'] = worker_id
        return redirect('/customer_login')
    
    try:
        customer = Customer.query.get(session['customer_id'])
        worker = Worker.query.get(worker_id)
        if not customer or not worker:
            return "Not found", 404
        
        prof = getattr(worker, 'profession', None) or getattr(worker, 'skill', None) or getattr(worker, 'service', None) or 'Service'
        
        new_booking = Booking(
            worker_id=worker.id,
            customer_id=customer.id,
            customer_name=customer.name,
            customer_phone=customer.phone,
            customer_email=getattr(customer, 'email', ''),
            customer_location=getattr(customer, 'location', 'Kumasi'),
            service_needed=prof,
            status='pending'
            total_amount=200
            commission_amount=30
            worker_payout=170
          
        )
        db.session.add(new_booking)
        db.session.commit()
        return redirect('/customer_dashboard')
    except Exception as e:
        print(f"BOOKING ERROR: {e}")
        db.session.rollback()
        return f"Booking failed: {e}", 500


@app.route('/booking/<int:booking_id>/accept')
@login_required
def accept_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.worker_id != current_user.id:
        flash('Not your booking!', 'danger')
        return redirect(url_for('worker_dashboard'))
    booking.status = 'accepted'
    db.session.commit()
    flash(f'Booking #{booking.id} accepted!', 'success')
    return redirect(url_for('worker_dashboard'))

@app.route('/booking/<int:booking_id>/complete')
@login_required
def complete_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.worker_id != current_user.id:
        return redirect(url_for('worker_dashboard'))
    booking.status = 'completed'
    db.session.commit()
    flash(f'Booking #{booking.id} completed! Great job!', 'success')
    return redirect(url_for('worker_dashboard'))

@app.route('/booking/<int:booking_id>/reject')
@login_required
def reject_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = 'rejected'
    db.session.commit()
    return redirect(url_for('worker_dashboard'))


@app.route('/worker/update', methods=['POST'])
@login_required
def worker_update():
    try:
        # Update job type if you have profile
        job_type = request.form.get('job_type')
        location = request.form.get('location')
        
        # Update current_user fields
        if job_type:
            try:
                current_user.job_type = job_type
            except:
                pass
        if location:
            try:
                current_user.location = location
            except:
                pass

        # HANDLE PHOTO
        file = request.files.get('profile_pic')
        if file and file.filename != '':
            result = cloudinary.uploader.upload(file)
            new_url = result.get('secure_url')
            if new_url:
                current_user.photo = new_url

        db.session.commit()
        flash('Profile updated successfully!', 'success')
    except Exception as e:
        print(f"Update error: {e}")
        flash(f'Update failed: {e}', 'danger')
    
    return redirect(url_for('worker_dashboard'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/worker/profile', methods=['GET', 'POST'])
@login_required
def edit_worker_profile():
    profile = WorkerProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        profile = WorkerProfile(user_id=current_user.id)
         #handle POST upload logic here later
    return render_template('worker_profile.html', profile=profile)


@app.route('/pay-booking/<int:booking_id>')
def pay_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    
    
    total = booking.total_amount or 200  
    commission = total * 0.15
    payout = total - commission
    
    booking.commission_amount = commission
    booking.worker_payout = payout
    db.session.commit()

    # Paystack initialize
    import requests
    url = "https://api.paystack.co/transaction/initialize"
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
    data = {
        "email": booking.customer_email,  # customer pays now!
        "amount": int(total * 100),  # Paystack uses kobo
        "reference": f"booking_{booking.id}_{int(time.time())}",
        "callback_url": f"https://getservice-gh.onrender.com/verify-booking/{booking.id}",
        "metadata": {"booking_id": booking.id, "commission": commission, "payout": payout}
    }
    res = requests.post(url, json=data, headers=headers)
    result = res.json()
    
    if result['status']:
        return redirect(result['data']['authorization_url'])
    else:
        return f"Paystack Error: {result}"

@app.route('/verify-booking/<int:booking_id>')
def verify_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    # verify with paystack...
    # after success:
    booking.payment_status = 'paid'
    booking.status = 'paid' # job fully paid
    db.session.commit()
    flash("Payment successful! Worker will be notified. 15% commission kept by platform.")
    return redirect('/customer_dashboard')
                 

@app.route('/my-jobs')
def my_jobs():
    # worker enters his phone to see jobs
    return render_template('my_jobs_login.html')

@app.route('/my-jobs', methods=['POST'])
def my_jobs_check():
    phone = request.form.get('phone')
    worker = Worker.query.filter_by(phone=phone).first()
    if not worker:
        return "No worker found with that phone"
    bookings = Booking.query.filter_by(worker_id=worker.id).order_by(Booking.created_at.desc()).all()
    return render_template('worker_bookings.html', worker=worker, bookings=bookings)


with app.app_context():
    db.create_all()


# --- AUTO MIGRATION FIX ---
with app.app_context():
    try:
        from sqlalchemy import text
        db.session.execute(text("ALTER TABLE booking ADD COLUMN IF NOT EXISTS total_amount FLOAT DEFAULT 200"))
        db.session.execute(text("ALTER TABLE booking ADD COLUMN IF NOT EXISTS commission_amount FLOAT DEFAULT 0"))
        db.session.execute(text("ALTER TABLE booking ADD COLUMN IF NOT EXISTS worker_payout FLOAT DEFAULT 0"))
        db.session.execute(text("ALTER TABLE booking ADD COLUMN IF NOT EXISTS customer_email VARCHAR(100)"))
        db.session.commit()
        print("✅ DB migrated")
    except Exception as e:
        print(e)
        db.session.rollback()

if __name__ == '__main__':
    app.run(debug=True)
