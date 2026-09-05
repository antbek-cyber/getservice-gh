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
    work_images = db.Column(db.Text, default='')
    phone = db.Column(db.String(20), unique=True)
    password_hash = db.Column(db.String(500))
    is_approved = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default="pending")
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    bio = db.Column(db.Text, nullable=True)
    fcm_token = db.Column(db.String(300))

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    phone = db.Column(db.String(20), unique=True)
    password = db.Column(db.String(200))
    profile_pic = db.Column(db.String(100))


class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80))
    category = db.Column(db.String(80))
    location = db.Column(db.String(120))


class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(80))
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    phone = db.Column(db.String(20))
    job_type = db.Column(db.String(80))
    location = db.Column(db.String(120))
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='open') 
    budget = db.Column(db.String(50))
    title = db.Column(db.String(200))

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

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'))
    message = db.Column(db.String(300))
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    

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


@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            phone = request.form.get('phone')
            job_type = request.form.get('job_type')
            location = request.form.get('location')
            years = request.form.get('years')
            password = request.form.get('password')
            confirm = request.form.get('confirm_password')
           
            if password != confirm:
                flash('Passwords do not match!')
                return redirect(url_for('signup'))
            
            existing = Worker.query.filter_by(phone=phone).first()
            if existing:
                flash('Phone number already exists! Use different number')
                return redirect(url_for('signup'))
   
            photo_url = None
            if 'profile_pic' in request.files:
                file = request.files['profile_pic']
                if file and file.filename != '':
                    result = cloudinary.uploader.upload(file)
                    photo_url = result['secure_url']

            hashed_pw = generate_password_hash(password)

            new_worker = Worker(
                name=name,
                phone=phone,
                password_hash=hashed_pw,
                profession=job_type,
                location=location,
                experience=years,
                photo=photo_url,
                status='approved'
            )
            db.session.add(new_worker)
            db.session.commit()
            
            flash('Account created! Waiting for admin approval.')
            return redirect(url_for('login'))

        except Exception as e:
            print(f"Signup error: {e}")
            flash(f"Error: {e}")
            return redirect(url_for('signup'))

    return render_template('signup.html')
          

@app.route('/customer_register', methods=['GET', 'POST'])
def customer_register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        password = request.form['password']
        confirm = request.form['confirm_password']

        if password != confirm:
            flash("Passwords don't match", "danger")
            return redirect(url_for('customer_register'))

        hashed = generate_password_hash(password) 

        new_customer = Customer(name=name, email=email, phone=phone, password=hashed)
        db.session.add(new_customer)
        db.session.commit()
        flash("Registered! Login now", "success")
        return redirect(url_for('login'))
    return render_template('customer_register.html')
        

@app.route('/login_choice')
def login_choice():
    return render_template('login_choice.html')


@app.route('/customer_login', methods=['GET','POST'])
def customer_login():
    if request.method == 'POST':
        try:
            identifier = request.form.get('email','').strip()
            password = request.form.get('password','').strip()

            if not identifier or not password:
                flash('Please fill all fields')
                return redirect(url_for('customer_login'))

            customer = Customer.query.filter(
                or_(Customer.email == identifier, Customer.phone == identifier)
            ).first()

            if not customer:
                flash('No account found')
                return redirect(url_for('customer_login'))

            # FIX: works whether your model is 'password' or 'password_hash'
            stored_hash = getattr(customer, 'password_hash', None) or getattr(customer, 'password', None)

            if stored_hash and check_password_hash(stored_hash, password):
                session['customer_id'] = customer.id
                session['customer_name'] = customer.name
                return redirect(url_for('customer_dashboard'))
            else:
                flash('Invalid email/phone or password')
                return redirect(url_for('customer_login'))
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            flash(f'Login failed: {e}')
            return redirect(url_for('customer_login'))

    return render_template('customer_login.html')
            

@app.route('/customer_dashboard')
def customer_dashboard():
    if 'customer_id' not in session:
        return redirect('/customer_login')
    
    c = Customer.query.get(session['customer_id'])
    if not c:
        session.pop('customer_id', None)
        return redirect('/customer_login')

    try:
        bookings = Booking.query.filter(
            (Booking.customer_email == c.email) | 
            (Booking.customer_phone == c.phone) |
            (Booking.customer_id == c.id)
        ).order_by(Booking.id.desc()).all()
    except Exception as e:
        print(f"Bookings query failed: {e}")
        try:
            bookings = Booking.query.filter_by(customer_id=c.id).order_by(Booking.id.desc()).all()
        except:
            bookings = []

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
        try:
            customer_id = session.get('customer_id')
            customer = None
            if customer_id:
                customer = Customer.query.get(customer_id)
            else:
                phone = session.get('customer_phone')
                if phone:
                    customer = Customer.query.filter_by(phone=phone).first()
                    if customer:
                        customer_id = customer.id
            
            if not customer:
                return redirect('/customer_login')

            title = request.form.get('title')
            budget = request.form.get('budget')

            new_job = Job(
                customer_id=customer_id,
                customer_name=customer.name if customer else "Customer",
                phone=customer.phone if customer else session.get('customer_phone'),
                job_type=title,  # <-- your form's title goes into job_type
                location=request.form.get('location'),
                description=f"{request.form.get('description')} | Budget: {budget}",
                status='open'
            )
            db.session.add(new_job)
            db.session.commit()
            return redirect('/jobs')

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print("POST JOB ERROR:", tb)
            db.session.rollback()
            return f"<h3>Real Error:</h3><pre>{tb}</pre>", 500

    return render_template('post_job.html')


