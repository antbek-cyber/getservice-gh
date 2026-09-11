from extensions import db
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20), default="customer") # customer or admin

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    


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
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(500))
    is_approved = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default="pending")
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    bio = db.Column(db.Text, nullable=True)
    fcm_token = db.Column(db.String(300))

    def __repr__(self):
        return f'<Worker {self.name} - {self.skill}>'


    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    phone = db.Column(db.String(20), unique=True)
    password_hash = db.Column(db.String(500))
    profile_pic = db.Column(db.String(100))

    def __repr__(self):
        return f'<Customer {self.name}>'


    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


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
    rating = db.Column(db.Integer, nullable=True)
    review = db.Column(db.Text, nullable=True)
    payout_status = db.Column(db.String(20), default='unpaid') # unpaid, pending_payout, paid_out

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id')) 
    message = db.Column(db.String(500))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class WorkPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'))
    image_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    customer_name = db.Column(db.String(100))
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    worker = db.relationship('Worker', backref='reviews')

class WorkerPayout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('worker.id'), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), unique=True, nullable=False) # one payout per booking
    customer_paid = db.Column(db.Float, nullable=False) # what customer paid e.g. 200
    platform_fee = db.Column(db.Float, nullable=False) # your cut e.g. 20% = 40
    worker_earnings = db.Column(db.Float, nullable=False) # worker gets e.g. 160
    status = db.Column(db.String(20), default='pending') # pending, approved, paid, failed
    paystack_transfer_ref = db.Column(db.String(100)) # for Paystack transfer
    recipient_code = db.Column(db.String(100)) # worker's bank/momo code in Paystack 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime)
    worker = db.relationship('Worker', backref='payouts')
    booking = db.relationship('Booking', backref=db.backref('payout', uselist=False))





