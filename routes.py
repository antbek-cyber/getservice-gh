from flask import render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import os
import time
import cloudinary.uploader
import math
import io
from PIL import Image
from datetime import datetime
from sqlalchemy import or_, text
from models import Worker, Customer, Booking, Notification, WorkPhoto, Service
from models import Review
import secrets
import requests
try:
    from models import Review
except ImportError:
    Review = None
from app import app
from extensions import db, login_manager

PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY")

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
        import math
        def haversine(lat1, lon1, lat2, lon2):
            R = 6371
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
            return R * 2 * math.asin(math.sqrt(a))

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

        if user_lat is not None and user_lng is not None:
            for w in workers:
                try:
                    w_lat = getattr(w, 'latitude', None) or getattr(w, 'lat', None)
                    w_lng = getattr(w, 'longitude', None) or getattr(w, 'lng', None)
                    w.distance = haversine(user_lat, user_lng, float(w_lat), float(w_lng)) if w_lat and w_lng else 9999
                except:
                    w.distance = 9999
            workers = sorted(workers, key=lambda x: getattr(x, 'distance', 9999))
        else:
            for w in workers:
                w.distance = None

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
        print(f"Search error: {e}")
        return render_template('results.html', workers=[], query=q)
    


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

@app.route('/worker_dashboard')
def worker_dashboard():
    if not current_user.is_authenticated:
        return redirect(url_for('worker_login'))

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
        new_bookings_count = Booking.query.filter_by(worker_id=current_user.id, status="pending").count()
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
        worker=current_user,
        bookings=bookings,
        notifications=notifications,
        unread_count=unread_count,
        new_bookings_count=new_bookings_count,
        work_images=work_images,
        reviews=reviews,
        avg_rating=avg_rating)


   


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
    worker_id=worker_id,
    customer_id=customer_id,
    customer_name=customer.name,
    customer_phone=customer.phone,
    customer_email=customer.email,
    customer_location=getattr(customer, 'location', None) or getattr(customer, 'address', 'Kumasi'),
    service_needed=getattr(worker, 'service', None) or getattr(worker, 'category', None) or 'General Service',
    job_date=str(date.today()) if 'date' in locals() else None,
    details=f"Booking for {worker.name}",
    status='pending',
    payment_status='pending',
    total_amount=200.0,
    commission_amount=40.0,
    worker_payout=160.0
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



@app.route('/verify/booking/<int:booking_id>')
def verify_booking(booking_id):
    reference = request.args.get('reference')
    if not reference:
        flash('No reference provided', 'danger')
        return redirect(url_for('customer_dashboard'))

    # Verify with Paystack
    secret_key = 'sk_test_293d53c43d7a0d7a039166ae9376b8cac677e2df'
    headers = {"Authorization": f"Bearer {secret_key}"}
    try:
        r = requests.get(f"https://api.paystack.co/transaction/verify/{reference}", headers=headers, timeout=10)
        data = r.json()
        if data.get('status') and data['data']['status'] == 'success':
            booking = Booking.query.get(booking_id)
            if booking:
                booking.payment_status = 'paid'
                db.session.commit()
                flash('Payment verified! Thank you', 'success')
            else:
                # This was your TEST 999 booking, so it doesn't exist - that's ok
                flash('Test payment success!', 'success')
        else:
            flash('Payment verification failed', 'danger')
    except Exception as e:
        flash(f'Verification error: {e}', 'danger')

    return redirect(url_for('customer_dashboard'))


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

@app.route('/upload_profile_pic', methods=['POST'])
@login_required
def upload_profile_pic():
    file = request.files.get('profile_pic')
    if file:
        filename = secure_filename(f"worker_{current_user.id}_{file.filename}")
        path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(path)
        current_user.profile_pic = f"/{path}"
        db.session.commit()
    return redirect(url_for('worker_dashboard'))

@app.route('/upload_work_photos', methods=['POST'])
@login_required
def upload_work_photos():
    files = request.files.getlist('work_photos')
    saved = []
    for file in files:
        if file:
            filename = secure_filename(f"work_{current_user.id}_{file.filename}")
            path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(path)
            saved.append(f"/{path}")
    if saved:
        # append to existing
        existing = current_user.work_images or ""
        all_imgs = (existing + "," + ",".join(saved)).strip(",")
        current_user.work_images = all_imgs
        db.session.commit()
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
         #handle POST upload logic here 


