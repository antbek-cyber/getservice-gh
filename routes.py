from flask import render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import os
import cloudinary.uploader
import math
import io
from PIL import Image
from datetime import datetime
from sqlalchemy import or_, text
from models import Worker, Customer, Booking, Notification, WorkPhoto, Service
from .models import Review
try:
    from models import Review
except ImportError:
    Review = None
from app import app
from extensions import db, login_manager

PAYSTACK_SECRET = os.environ.get("PAYSTACK_SECRET_KEY")

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}



def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@login_manager.user_loader
def load_user(user_id):
    # ONLY workers use flask-login now
    return Worker.query.get(int(user_id))
    

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
          

@app.route('/customer_register', methods=['GET','POST'])
def customer_register():   # NO @login_required here!
    # If you have this block at top, DELETE it:
    # if 'customer_id' in session:
    #     return redirect(...)
    
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        email = request.form.get('email','').strip()
        phone = request.form.get('phone','').strip()
        password = request.form.get('password','').strip()

        if not name or not email or not password:
            flash('Fill all fields')
            return redirect(url_for('customer_register'))

        existing = Customer.query.filter(
            or_(Customer.email==email, Customer.phone==phone)
        ).first()
        if existing:
            flash('Already registered, please login')
            return redirect(url_for('customer_login'))

        new_customer = Customer(name=name, email=email, phone=phone)
        new_customer.set_password(password)
        db.session.add(new_customer)
        db.session.commit()
        flash('Registration successful! Please login.')
        return redirect(url_for('customer_login'))

    return render_template('customer_register.html')
        

@app.route('/login')
def login_redirect():
    return redirect('/login_choice')

@app.route('/login_choice')
def login_choice():
    return render_template('login_choice.html')


@app.route('/customer_login', methods=['GET','POST'])
def customer_login():
    if request.method == 'POST':
        phone = request.form.get('phone')
        email = request.form.get('email')
        password = request.form.get('password','').strip()
        
        # accept whatever the form sends
        identifier = phone or email or request.form.get('username','').strip()
        
        print(f"LOGIN ATTEMPT identifier={identifier} phone={phone} email={email} pass={password}")

        customer = None
        if identifier:
            customer = Customer.query.filter(
                or_(Customer.phone==identifier, Customer.email==identifier)
            ).first()
        
        if not customer:
            print(f"No customer found for {identifier}")
            flash('No account found with that email/phone')
            return render_template('customer_login.html')

        if customer.check_password(password):
            session.clear()
            session['customer_id'] = customer.id
            print(f"LOGIN SUCCESS id={customer.id}")
            return redirect(url_for('customer_dashboard'))
        else:
            flash('Wrong password')
            print("Wrong password")
    
    return render_template('customer_login.html')

            
@app.route('/customer/dashboard')
def customer_dashboard():
    customer_id = session.get('customer_id')
    if not customer_id:
        return redirect(url_for('customer_login'))
    
    customer = Customer.query.get(int(customer_id))
    # get bookings for THIS customer
    bookings = Booking.query.filter_by(customer_id=customer.id).order_by(Booking.id.desc()).all()
    
    print(f"DASHBOARD customer={customer.id} bookings found={len(bookings)}")
    return render_template('customer_dashboard.html', customer=customer, bookings=bookings)


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

        # 2. GPS Distance calculation - SAFE VERSION
        def haversine(lat1, lon1, lat2, lon2):
            import math
            R = 6371 # km
            dlat = math.radians(lat2-lat1)
            dlon = math.radians(lon2-lon1)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
            return R * 2 * math.asin(math.sqrt(a))

        if user_lat is not None and user_lng is not None:
            for w in workers:
                try:
                    w_lat = getattr(w, 'latitude', None) or getattr(w, 'lat', None)
                    w_lng = getattr(w, 'longitude', None) or getattr(w, 'lng', None)
                    if w_lat and w_lng:
                        w.distance = haversine(user_lat, user_lng, float(w_lat), float(w_lng))
                    else:
                        w.distance = 9999
                except:
                    w.distance = 9999
            workers = sorted(workers, key=lambda x: getattr(x, 'distance', 9999))
        else:
            for w in workers:
                w.distance = None

    # ADD RATINGS FOR SEARCH
    for w in workers:
        try:
            revs = Review.query.filter_by(worker_id=w.id).all()
            w.avg_rating = round(sum([r.rating for r in revs]) / len(revs), 1) if revs else 0
            w.review_count = len(revs)
        except:
            w.avg_rating = 0
            w.review_count = 0

    return render_template('results.html', workers=workers, query=q)
       

    except Exception as e:
        import traceback
        traceback.print_exc()
        # Fallback: return without GPS sorting if error
        try:
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
            for w in workers:
                w.distance = None
            return render_template('results.html', workers=workers, query=q)
        except Exception as e2:
            return f"SEARCH ERROR: {e2}<br><pre>{traceback.format_exc()}</pre>"
    

@app.route('/rate/<int:worker_id>/<int:stars>')
def rate(worker_id, stars):
    worker = Worker.query.get(worker_id)
    booking_id = request.args.get('booking_id')
    if worker:
        current_total = worker.total_ratings or 0
        current_rating = worker.rating or 0
        new_total = current_total + 1
        new_rating = ((current_rating * current_total) + stars) / new_total
        worker.total_ratings = new_total
        worker.rating = new_rating
        
        if booking_id:
            b = Booking.query.get(booking_id)
            if b:
                b.is_rated = True

        db.session.commit()
    return redirect(request.referrer or url_for('customer_dashboard'))



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