@app.route('/jobs')
def view_jobs():
    jobs = Job.query.order_by(Job.id.desc()).all()
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
            # Profile pic - accepts any file name
            if 'profile_pic' in request.files:
                file = request.files['profile_pic']
                if file and file.filename != '':
                    result = cloudinary.uploader.upload(file, folder="getservicegh/profile")
                    current_user.photo = result['secure_url']

            # Work pics - works whether form says work_pics or work_images
            work_files = []
            if 'work_pics' in request.files:
                work_files = request.files.getlist('work_pics')
            elif 'work_images' in request.files:
                work_files = request.files.getlist('work_images')

            urls = []
            for f in work_files:
                if f and f.filename != '':
                    res = cloudinary.uploader.upload(f, folder="getservicegh/work")
                    urls.append(res['secure_url'])

                if urls:
                    old = current_user.work_images or ""
                    current_user.work_images = old + "," + ",".join(urls) if old else ",".join(urls)

                # FIX: handle rate with all possible names
                rate_val = request.form.get('fee') or request.form.get('rate') or request.form.get('daily_rate')
                if rate_val:
                    rate_val = rate_val.replace('GH₵','').replace('/day','').strip()
                    try:
                        fv = float(rate_val)
                        # save to whatever column exists
                        if hasattr(current_user, 'fee'):
                            current_user.fee = fv
                        if hasattr(current_user, 'rate'):
                            current_user.rate = fv
                        if hasattr(current_user, 'daily_rate'):
                            current_user.daily_rate = fv
                    except:
                        pass

                for field in ['skill','location','bio']:
                    if field in request.form:
                        setattr(current_user, field, request.form.get(field))

                db.session.commit()
                flash('Updated!', 'success')

            db.session.commit()
            flash('Updated!', 'success')
        except Exception as e:
            import traceback
            traceback.print_exc()
            db.session.rollback()
            flash(f'Failed: {e}')

        return redirect(url_for('worker_dashboard'))

    # GET part - your existing code
    work_images = []
    if current_user.work_images:
        work_images = [img.strip() for img in current_user.work_images.split(',') if img.strip()]

    try:
        bookings = Booking.query.filter_by(worker_id=current_user.id).order_by(Booking.id.desc()).all()
    except:
        bookings = []

    try:
        notifications = Notification.query.filter_by(worker_id=current_user.id, is_read=False).all()
        unread_count = len(notifications)
        new_bookings_count = Booking.query.filter_by(worker_id=current_user.id, status='pending').count()
    except:
        notifications = []
        unread_count = 0
        new_bookings_count = 0

    return render_template('worker_dashboard.html',
                           bookings=bookings,
                           work_images=work_images,
                           notifications=notifications,
                           unread_count=unread_count,
                           new_bookings_count=new_bookings_count,
                           worker=current_user)


@app.route('/push_subscribe', methods=['POST'])
@login_required
def push_subscribe():
    data = request.get_json()
    sub = data.get('subscription')
    # save to DB - you had PushSubscription model
    try:
        existing = PushSubscription.query.filter_by(worker_id=current_user.id).first()
        if existing:
            existing.subscription_json = json.dumps(sub)
        else:
            new_sub = PushSubscription(worker_id=current_user.id, subscription_json=json.dumps(sub))
            db.session.add(new_sub)
        db.session.commit()
        return jsonify({'ok':True})
    except Exception as e:
        print(e)
        return jsonify({'ok':False}), 500


@app.route('/delete_work_image', methods=['POST'])
@login_required
def delete_work_image():
    to_del = request.form.get('image_to_delete','').strip()
    if current_user.work_images and to_del:
        images = [x.strip() for x in current_user.work_images.split(',') if x.strip() and x.strip() != to_del]
        current_user.work_images = ','.join(images)
        db.session.commit()
    return redirect('/worker_dashboard')


@app.route('/worker/<int:worker_id>')
@login_required
def view_worker_profile(worker_id):
    worker = Worker.query.get_or_404(worker_id)
    return render_template('worker_profile.html', worker=worker)


@app.route('/book/<int:worker_id>')
def book_worker(worker_id):
    try:
        customer_id = session.get('customer_id')
        if not customer_id:
            phone = session.get('customer_phone') or session.get('phone')
            if phone:
                c = Customer.query.filter_by(phone=phone).first()
                if c:
                    customer_id = c.id
                    session['customer_id'] = c.id
        
        if not customer_id:
            return redirect('/login')

        worker = Worker.query.get(worker_id)
        customer = Customer.query.get(customer_id)

        # Create booking
        new_booking = Booking(
            worker_id=worker_id,
            customer_id=customer_id,
            customer_name=customer.name if customer else 'Customer',
            customer_phone=customer.phone if customer else '',
            service=worker.skill if worker else 'Service',
            status='pending'
        )
        db.session.add(new_booking)
        db.session.commit()
        return redirect('/customer_dashboard')

    except Exception as e:
        print("BOOKING ERROR:", e)
        db.session.rollback()
        return f"Booking Error: {e}", 500

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

@property
def full_name(self):
    return self.name

#with app.app_context():
    #db.drop_all()
    #db.create_all()
    #print("DB RESET DONE")


if __name__ == '__main__':
    app.run(debug=True)