# 1. PAY - Initialize
@app.route('/pay/<int:booking_id>', methods=['POST','GET'])
def pay_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    
    ref = f"BOOK-{booking_id}-{secrets.token_hex(4)}"
    booking.paystack_ref = ref
    db.session.commit()

    # Fix for AnonymousUser - get customer email from DB
    if current_user.is_authenticated and hasattr(current_user, 'email'):
        customer_email = current_user.email
    else:
        cust = Customer.query.get(booking.customer_id)
        customer_email = cust.email if cust and cust.email else "customer@getservicegh.com"

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "email": customer_email,
        "amount": int(booking.total_amount * 100),
        "reference": ref,
        "callback_url": url_for('pay_callback', booking_id=booking_id, _external=True)
    }
    r = requests.post("https://api.paystack.co/transaction/initialize", headers=headers, json=data)
    res = r.json()
    if res.get('status'):
        return redirect(res['data']['authorization_url'])
    else:
        flash(f"Payment init failed: {res.get('message')}", "danger")
        return redirect(url_for('customer_dashboard'))

# 2. CALLBACK - What user sees after paying (UX only)
@app.route('/pay/callback/<int:booking_id>')
def pay_callback(booking_id):
    # Don't mark as paid here, just redirect to a "verifying..." page
    # The real confirmation comes from webhook
    flash("Verifying your payment, please wait...")
    # We verify again quickly for UX
    booking = Booking.query.get_or_404(booking_id)
    ref = request.args.get('reference')
    
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    r = requests.get(f"https://api.paystack.co/transaction/verify/{ref}", headers=headers)
    res = r.json()
    
    if res['status'] and res['data']['status'] == 'success':
        booking.payment_status = 'paid'
        booking.status = 'confirmed'
        db.session.commit()
        return redirect(url_for('payment_success', booking_id=booking.id))
    else:
        return redirect(url_for('customer_dashboard'))

# 3. WEBHOOK - The REAL secure confirmation (add this URL in Paystack Dashboard)
@app.route('/paystack/webhook', methods=['POST'])
def paystack_webhook():
    # Paystack sends POST here even if user closes browser
    payload = request.get_json()
    if payload['event'] == 'charge.success':
        ref = payload['data']['reference']
        booking = Booking.query.filter_by(paystack_ref=ref).first()
        if booking:
            booking.payment_status = 'paid'
            booking.status = 'confirmed'
            db.session.commit()
            print(f"WEBHOOK: Booking {booking.id} confirmed paid")
    return jsonify({"status": "ok"}), 200

@app.route('/payment/success/<int:booking_id>')
def payment_success(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return render_template('payment_success.html', booking=booking)

@app.route('/payment/cancel/<int:booking_id>')
def payment_cancel(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return render_template('payment_cancel.html', booking=booking)


@app.route('/rate_worker/<int:booking_id>', methods=['GET','POST'])
def rate_worker(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    
    if request.method == 'POST':
        try:
            rating = int(request.form.get('rating', 0))
            review = request.form.get('review', '')
            
            booking.rating = rating
            booking.review = review
            
            # Update worker rating safely
            worker = User.query.get(booking.worker_id)
            if worker:
                # Get all rated bookings for this worker
                all_rated = Booking.query.filter_by(worker_id=worker.id).filter(Booking.rating != None).all()
                if all_rated:
                    total = sum(b.rating for b in all_rated)
                    count = len(all_rated)
                    # Only set if columns exist
                    if hasattr(worker, 'avg_rating'):
                        worker.avg_rating = total / count
                    if hasattr(worker, 'rating_count'):
                        worker.rating_count = count
            
            db.session.commit()
            return redirect(url_for('customer_dashboard'))
        except Exception as e:
            print(f"Rating error: {e}")
            db.session.rollback()
            return f"Error saving rating: {e}", 500

    return render_template('rate_worker.html', booking=booking)

                 

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