@app.route('/worker_login', methods=['GET','POST'])
def worker_login():
    if request.method == 'POST':
        identifier = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not identifier or not password:
            flash("Please fill all fields")
            return redirect('/worker_login')

        # Check BOTH email and phone
        worker = Worker.query.filter(
            (Worker.email == identifier) | (Worker.phone == identifier)
        ).first()

        if worker and worker.check_password(password):
            login_user(worker)
            flash("Login successful!")
            return redirect('/worker_dashboard')
        else:
            flash("Invalid email/phone or password")
            return redirect('/worker_login')

    return render_template('worker_login.html')



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
            try:
        reviews = Review.query.filter_by(worker_id=current_user.id).order_by(Review.created_at.desc()).all()
        avg_rating = round(sum([r.rating for r in reviews]) / len(reviews), 1) if reviews else 0
    except:
        reviews = []
        avg_rating = 0
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
def view_worker_profile(worker_id):
    worker = Worker.query.get_or_404(worker_id)
    return render_template('worker_profile.html', worker=worker)


@app.route('/book/<int:worker_id>')
def book_worker(worker_id):
    customer_id = session.get('customer_id')
    if not customer_id:
        return redirect(url_for('customer_login'))
    
    customer = Customer.query.get(int(customer_id))
    worker = Worker.query.get_or_404(worker_id)
    
    booking = Booking(
    worker_id=worker.id,
    customer_id=customer_id,
    customer_name=customer.name,
    customer_phone=customer.phone,
    status='pending'
    )
    db.session.add(booking)
    db.session.commit()  # commit first so booking.id is created

    notification = Notification(
        worker_id=worker.id,
        booking_id=booking.id,
        message=f"New booking from {customer.name} - {customer.phone}"
    )
    db.session.add(notification)
    db.session.commit()

    print(f"BOOKING SAVED id={booking.id} customer={customer.id} worker={worker.id}")
    flash(f'Booked {worker.name}!', 'success')
    return redirect(url_for('customer_dashboard'))
    
        
@app.route('/booking/<int:booking_id>/accept', methods=['GET','POST'])
def accept_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = 'accepted'
    db.session.commit()
    print(f"BOOKING {booking_id} ACCEPTED")
    flash('Booking accepted!', 'success')
    return redirect(url_for('worker_dashboard'))

@app.route('/booking/<int:booking_id>/decline', methods=['GET','POST'])
def decline_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = 'declined'
    db.session.commit()
    flash('Booking declined', 'info')
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


@app.route('/booking/<int:booking_id>/delete', methods=['POST'])
def delete_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    # delete linked notification too so it doesn't pop again
    Notification.query.filter_by(booking_id=booking.id).delete()
    db.session.delete(booking)
    db.session.commit()
    flash('Booking removed from dashboard', 'info')
    # go back to where you came from
    referer = request.referrer
    if referer and 'worker' in referer:
        return redirect(url_for('worker_dashboard'))
    else:
        return redirect(url_for('customer_dashboard'))

@app.route('/bookings/clear_accepted', methods=['POST'])
def clear_accepted():
    # clears all accepted/declined for current worker or customer
    # worker clear
    if 'worker_id' in session:
        Booking.query.filter_by(worker_id=session['worker_id']).filter(Booking.status != 'pending').delete()
        Notification.query.filter_by(worker_id=session['worker_id']).delete()
    else:
        # customer clear - you use current_user.id if you use flask-login
        try:
            Booking.query.filter_by(customer_id=current_user.id).filter(Booking.status != 'pending').delete()
        except:
            pass
    db.session.commit()
    flash('Old bookings cleared', 'info')
    return redirect(request.referrer or url_for('worker_dashboard'))


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

@app.route('/paystack/verify')
@login_required
def paystack_verify():
    reference = request.args.get('reference')
    booking_id = request.args.get('booking_id')
    
    # Verify with Paystack
    import requests
    headers = {"Authorization": "Bearer sk_test_YOUR_SECRET_KEY"} # replace with secret
    r = requests.get(f"https://api.paystack.co/transaction/verify/{reference}", headers=headers)
    data = r.json()
    
    if data['status'] and data['data']['status'] == 'success':
        booking = Booking.query.get(booking_id)
        if booking:
            booking.payment_status = 'paid'
            booking.payment_reference = reference
            db.session.commit()
            flash('Payment successful! You can now contact worker & rate him.')
    
    return redirect(url_for('customer_dashboard'))
                 

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


@app.route('/debug-bookings')
def debug_bookings():
    customer_id = session.get('customer_id')
    all_b = Booking.query.all()
    mine = Booking.query.filter_by(customer_id=customer_id).all() if customer_id else []
    return f"""
    Your session customer_id: {customer_id} <br>
    Total bookings in DB: {len(all_b)} <br>
    All: {[(b.id, b.customer_id, b.worker_id, b.customer_name) for b in all_b]} <br><br>
    My bookings (filter by customer_id={customer_id}): {len(mine)} <br>
    Mine: {[(b.id, b.worker_id) for b in mine]}
    """


with app.app_context():
    db.create_all()
    print("TABLES CREATED!")

