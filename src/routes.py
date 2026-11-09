"""Application routes.

Notes for maintainers
---------------------
* Workers and admins authenticate with Flask-Login (ids are namespaced:
  "worker:<id>" / "user:<id>").  Customers authenticate with
  session["customer_id"].
* Every route that touches a booking/job verifies ownership in the query.
* Money is only ever credited by _settle_booking_payment(), which is
  idempotent and verifies amount + currency against Paystack.
"""
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import smtplib
import ssl
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from urllib.parse import quote, urlparse

import cloudinary.uploader
import requests
from flask import (abort, flash, g, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from flask import current_app as app
from flask_login import current_user, login_user, logout_user
from itsdangerous import BadSignature, URLSafeTimedSerializer
from PIL import Image
from pywebpush import WebPushException, webpush
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload

from extensions import db, login_manager
from models import (Booking, Customer, Job, Notification, Payment, PhoneOTP,
                    PushSubscription, Review, Service, User, WorkPhoto,
                    Worker, WorkerPayout, WorkerProfile)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:getserviceadmin1@gmail.com")

CURRENCY = "GHS"
COMMISSION_RATE = 0.0
DEFAULT_BOOKING_AMOUNT = 200.0
MIN_BOOKING_AMOUNT = 50.0
MAX_BOOKING_AMOUNT = 100000.0
VERIFY_FEE_GHS = 50

PER_PAGE = 24
MAX_GEO_CANDIDATES = 500
MAX_WORK_IMAGES = 20
MIN_PASSWORD_LENGTH = 8
MIN_ADMIN_PASSWORD_LENGTH = 10
MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60
RESET_TOKEN_MAX_AGE = 60 * 60   # password-reset links work for 1 hour

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG"}

PHONE_RE = re.compile(r"^\+?\d{9,15}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _apply_default_config():
    """Safe defaults; anything already configured explicitly is left alone.
    (Move these into your real config when convenient.)"""
    cfg = app.config
    if cfg.get("MAX_CONTENT_LENGTH") is None:
        cfg["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB request cap
    if cfg.get("SESSION_COOKIE_SAMESITE") is None:
        cfg["SESSION_COOKIE_SAMESITE"] = "Lax"
    if cfg.get("REMEMBER_COOKIE_SAMESITE") is None:
        cfg["REMEMBER_COOKIE_SAMESITE"] = "Lax"
    cfg["REMEMBER_COOKIE_HTTPONLY"] = True
    # Secure cookies need HTTPS. Set COOKIE_SECURE=0 to opt out (e.g. plain-HTTP staging).
    if not app.debug and not app.testing and os.environ.get("COOKIE_SECURE", "1") == "1":
        cfg["SESSION_COOKIE_SECURE"] = True
        cfg["REMEMBER_COOKIE_SECURE"] = True


_apply_default_config()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _clean(value, maxlen=255):
    return (value or "").strip()[:maxlen]


def _to_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _to_int(value, default=0, lo=None, hi=None):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if lo is not None:
        number = max(lo, number)
    if hi is not None:
        number = min(hi, number)
    return number


def _money(value):
    """Round to 2dp. Raises TypeError/ValueError on junk input."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("not a finite number")
    return round(number, 2)


def _pesewas(value):
    return int(round(float(value) * 100))


def _norm_phone(phone):
    return re.sub(r"[\s\-().]", "", phone or "")


def _phone_variants(phone):
    raw = (phone or "").strip()
    return list({raw, _norm_phone(raw)} - {""})


def _like_escape(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _split_images(csv_text):
    return [x.strip() for x in (csv_text or "").split(",") if x.strip()]


def _find_by_identifier(model, identifier):
    """Look a Customer/Worker up by email or phone using index-friendly comparisons."""
    if not identifier:
        return None
    return model.query.filter(or_(
        model.email == identifier,
        model.email == identifier.lower(),
        model.phone.in_(_phone_variants(identifier)),
    )).first()


def haversine(lat1, lon1, lat2, lon2):
    radius = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return radius * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Login throttling (in-memory, per process).  For multiple gunicorn workers use
# Flask-Limiter with a Redis backend instead.
# ---------------------------------------------------------------------------
_failed_logins = {}


def _throttle_key(scope, identifier):
    return f"{scope}:{request.remote_addr}:{(identifier or '').lower()[:120]}"


def _is_locked(key, limit=None):
    now = time.time()
    recent = [t for t in _failed_logins.get(key, []) if now - t < LOCKOUT_SECONDS]
    if recent:
        _failed_logins[key] = recent
    else:
        _failed_logins.pop(key, None)
    return len(recent) >= (limit or MAX_LOGIN_FAILURES)


def _record_failure(key):
    _failed_logins.setdefault(key, []).append(time.time())
    if len(_failed_logins) > 10000:  # keep memory bounded
        now = time.time()
        for k in [k for k, v in _failed_logins.items() if not v or now - v[-1] >= LOCKOUT_SECONDS]:
            _failed_logins.pop(k, None)


def _clear_failures(key):
    _failed_logins.pop(key, None)


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    kind, _, raw = (user_id or "").partition(":")
    model = {"user": User, "worker": Worker}.get(kind)
    if model is None or not raw.isdigit():
        return None  # also invalidates legacy un-namespaced ids
    return db.session.get(model, int(raw))


def _current_worker():
    if current_user.is_authenticated:
        user = current_user._get_current_object()
        if isinstance(user, Worker):
            return user
    return None


def _current_admin():
    if current_user.is_authenticated:
        user = current_user._get_current_object()
        if isinstance(user, User) and user.is_admin:
            return user
    return None


def _session_customer_id():
    raw = session.get("customer_id")
    return int(raw) if str(raw).isdigit() else None


def _load_customer():
    if "customer" not in g.__dict__:
        cid = _session_customer_id()
        g.customer = db.session.get(Customer, cid) if cid else None
        if cid and g.customer is None:
            session.pop("customer_id", None)
    return g.customer


def worker_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        worker = _current_worker()
        if worker is None:
            flash("Please log in as a worker.")
            return redirect(url_for("worker_login"))
        if _phone_enforced() and not worker.phone_verified:
            return _begin_verification("worker", worker, send=False)
        return f(*args, **kwargs)
    return wrapper


def customer_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        customer = _load_customer()
        if customer is None:
            flash("Please log in to continue.")
            return redirect(url_for("customer_login"))
        if _phone_enforced() and not customer.phone_verified:
            return _begin_verification("customer", customer, send=False)
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if _current_admin() is None:
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


def permission_required(perm):
    """Apply *after* @admin_required."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            admin = _current_admin()
            if admin and (admin.is_super_admin or (admin.admin_permissions or {}).get(perm)):
                return f(*args, **kwargs)
            flash("You don't have permission", "danger")
            return redirect(url_for("admin_dashboard"))
        return wrapper
    return decorator


def _upload_image(file_storage, folder):
    """Validate (extension + real image content) and upload to Cloudinary.
    Returns the secure URL, or None if no file was supplied. Raises ValueError
    with a user-friendly message for bad files."""
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        raise ValueError("Only PNG or JPG images are allowed.")
    try:
        image = Image.open(file_storage.stream)
        image_format = image.format
        image.verify()
    except Exception:
        raise ValueError("That file is not a valid image.")
    finally:
        file_storage.stream.seek(0)
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ValueError("Only PNG or JPG images are allowed.")
    result = cloudinary.uploader.upload(file_storage, folder=folder, resource_type="image")
    return result.get("secure_url")


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    if session.get("customer_id") or current_user.is_authenticated:
        workers = (Worker.query.filter_by(is_approved=True)
                   .order_by(func.coalesce(Worker.rating, 0).desc(), Worker.id.desc())
                   .limit(PER_PAGE * 3).all())
        return render_template("index.html", workers=workers)
    return render_template("landing.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/join_choice")
def join_choice():
    return render_template("join_choice.html")


@app.route("/login")
def login_redirect():
    return redirect(url_for("login_choice"))


@app.route("/login_choice")
def login_choice():
    return render_template("login_choice.html")


@app.route("/service-worker.js")
def service_worker():
    response = make_response(app.send_static_file("service-worker.js"))
    response.headers["Cache-Control"] = "no-cache"
    return response


# ---------------------------------------------------------------------------
# Registration & login
# ---------------------------------------------------------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    name = _clean(request.form.get("name"), 80)
    phone = _norm_phone(request.form.get("phone"))
    email = _clean(request.form.get("email"), 120).lower() or None   # optional, used for password reset
    job_type = _clean(request.form.get("job_type"), 80)
    location = _clean(request.form.get("location"), 120)
    experience = _to_int(request.form.get("years"), default=0, lo=0, hi=70)
    password = (request.form.get("password") or "").strip()
    confirm = (request.form.get("confirm_password") or "").strip()

    if not (name and phone and job_type and location):
        flash("Please fill in all required fields.")
        return redirect(url_for("signup"))
    if not PHONE_RE.match(phone):
        flash("Please enter a valid phone number.")
        return redirect(url_for("signup"))
    if email and not EMAIL_RE.match(email):
        flash("Please enter a valid email address.")
        return redirect(url_for("signup"))
    if email and Worker.query.filter_by(email=email).first():
        flash("That email is already registered. Try logging in or resetting your password.")
        return redirect(url_for("signup"))
    if len(password) < MIN_PASSWORD_LENGTH:
        flash(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        return redirect(url_for("signup"))
    if password != confirm:
        flash("Passwords do not match!")
        return redirect(url_for("signup"))
    if Worker.query.filter(Worker.phone.in_(_phone_variants(phone))).first():
        flash("Phone number already exists! Use different number")
        return redirect(url_for("signup"))

    try:
        photo_url = _upload_image(request.files.get("profile_pic"), "getservice_gh/profile/")
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("signup"))
    except Exception:
        logger.exception("Signup photo upload failed")
        flash("We couldn't upload your photo. Please try again.")
        return redirect(url_for("signup"))

    worker = Worker(name=name, phone=phone, profession=job_type, location=location,
                    experience=experience, photo=photo_url, email=email,
                    status="pending", is_approved=False)
    worker.set_password(password)
    try:
        db.session.add(worker)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("That phone number or email is already registered.")
        return redirect(url_for("signup"))
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Signup failed")
        flash("Something went wrong. Please try again.")
        return redirect(url_for("signup"))

    if _phone_enforced():
        return _begin_verification("worker", worker)
    flash("Account created! Waiting for admin approval.")
    return redirect(url_for("index"))


@app.route("/customer_register", methods=["GET", "POST"])
def customer_register():
    if request.method == "GET":
        return render_template("customer_register.html")

    name = _clean(request.form.get("name"), 100)
    email = _clean(request.form.get("email"), 100).lower()
    phone = _norm_phone(request.form.get("phone")) or None   # NULL, never '' (unique column)
    password = (request.form.get("password") or "").strip()

    if not name or not email or not password:
        flash("Fill all fields")
        return redirect(url_for("customer_register"))
    if not EMAIL_RE.match(email):
        flash("Please enter a valid email address.")
        return redirect(url_for("customer_register"))
    if phone and not PHONE_RE.match(phone):
        flash("Please enter a valid phone number.")
        return redirect(url_for("customer_register"))
    if len(password) < MIN_PASSWORD_LENGTH:
        flash(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        return redirect(url_for("customer_register"))
    confirm = request.form.get("confirm_password")
    if confirm is not None and confirm.strip() != password:
        flash("Passwords do not match!")
        return redirect(url_for("customer_register"))

    conditions = [Customer.email == email]
    if phone:
        conditions.append(Customer.phone.in_(_phone_variants(phone)))
    if Customer.query.filter(or_(*conditions)).first():
        flash("Already registered, please login")
        return redirect(url_for("customer_login"))

    if _phone_enforced() and not phone:
        flash("A phone number is required so we can verify it by SMS.")
        return redirect(url_for("customer_register"))

    customer = Customer(name=name, email=email, phone=phone)
    customer.set_password(password)
    try:
        db.session.add(customer)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Already registered, please login")
        return redirect(url_for("customer_login"))
    if _phone_enforced():
        return _begin_verification("customer", customer)
    flash("Registration successful! Please login.")
    return redirect(url_for("customer_login"))


@app.route("/customer_login", methods=["GET", "POST"])
def customer_login():
    if request.method == "POST":
        identifier = _clean(request.form.get("phone") or request.form.get("email")
                            or request.form.get("identifier") or request.form.get("username"), 120)
        password = (request.form.get("password") or "").strip()
        key = _throttle_key("customer", identifier)
        if _is_locked(key):
            flash("Too many failed attempts. Try again in 15 minutes.")
            return render_template("customer_login.html"), 429

        customer = _find_by_identifier(Customer, identifier)
        if customer and customer.check_password(password):
            _clear_failures(key)
            if _phone_enforced() and not customer.phone_verified:
                return _begin_verification("customer", customer)
            logout_user()
            session.clear()
            session.permanent = True
            session["customer_id"] = customer.id
            response = make_response(redirect(url_for("index")))
            response.delete_cookie("remember_token")  # don't stay logged in as a worker too
            return response

        _record_failure(key)
        flash("Invalid email/phone or password.")
    return render_template("customer_login.html")


@app.route("/worker_login", methods=["GET", "POST"])
def worker_login():
    if request.method == "POST":
        identifier = _clean(request.form.get("email") or request.form.get("identifier")
                            or request.form.get("phone"), 120)
        password = (request.form.get("password") or "").strip()
        if not identifier or not password:
            flash("Please fill all fields")
            return redirect(url_for("worker_login"))

        key = _throttle_key("worker", identifier)
        if _is_locked(key):
            flash("Too many failed attempts. Try again in 15 minutes.")
            return render_template("worker_login.html"), 429

        worker = _find_by_identifier(Worker, identifier)
        if worker and worker.check_password(password):
            _clear_failures(key)
            if _phone_enforced() and not worker.phone_verified:
                return _begin_verification("worker", worker)
            session.clear()
            login_user(worker, remember=True)
            session.permanent = True
            flash("Login successful!")
            return redirect(url_for("index"))

        _record_failure(key)
        flash("Invalid email/phone or password")
        return redirect(url_for("worker_login"))
    return render_template("worker_login.html")


def _logout_response():
    logout_user()
    session.clear()
    response = make_response(redirect(url_for("index")))
    response.delete_cookie("remember_token")
    return response


@app.route("/worker_logout")
def worker_logout():
    return _logout_response()


@app.route("/customer_logout")
def customer_logout():
    return _logout_response()


@app.route("/logout")
def logout_all():
    return _logout_response()


# ---------------------------------------------------------------------------
# Search (one query, ratings aggregated in SQL, paginated)
# ---------------------------------------------------------------------------
@app.route("/search")
def search():
    q = _clean(request.args.get("q"), 100)
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    if lat is not None and not (math.isfinite(lat) and -90 <= lat <= 90):
        lat = None
    if lng is not None and not (math.isfinite(lng) and -180 <= lng <= 180):
        lng = None
    has_geo = lat is not None and lng is not None

    rating_sq = (db.session.query(Review.worker_id.label("wid"),
                                  func.avg(Review.rating).label("avg_rating"),
                                  func.count(Review.id).label("cnt"))
                 .group_by(Review.worker_id).subquery())
    avg_col = func.coalesce(rating_sq.c.avg_rating, 0)
    cnt_col = func.coalesce(rating_sq.c.cnt, 0)

    query = (db.session.query(Worker, avg_col, cnt_col)
             .outerjoin(rating_sq, rating_sq.c.wid == Worker.id)
             .filter(Worker.is_approved.is_(True)))
    if q:
        pattern = f"%{_like_escape(q)}%"
        query = query.filter(or_(
            Worker.name.ilike(pattern, escape="\\"),
            Worker.profession.ilike(pattern, escape="\\"),
            Worker.location.ilike(pattern, escape="\\"),
        ))
    query = query.order_by(avg_col.desc(), Worker.id)

    def decorate(rows):
        workers = []
        for worker, avg, cnt in rows:
            worker.avg_rating = round(float(avg or 0), 1)
            worker.review_count = int(cnt or 0)
            worker.distance = 9999
            if has_geo and worker.latitude is not None and worker.longitude is not None:
                worker.distance = haversine(lat, lng, float(worker.latitude), float(worker.longitude))
            workers.append(worker)
        return workers

    try:
        if has_geo:
            # Distance sorting needs coordinates; cap how many candidates we pull.
            workers = decorate(query.limit(MAX_GEO_CANDIDATES).all())
            workers.sort(key=lambda w: w.distance)
            start = (page - 1) * PER_PAGE
            has_next = len(workers) > start + PER_PAGE
            workers = workers[start:start + PER_PAGE]
        else:
            rows = query.offset((page - 1) * PER_PAGE).limit(PER_PAGE + 1).all()
            has_next = len(rows) > PER_PAGE
            workers = decorate(rows[:PER_PAGE])
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Search failed")
        workers, has_next = [], False

    return render_template("results.html", workers=workers, query=q,
                           page=page, has_next=has_next, has_prev=page > 1)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = _clean(request.form.get("email"), 120).lower()
        password = request.form.get("password") or ""
        key = _throttle_key("admin", email)
        if _is_locked(key):
            flash("Too many failed attempts. Try again in 15 minutes.")
            return render_template("admin_login.html"), 429

        user = User.query.filter(func.lower(User.email) == email).first()
        if user and user.is_admin and user.check_password(password):
            _clear_failures(key)
            session.clear()
            login_user(user)
            return redirect(url_for("admin_dashboard"))

        _record_failure(key)
        flash("Invalid credentials.")
    return render_template("admin_login.html")


@app.route("/admin")
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    # Capped for now; add real pagination when the admin templates are redone.
    workers = Worker.query.order_by(Worker.id.desc()).limit(500).all()
    customers = Customer.query.order_by(Customer.id.desc()).limit(500).all()
    admins = User.query.filter_by(is_admin=True).all()
    pending = Worker.query.filter_by(is_approved=False).order_by(Worker.id.desc()).all()
    return render_template("admin_dashboard.html", workers=workers, customers=customers,
                           admins=admins, pending=pending,
                           total_workers=Worker.query.count(),
                           total_customers=Customer.query.count())


def _back_to_admin():
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/approve-worker/<int:id>", methods=["POST"])
@admin_required
def approve_worker(id):
    worker = db.session.get(Worker, id)
    if worker:
        worker.is_approved = True
        worker.status = "approved"
        db.session.commit()
    return _back_to_admin()


@app.route("/admin/unapprove-worker/<int:id>", methods=["POST"])
@admin_required
def unapprove_worker(id):
    worker = db.session.get(Worker, id)
    if worker:
        worker.is_approved = False
        worker.status = "pending"
        db.session.commit()
    return _back_to_admin()


@app.route("/admin/delete-worker/<int:id>", methods=["POST"])
@admin_required
def delete_worker(id):
    worker = db.session.get(Worker, id)
    if not worker:
        return _back_to_admin()
    try:
        Notification.query.filter_by(worker_id=id).delete(synchronize_session=False)
        PushSubscription.query.filter_by(user_id=id).delete(synchronize_session=False)
        WorkPhoto.query.filter_by(worker_id=id).delete(synchronize_session=False)
        WorkerProfile.query.filter_by(user_id=id).delete(synchronize_session=False)
        db.session.delete(worker)
        db.session.commit()
        flash("Worker deleted.")
    except IntegrityError:
        db.session.rollback()
        flash("This worker has bookings, reviews or payouts and can't be deleted. Unapprove them instead.")
    return _back_to_admin()


@app.route("/admin/approve-all-workers", methods=["POST"])
@admin_required
def approve_all_workers():
    try:
        count = (Worker.query.filter_by(is_approved=False)
                 .update({"is_approved": True, "status": "approved"}, synchronize_session=False))
        db.session.commit()
        flash(f"Approved {count} workers!")
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Approve-all failed")
        flash("Something went wrong approving workers.")
    return _back_to_admin()


@app.route("/admin/create-admin", methods=["POST"])
@admin_required
def create_admin():
    if not current_user.is_super_admin:
        flash("Only a super admin can create admins.", "danger")
        return _back_to_admin()

    email = _clean(request.form.get("email"), 120).lower()
    username = _clean(request.form.get("username"), 80)
    password = request.form.get("password") or ""
    role = request.form.get("role", "admin")

    if role not in ("admin", "super_admin"):
        role = "admin"
    if not EMAIL_RE.match(email) or not username:
        flash("A valid email and username are required.")
        return _back_to_admin()
    if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
        flash(f"Admin passwords must be at least {MIN_ADMIN_PASSWORD_LENGTH} characters.")
        return _back_to_admin()
    if User.query.filter(func.lower(User.email) == email).first():
        flash("Email already exists as admin")
        return _back_to_admin()

    admin = User(username=username, email=email, role=role, is_admin=True,
                 is_super_admin=(role == "super_admin"), admin_permissions={})
    admin.set_password(password)
    try:
        db.session.add(admin)
        db.session.commit()
        flash("Admin created.")
    except IntegrityError:
        db.session.rollback()
        flash("That username or email is already taken.")
    return _back_to_admin()


@app.route("/add", methods=["POST"])
@admin_required
def add_service():
    name = _clean(request.form.get("name"), 80)
    category = _clean(request.form.get("category"), 80)
    location = _clean(request.form.get("location"), 120)
    if not name:
        flash("Service name is required.")
        return redirect(url_for("index"))
    db.session.add(Service(name=name, category=category, location=location))
    db.session.commit()
    flash("Service added successfully!")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Jobs board
# ---------------------------------------------------------------------------
@app.route("/post-job", methods=["GET", "POST"])
@app.route("/post_job", methods=["GET", "POST"])
def post_job():
    if request.method == "GET":
        return render_template("post_job.html")

    customer = _load_customer()
    if customer is None:
        flash("Please log in to post a job.")
        return redirect(url_for("customer_login"))

    title = _clean(request.form.get("title"), 200)
    description = _clean(request.form.get("description"), 5000)
    if not description:
        flash("Please describe the job.")
        return redirect(url_for("post_job"))

    job = Job(customer_id=customer.id, customer_name=customer.name, phone=customer.phone,
              title=title, location=_clean(request.form.get("location"), 120),
              job_type=_clean(request.form.get("category"), 80),
              description=description, budget=_clean(request.form.get("budget"), 50),
              status="open")
    try:
        db.session.add(job)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Posting job failed")
        flash("We couldn't post your job. Please try again.")
        return redirect(url_for("post_job"))
    return redirect(url_for("view_jobs"))


@app.route("/jobs")
def view_jobs():
    jobs = Job.query.order_by(Job.id.desc()).limit(200).all()
    return render_template("jobs.html", jobs=jobs)


@app.route("/delete-job/<int:job_id>", methods=["POST"])
def delete_job(job_id):
    job = Job.query.filter_by(id=job_id).first_or_404()
    customer = _load_customer()
    is_owner = customer is not None and job.customer_id == customer.id
    if not (is_owner or _current_admin()):
        abort(404)
    db.session.delete(job)
    db.session.commit()
    flash("Job deleted!", "success")
    return redirect(url_for("view_jobs"))


# ---------------------------------------------------------------------------
# Dashboards
# ---------------------------------------------------------------------------
@app.route("/customer/dashboard")
@customer_required
def customer_dashboard():
    customer = g.customer
    bookings = (Booking.query.options(joinedload(Booking.worker))
                .filter_by(customer_id=customer.id)
                .order_by(Booking.id.desc()).limit(200).all())
    return render_template("customer_dashboard.html", customer=customer, bookings=bookings)


@app.route("/worker_dashboard")
@worker_required
def worker_dashboard():
    worker = _current_worker()

    bookings = (Booking.query.filter_by(worker_id=worker.id)
                .order_by(Booking.created_at.desc()).limit(200).all())
    new_bookings_count = Booking.query.filter_by(worker_id=worker.id, status="pending").count()

    notifications = (Notification.query.filter_by(worker_id=worker.id)
                     .order_by(Notification.created_at.desc()).limit(10).all())
    unread_count = Notification.query.filter_by(worker_id=worker.id, is_read=False).count()

    reviews = (Review.query.filter_by(worker_id=worker.id)
               .order_by(Review.created_at.desc()).limit(50).all())
    avg, review_count = (db.session.query(func.avg(Review.rating), func.count(Review.id))
                         .filter(Review.worker_id == worker.id).one())
    avg_rating = round(float(avg), 1) if avg else 0

    total_earnings = float(db.session.query(func.coalesce(func.sum(WorkerPayout.worker_earnings), 0))
                           .filter(WorkerPayout.worker_id == worker.id).scalar() or 0)
    paid_bookings = (WorkerPayout.query.filter_by(worker_id=worker.id)
                     .order_by(WorkerPayout.created_at.desc()).limit(50).all())

    return render_template(
        "worker_dashboard.html",
        worker=worker, bookings=bookings, notifications=notifications,
        unread_count=unread_count, new_bookings_count=new_bookings_count,
        work_images=_split_images(worker.work_images),
        reviews=reviews, avg_rating=avg_rating, review_count=review_count,
        total_earnings=total_earnings, worker_share=total_earnings,
        paid_bookings=paid_bookings, VAPID_PUBLIC_KEY=VAPID_PUBLIC_KEY)


@app.route("/my-jobs")
@worker_required
def my_jobs():
    worker = _current_worker()
    bookings = (Booking.query.filter_by(worker_id=worker.id)
                .order_by(Booking.created_at.desc()).limit(200).all())
    return render_template("worker_bookings.html", worker=worker, bookings=bookings)


@app.route("/my-jobs", methods=["POST"])
def my_jobs_check():
    # Legacy phone-number lookup removed: it exposed customers' details to anyone.
    return redirect(url_for("my_jobs"))


@app.route("/worker/<int:worker_id>")
def view_worker_profile(worker_id):
    worker = Worker.query.filter_by(id=worker_id).first_or_404()
    if not worker.is_approved:
        me = _current_worker()
        if not (_current_admin() or (me and me.id == worker.id)):
            abort(404)
    return render_template("worker_profile.html", worker=worker)


@app.route("/worker/profile", methods=["GET", "POST"])
@worker_required
def edit_worker_profile():
    # Profile editing lives in worker_update; this stub used to crash (undefined model).
    return redirect(url_for("worker_dashboard"))


# ---------------------------------------------------------------------------
# Push notifications (subscriptions are keyed by Worker.id)
# ---------------------------------------------------------------------------
@app.route("/api/save-subscription", methods=["POST"])
@worker_required
def save_subscription():
    worker = _current_worker()
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    keys = data.get("keys") or {}
    if not (isinstance(endpoint, str) and endpoint.startswith("https://")
            and keys.get("p256dh") and keys.get("auth")):
        return jsonify({"error": "invalid subscription"}), 400
    try:
        sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
        if sub:
            sub.user_id = worker.id
            sub.p256dh = keys["p256dh"]
            sub.auth = keys["auth"]
        else:
            db.session.add(PushSubscription(user_id=worker.id, endpoint=endpoint,
                                            p256dh=keys["p256dh"], auth=keys["auth"]))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Saving push subscription failed")
        return jsonify({"error": "could not save subscription"}), 500
    return jsonify({"ok": True}), 200


def send_push_to_worker(worker_id, title, body):
    """Best-effort push. Never raises. (Move to a background queue when traffic grows.)"""
    if not VAPID_PRIVATE_KEY:
        return
    subs = PushSubscription.query.filter_by(user_id=worker_id).all()
    for sub in subs:
        try:
            parsed = urlparse(sub.endpoint)
            webpush(
                subscription_info={"endpoint": sub.endpoint,
                                   "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=json.dumps({"title": title, "body": body}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT, "aud": f"{parsed.scheme}://{parsed.netloc}"},
                ttl=3600, timeout=5,
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning("Push failed for worker %s (status %s)", worker_id, status)
            if status in (404, 410):  # subscription is gone for good
                db.session.delete(sub)
                db.session.commit()
        except Exception:
            logger.exception("Unexpected push error for worker %s", worker_id)


# ---------------------------------------------------------------------------
# In-app notifications
# ---------------------------------------------------------------------------
def _notification_filter():
    """(column, id) identifying whose notifications the current visitor may see."""
    worker = _current_worker()
    if worker:
        return Notification.worker_id, worker.id
    cid = _session_customer_id()
    if cid:
        return Notification.customer_id, cid
    return None, None


@app.route("/api/mark-notification-read", methods=["POST"])
@app.route("/api/mark-notifications-read", methods=["POST"])
def mark_read_api():
    column, owner_id = _notification_filter()
    if column is None:
        return jsonify({"ok": False}), 401
    try:
        (Notification.query.filter(column == owner_id, Notification.is_read.is_(False))
         .update({"is_read": True}, synchronize_session=False))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Marking notifications read failed")
        return jsonify({"ok": False}), 500
    return jsonify({"ok": True})


@app.route("/api/check-notifications")
def check_notifications():
    column, owner_id = _notification_filter()
    if column is None:
        return jsonify({"has_new": False})
    unread = Notification.query.filter(column == owner_id, Notification.is_read.is_(False))
    count = unread.count()
    if not count:  # the common case on every poll: a single cheap query
        return jsonify({"has_new": False})
    latest = unread.order_by(Notification.created_at.desc()).first()
    return jsonify({"has_new": True, "count": count, "message": latest.message})


# ---------------------------------------------------------------------------
# Worker profile management
# ---------------------------------------------------------------------------
@app.route("/worker/update", methods=["POST"])
@worker_required
def worker_update():
    worker = _current_worker()
    try:
        new_email = _clean(request.form.get("email"), 120).lower()
        if new_email:   # blank = leave unchanged, so a worker can't lock themselves out by accident
            if not EMAIL_RE.match(new_email):
                flash("Please enter a valid email address.")
                return redirect(url_for("worker_dashboard"))
            if Worker.query.filter(Worker.email == new_email, Worker.id != worker.id).first():
                flash("That email is already used by another account.")
                return redirect(url_for("worker_dashboard"))
            worker.email = new_email

        job_type = _clean(request.form.get("job_type"), 80)
        if job_type:
            worker.profession = job_type

        location = _clean(request.form.get("location"), 120)
        if location:
            worker.location = location

        raw_price = request.form.get("price")
        if raw_price:
            price = _to_float(re.sub(r"[^\d.]", "", raw_price))
            if price is not None and 0 <= price <= MAX_BOOKING_AMOUNT:
                worker.price = round(price, 2)

        bio = _clean(request.form.get("bio"), 2000)
        if bio:
            worker.bio = bio

        lat = _to_float(request.form.get("latitude"))
        lng = _to_float(request.form.get("longitude"))
        if lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180:
            worker.latitude, worker.longitude = lat, lng

        new_photo = _upload_image(request.files.get("profile_pic"), "getservice_gh/profile/")
        if new_photo:
            worker.photo = new_photo

        work_files = request.files.getlist("work_photos") or request.files.getlist("work_files")
        images = _split_images(worker.work_images)
        for wf in work_files:
            if not (wf and wf.filename):
                continue
            if len(images) >= MAX_WORK_IMAGES:
                flash(f"You can keep up to {MAX_WORK_IMAGES} work photos.")
                break
            try:
                url = _upload_image(wf, "getservice_gh/work/")
            except ValueError as exc:
                flash(f"{wf.filename}: {exc}")
                continue
            if url:
                images.append(url)
        worker.work_images = ",".join(images)

        db.session.commit()
        flash("Profile updated!", "success")
    except ValueError as exc:  # bad profile picture
        db.session.rollback()
        flash(str(exc))
    except Exception:
        db.session.rollback()
        logger.exception("Worker profile update failed")
        flash("We couldn't update your profile. Please try again.")
    return redirect(url_for("worker_dashboard"))


@app.route("/delete_work_image", methods=["POST"])
@worker_required
def delete_work_image():
    worker = _current_worker()
    target = _clean(request.form.get("image_to_delete"), 500)
    images = _split_images(worker.work_images)
    if target and target in images:
        images.remove(target)
        worker.work_images = ",".join(images)
        db.session.commit()
    return redirect(url_for("worker_dashboard"))


# ---------------------------------------------------------------------------
# Booking helpers
# ---------------------------------------------------------------------------
def _booking_party(booking):
    """'worker' / 'customer' / None: how the current visitor relates to this booking."""
    worker = _current_worker()
    if worker and worker.id == booking.worker_id:
        return "worker"
    cid = _session_customer_id()
    if cid and booking.customer_id == cid:
        return "customer"
    return None


def _get_booking_for_party(booking_id, lock=False):
    """Fetch a booking only if the current visitor is its worker or its customer.
    Returns (booking, party). 404s otherwise, so existence isn't leaked."""
    query = Booking.query.filter_by(id=booking_id)
    if lock:
        query = query.with_for_update()
    booking = query.first_or_404()
    party = _booking_party(booking)
    if party is None:
        abort(404)
    return booking, party


def _get_worker_booking(booking_id):
    worker = _current_worker()
    return (Booking.query.filter_by(id=booking_id, worker_id=worker.id)
            .with_for_update().first_or_404())


def _get_customer_booking(booking_id, lock=False):
    query = Booking.query.filter_by(id=booking_id, customer_id=g.customer.id)
    if lock:
        query = query.with_for_update()
    return query.first_or_404()


def _notify(booking, to_party, message):
    """Queue an in-app notification (caller commits)."""
    if to_party == "worker":
        note = Notification(worker_id=booking.worker_id, booking_id=booking.id,
                            message=message[:500], is_read=False)
    elif booking.customer_id:
        note = Notification(customer_id=booking.customer_id, booking_id=booking.id,
                            message=message[:500], is_read=False)
    else:
        return
    db.session.add(note)


def _dashboard_for(party):
    return redirect(url_for("worker_dashboard" if party == "worker" else "customer_dashboard"))


def _refresh_payment_status(booking):
    paid = booking.paid_amount or 0
    total = booking.total_amount or 0
    if paid > 0 and paid + 0.005 >= total:
        booking.payment_status = "paid"
    elif paid > 0:
        booking.payment_status = "partially_paid"
    else:
        booking.payment_status = "pending"


# ---------------------------------------------------------------------------
# Creating a booking
# ---------------------------------------------------------------------------
@app.route("/book/<int:worker_id>", methods=["GET", "POST"])
@customer_required
def book_worker(worker_id):
    worker = Worker.query.filter_by(id=worker_id).first_or_404()
    if not worker.is_approved:
        abort(404)
    if request.method == "GET":
        # Creating a booking must be an explicit POST, never a link click.
        return redirect(url_for("view_worker_profile", worker_id=worker_id))

    customer = g.customer
    # Price comes from the worker's listed rate, never from the browser.
    price = worker.price or DEFAULT_BOOKING_AMOUNT
    total_amount = round(min(max(float(price), MIN_BOOKING_AMOUNT), MAX_BOOKING_AMOUNT), 2)
    fee = round(total_amount * COMMISSION_RATE, 2)

    booking = Booking(
        worker_id=worker.id,
        customer_id=customer.id,
        customer_name=customer.name,
        customer_phone=customer.phone,
        customer_email=customer.email,
        customer_location=_clean(request.form.get("location"), 200) or "Kumasi",
        service_needed=worker.profession or "General Service",
        job_date=_clean(request.form.get("date") or request.form.get("job_date"), 50) or None,
        details=_clean(request.form.get("details"), 2000) or f"Booking for {worker.name}",
        status="pending", payment_status="pending",
        total_amount=total_amount, commission_amount=fee,
        worker_payout=round(total_amount - fee, 2), paid_amount=0.0,
        proposed_amount=None, proposed_by=None, proposed_status="none",
    )
    try:
        db.session.add(booking)
        db.session.flush()  # get booking.id
        _notify(booking, "worker", f"New booking! GHS {total_amount:.2f} from {customer.name}")
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Booking creation failed")
        flash("We couldn't create your booking. Please try again.", "danger")
        return redirect(url_for("view_worker_profile", worker_id=worker_id))

    send_push_to_worker(worker.id, "New Booking! 🔔",
                        f"GHS {total_amount:.2f} from {customer.name} - Check dashboard!")
    flash(f"Booked {worker.name}!", "success")
    return redirect(url_for("customer_dashboard"))


# ---------------------------------------------------------------------------
# Price negotiation (either party may propose; only the OTHER party may answer)
# ---------------------------------------------------------------------------
@app.route("/booking/<int:id>/request_new_amount", methods=["POST"])
def request_new_amount(id):
    booking, party = _get_booking_for_party(id, lock=True)
    if booking.status not in ("pending", "accepted"):
        flash("This booking can no longer be renegotiated.")
        return _dashboard_for(party)
    try:
        new_amount = _money(request.form.get("new_amount"))
    except (TypeError, ValueError):
        flash("Please enter a valid amount.")
        return _dashboard_for(party)
    if not (MIN_BOOKING_AMOUNT <= new_amount <= MAX_BOOKING_AMOUNT) or new_amount < (booking.paid_amount or 0):
        flash(f"Amount must be between GHS {MIN_BOOKING_AMOUNT:.0f} and GHS {MAX_BOOKING_AMOUNT:.0f}, "
              "and not below what is already paid.")
        return _dashboard_for(party)

    booking.proposed_amount = new_amount
    booking.proposed_by = party
    booking.proposed_status = "pending"
    other = "worker" if party == "customer" else "customer"
    _notify(booking, other, f"{party.title()} proposed new price: GHS {new_amount:.2f} "
                            f"(was GHS {booking.total_amount:.2f})")
    db.session.commit()
    flash(f"New amount GHS {new_amount:.2f} proposed - other party notified")
    return _dashboard_for(party)


@app.route("/booking/<int:id>/accept_proposal", methods=["POST"])
def accept_proposal(id):
    booking, party = _get_booking_for_party(id, lock=True)
    if (booking.proposed_status != "pending" or booking.proposed_amount is None
            or booking.proposed_by == party):
        flash("There is no pending proposal from the other party to accept.")
        return _dashboard_for(party)

    new_total = _money(booking.proposed_amount)
    paid = _money(booking.paid_amount or 0)
    if new_total < paid:
        flash("This proposal is below the amount already paid. Please decline it.")
        return _dashboard_for(party)

    proposer = booking.proposed_by
    balance = _money(new_total - paid)
    fee = round(new_total * COMMISSION_RATE, 2)
    booking.total_amount = new_total
    booking.commission_amount = fee
    booking.worker_payout = round(new_total - fee, 2)
    _refresh_payment_status(booking)

    if balance > 0:
        booking.proposed_status = "accepted"   # cleared once the balance is paid
    else:
        booking.proposed_status = "none"
        booking.proposed_amount = None
        booking.proposed_by = None

    # Always tell the PROPOSER (the original code notified the acceptor by mistake).
    message = f"Your proposal of GHS {new_total:.2f} was ACCEPTED"
    if proposer == "customer" and balance > 0:
        message += f" - please pay the balance of GHS {balance:.2f}"
    _notify(booking, proposer, message)
    db.session.commit()

    if balance > 0 and party == "customer":
        flash(f"Accepted! New total GHS {new_total:.2f}. Please pay balance GHS {balance:.2f}")
        return redirect(url_for("pay_booking", booking_id=booking.id))
    flash(f"Accepted! New total GHS {new_total:.2f}")
    return _dashboard_for(party)


@app.route("/booking/<int:id>/decline_proposal", methods=["POST"])
def decline_proposal(id):
    booking, party = _get_booking_for_party(id, lock=True)
    if booking.proposed_status != "pending" or booking.proposed_by == party:
        flash("There is no pending proposal from the other party to decline.")
        return _dashboard_for(party)
    proposer = booking.proposed_by
    booking.proposed_status = "declined"
    _notify(booking, proposer, "Your price proposal was declined")
    db.session.commit()
    flash("Proposal declined")
    return _dashboard_for(party)


# ---------------------------------------------------------------------------
# Worker actions on bookings
# ---------------------------------------------------------------------------
@app.route("/booking/<int:booking_id>/accept", methods=["POST"])
@worker_required
def accept_booking(booking_id):
    booking = _get_worker_booking(booking_id)
    if booking.status != "pending":
        flash("This booking is no longer pending.", "info")
        return redirect(url_for("worker_dashboard"))
    booking.status = "accepted"
    _notify(booking, "customer", f"Accepted! Pay GHS {booking.total_amount:.2f} now")
    db.session.commit()
    flash("Booking accepted!", "success")
    return redirect(url_for("worker_dashboard"))


@app.route("/booking/<int:booking_id>/decline", methods=["POST"])
@worker_required
def decline_booking(booking_id):
    booking = _get_worker_booking(booking_id)
    if booking.status not in ("pending", "accepted") or (booking.paid_amount or 0) > 0:
        flash("This booking can't be declined (it is closed or already paid).", "info")
        return redirect(url_for("worker_dashboard"))
    booking.status = "declined"
    _notify(booking, "customer", "Your booking was declined by the worker")
    db.session.commit()
    flash("Booking declined", "info")
    return redirect(url_for("worker_dashboard"))


@app.route("/booking/<int:booking_id>/complete", methods=["POST"])
@worker_required
def complete_booking(booking_id):
    booking = _get_worker_booking(booking_id)
    if booking.status != "accepted":
        flash("Only accepted bookings can be completed.", "info")
        return redirect(url_for("worker_dashboard"))
    booking.status = "completed"
    _notify(booking, "customer", "Your job was marked complete. Please rate the worker!")
    db.session.commit()
    flash(f"Booking #{booking.id} completed! Great job!", "success")
    return redirect(url_for("worker_dashboard"))


# ---------------------------------------------------------------------------
# Customer actions on bookings
# ---------------------------------------------------------------------------
@app.route("/booking/<int:booking_id>/delete", methods=["POST"])
@customer_required
def delete_booking(booking_id):
    booking = _get_customer_booking(booking_id, lock=True)
    if (booking.paid_amount or 0) > 0:
        flash("Paid bookings can't be deleted.", "danger")
        return redirect(url_for("customer_dashboard"))
    db.session.delete(booking)  # payout/payments/notifications cascade
    db.session.commit()
    return redirect(url_for("customer_dashboard"))


@app.route("/bookings/clear_accepted", methods=["POST"])
def clear_accepted():
    worker = _current_worker()
    cid = _session_customer_id()
    if not worker and not cid:
        return redirect(url_for("login_choice"))
    try:
        if worker:
            jobs = Booking.query.filter_by(worker_id=worker.id, status="accepted").all()
        else:
            jobs = Booking.query.filter_by(customer_id=cid, status="pending").all()
        for job in jobs:
            if job.payment_status == "paid":
                if worker:
                    job.status = "completed"   # keep paid jobs for earnings history
                continue
            if (job.paid_amount or 0) > 0:
                continue                       # never delete a booking with money on it
            db.session.delete(job)
        db.session.flush()
        if worker:
            Notification.query.filter_by(worker_id=worker.id).delete(synchronize_session=False)
        else:
            Notification.query.filter_by(customer_id=cid).delete(synchronize_session=False)
        db.session.commit()
        flash("Old pending bookings cleared", "info")
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("clear_accepted failed")
        flash("Something went wrong clearing bookings.", "danger")
    return _dashboard_for("worker" if worker else "customer")


# ---------------------------------------------------------------------------
# Paystack helpers
# ---------------------------------------------------------------------------
def _paystack_secret():
    return os.environ.get("PAYSTACK_SECRET_KEY") or app.config.get("PAYSTACK_SECRET_KEY")


def _paystack_verify(reference):
    """Ask Paystack for the real state of a transaction. Returns its `data` dict or None."""
    secret = _paystack_secret()
    if not secret or not reference:
        return None
    try:
        response = requests.get(
            f"https://api.paystack.co/transaction/verify/{quote(reference, safe='')}",
            headers={"Authorization": f"Bearer {secret}"}, timeout=15)
        body = response.json()
    except (requests.RequestException, ValueError):
        logger.exception("Paystack verify request failed")
        return None
    if response.status_code == 200 and body.get("status"):
        return body.get("data") or {}
    return None


def _paystack_initialize(payload):
    """Returns (authorization_url, error_message)."""
    secret = _paystack_secret()
    if not secret:
        return None, "Payments are not configured yet."
    try:
        response = requests.post("https://api.paystack.co/transaction/initialize",
                                 headers={"Authorization": f"Bearer {secret}"},
                                 json=payload, timeout=15)
        body = response.json()
    except (requests.RequestException, ValueError):
        logger.exception("Paystack initialize request failed")
        return None, "Could not reach the payment provider. Please try again."
    url = (body.get("data") or {}).get("authorization_url")
    if body.get("status") and url:
        return url, None
    return None, body.get("message") or "Payment could not be started."


def _sync_payout(booking):
    """Create/update the worker payout row from what has actually been paid."""
    paid = _money(booking.paid_amount or 0)
    fee = _money(paid * COMMISSION_RATE)
    earnings = _money(paid - fee)
    payout = booking.payout
    if payout is None:
        db.session.add(WorkerPayout(worker_id=booking.worker_id, booking_id=booking.id,
                                    customer_paid=paid, platform_fee=fee,
                                    worker_earnings=earnings, status="pending"))
    else:
        payout.customer_paid = paid
        payout.platform_fee = fee
        payout.worker_earnings = earnings
    booking.commission_amount = fee
    booking.worker_payout = earnings


def _settle_booking_payment(reference, tx):
    """Credit a booking for a successful Paystack charge. Idempotent.

    `tx` is Paystack transaction data (from the verify API or a signed webhook).
    Returns (outcome, payment) where outcome is one of:
    'success', 'already', 'failed', 'mismatch', 'unknown'.
    """
    payment = Payment.query.filter_by(reference=reference).with_for_update().first()
    if payment is None:
        logger.warning("Paystack reference %s has no Payment row", reference)
        return "unknown", None
    if payment.status == "success":
        return "already", payment
    if tx.get("status") != "success":
        return "failed", payment

    if tx.get("currency", CURRENCY) != CURRENCY or int(tx.get("amount") or 0) != _pesewas(payment.amount):
        payment.status = "mismatch"
        db.session.commit()
        logger.error("Amount/currency mismatch on %s: expected %s %s, got %s %s",
                     reference, payment.amount, CURRENCY, tx.get("amount"), tx.get("currency"))
        return "mismatch", payment

    booking = Booking.query.filter_by(id=payment.booking_id).with_for_update().first()
    payment.status = "success"
    payment.paid_at = datetime.utcnow()
    booking.paid_amount = _money((booking.paid_amount or 0) + payment.amount)
    booking.paystack_ref = reference
    if booking.paid_amount > (booking.total_amount or 0) + 0.005:
        logger.warning("Booking %s is overpaid (paid %s, total %s)",
                       booking.id, booking.paid_amount, booking.total_amount)
    _refresh_payment_status(booking)

    if booking.proposed_status == "accepted" and booking.payment_status == "paid":
        booking.proposed_status = "none"   # negotiated balance has been settled
        booking.proposed_amount = None
        booking.proposed_by = None

    _sync_payout(booking)
    _notify(booking, "worker",
            f"Payment received: GHS {payment.amount:.2f}. Total paid: GHS {booking.paid_amount:.2f} "
            f"of GHS {booking.total_amount:.2f}")
    db.session.commit()
    return "success", payment


def _apply_worker_verification(tx):
    """Mark a worker verified after a genuine, correctly-sized verification payment."""
    metadata = tx.get("metadata") if isinstance(tx.get("metadata"), dict) else {}
    if tx.get("status") != "success" or metadata.get("type") != "verification":
        return False
    if tx.get("currency", CURRENCY) != CURRENCY or int(tx.get("amount") or 0) != VERIFY_FEE_GHS * 100:
        logger.error("Verification payment mismatch on %s", tx.get("reference"))
        return False
    try:
        worker_id = int(metadata.get("worker_id"))
    except (TypeError, ValueError):
        return False
    if not str(tx.get("reference", "")).startswith(f"VERIFY-{worker_id}-"):
        return False
    worker = db.session.get(Worker, worker_id)
    if worker is None:
        return False
    if not worker.is_verified:
        worker.is_verified = True
        worker.verified_at = datetime.utcnow()
        db.session.commit()
    return True


# ---------------------------------------------------------------------------
# Booking payments
# ---------------------------------------------------------------------------
@app.route("/pay/<int:booking_id>", methods=["GET", "POST"])
@customer_required
def pay_booking(booking_id):
    customer = g.customer
    booking = Booking.query.filter_by(id=booking_id, customer_id=customer.id).first_or_404()
    if booking.status == "declined":
        flash("This booking was declined.", "danger")
        return redirect(url_for("customer_dashboard"))

    # The amount is ALWAYS computed server-side: what's still owed.
    amount_due = _money((booking.total_amount or 0) - (booking.paid_amount or 0))
    if amount_due <= 0:
        flash("This booking is already fully paid.", "info")
        return redirect(url_for("customer_dashboard"))

    reference = f"BOOK-{booking.id}-{secrets.token_hex(6)}"
    payment = Payment(reference=reference, booking_id=booking.id, amount=amount_due, status="initiated")
    db.session.add(payment)
    db.session.commit()

    url, error = _paystack_initialize({
        "email": customer.email or "customer@getservicegh.com",
        "amount": _pesewas(amount_due),
        "currency": CURRENCY,
        "reference": reference,
        "callback_url": url_for("pay_callback", booking_id=booking.id, _external=True),
        "metadata": {"booking_id": booking.id, "type": "booking",
                     "cancel_action": url_for("payment_cancel", booking_id=booking.id, _external=True)},
    })
    if url:
        return redirect(url)

    payment.status = "failed"
    db.session.commit()
    flash(f"Payment init failed: {error}", "danger")
    return redirect(url_for("customer_dashboard"))


def _finish_payment(reference, booking_id):
    """Shared by the browser callback and the legacy verify route."""
    payment = (Payment.query.filter_by(reference=reference, booking_id=booking_id).first()
               if reference else None)
    if payment is None:
        flash("Unknown payment reference.", "danger")
        return
    tx = _paystack_verify(reference)
    if tx is None:
        flash("We couldn't confirm your payment yet. If you were charged, it will update shortly.", "warning")
        return
    outcome, payment = _settle_booking_payment(reference, tx)
    if outcome == "success":
        flash(f"Payment successful! GHS {payment.amount:.2f} paid", "success")
    elif outcome == "already":
        flash("Payment already confirmed. Thank you!", "info")
    elif outcome == "mismatch":
        flash("The payment amount didn't match. Please contact support with your reference.", "danger")
    else:
        flash("Payment was not completed.", "danger")


@app.route("/pay/callback/<int:booking_id>")
def pay_callback(booking_id):
    # Settlement is verified against Paystack and the Payment row, so it's safe
    # even if the browser lost its session on the way back.
    _finish_payment(request.args.get("reference") or request.args.get("trxref"), booking_id)
    return redirect(url_for("customer_dashboard"))


@app.route("/verify/booking/<int:booking_id>")
@customer_required
def verify_booking(booking_id):
    # Legacy route. Ownership + reference + amount are all checked now.
    _get_customer_booking(booking_id)
    _finish_payment(request.args.get("reference"), booking_id)
    return redirect(url_for("customer_dashboard"))


@app.route("/paystack/webhook", methods=["POST"])
def paystack_webhook():
    secret = _paystack_secret()
    if not secret:
        abort(503)
    signature = request.headers.get("x-paystack-signature", "")
    expected = hmac.new(secret.encode(), request.get_data(), hashlib.sha512).hexdigest()
    if not hmac.compare_digest(signature.encode(), expected.encode()):
        abort(401)

    payload = request.get_json(silent=True) or {}
    if payload.get("event") == "charge.success":
        tx = payload.get("data") or {}
        reference = str(tx.get("reference") or "")
        try:
            if reference.startswith("VERIFY-"):
                _apply_worker_verification(tx)
            elif reference:
                _settle_booking_payment(reference, tx)
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Webhook processing failed for %s", reference)
            return jsonify({"status": "error"}), 500   # Paystack will retry
    return jsonify({"status": "ok"}), 200


@app.route("/payment/success/<int:booking_id>")
@customer_required
def payment_success(booking_id):
    booking = _get_customer_booking(booking_id)
    return render_template("payment_success.html", booking=booking)


@app.route("/payment/cancel/<int:booking_id>")
@customer_required
def payment_cancel(booking_id):
    booking = _get_customer_booking(booking_id)
    return render_template("payment_cancel.html", booking=booking)


# ---------------------------------------------------------------------------
# Worker verification badge (GHS 50)
# ---------------------------------------------------------------------------
@app.route("/worker/verify")
@worker_required
def verify_worker():
    worker = _current_worker()
    if worker.is_verified:
        flash("You are already verified!", "info")
        return redirect(url_for("worker_dashboard"))

    reference = f"VERIFY-{worker.id}-{int(time.time())}"
    email = worker.email if worker.email and "@" in worker.email else f"worker{worker.id}@getservicegh.com"
    url, error = _paystack_initialize({
        "email": email,
        "amount": VERIFY_FEE_GHS * 100,
        "currency": CURRENCY,
        "reference": reference,
        "callback_url": url_for("verify_callback", _external=True),
        "metadata": {"worker_id": worker.id, "type": "verification"},
    })
    if url:
        return redirect(url)
    flash(f"Paystack error: {error}", "danger")
    return redirect(url_for("worker_dashboard"))


@app.route("/verify/callback")
def verify_callback():
    tx = _paystack_verify(request.args.get("reference") or request.args.get("trxref"))
    if tx and _apply_worker_verification(tx):
        flash("You are now Verified ✓", "success")
    else:
        flash("We couldn't confirm your verification payment yet.", "warning")
    return redirect(url_for("worker_dashboard"))


# ---------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------
@app.route("/rate_worker/<int:booking_id>", methods=["GET", "POST"])
@customer_required
def rate_worker(booking_id):
    booking = _get_customer_booking(booking_id, lock=True)
    if booking.status != "completed":
        flash("You can rate a worker once the job is completed.", "info")
        return redirect(url_for("customer_dashboard"))
    if booking.rating is not None:
        flash("You have already rated this job.", "info")
        return redirect(url_for("customer_dashboard"))

    if request.method == "GET":
        return render_template("rate_worker.html", booking=booking)

    rating = _to_int(request.form.get("rating"), default=0)
    if not 1 <= rating <= 5:
        flash("Please choose a rating from 1 to 5.")
        return render_template("rate_worker.html", booking=booking)
    comment = _clean(request.form.get("review"), 1000)

    try:
        booking.rating = rating
        booking.review = comment
        db.session.add(Review(worker_id=booking.worker_id, customer_name=g.customer.name,
                              rating=rating, comment=comment))
        db.session.flush()
        avg, count = (db.session.query(func.avg(Review.rating), func.count(Review.id))
                      .filter(Review.worker_id == booking.worker_id).one())
        worker = db.session.get(Worker, booking.worker_id)
        worker.rating = round(float(avg or 0), 1)
        worker.total_ratings = int(count or 0)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Saving rating failed")
        flash("We couldn't save your rating. Please try again.", "danger")
        return render_template("rate_worker.html", booking=booking)

    flash("Thanks for your feedback!", "success")
    return redirect(url_for("customer_dashboard"))


# ---------------------------------------------------------------------------
# Phone verification (one-time SMS code)
# ---------------------------------------------------------------------------
# Switched on only when an SMS provider is configured (see INSTALL.md), so deploying this
# code can never lock anyone out. Set REQUIRE_PHONE_VERIFICATION=0 to switch it off again.
OTP_TTL_SECONDS = 10 * 60        # a code works for 10 minutes
OTP_MAX_ATTEMPTS = 5             # wrong guesses allowed per code
OTP_RESEND_SECONDS = 60          # wait between codes
OTP_DAILY_CAP = 5                # codes per account per 24 hours (limits SMS cost and abuse)
OTP_IP_LIMIT = 20                # sends per IP per 15 minutes (high: mobile networks share IPs)
VERIFY_SESSION_SECONDS = 30 * 60
SMS_APP_NAME = "GetService GH"
PHONE_MODELS = {"customer": Customer, "worker": Worker}


def _cfg(name, default=None):
    return os.environ.get(name) or app.config.get(name) or default


def _sms_provider():
    """Name of the usable SMS provider, or None. 'console' only works in debug/testing."""
    provider = (_cfg("SMS_PROVIDER") or "").strip().lower()
    if provider == "arkesel" and _cfg("ARKESEL_API_KEY") and _cfg("SMS_SENDER_ID"):
        return provider
    if provider == "twilio" and _cfg("TWILIO_ACCOUNT_SID") and _cfg("TWILIO_AUTH_TOKEN") and _cfg("TWILIO_FROM"):
        return provider
    if provider == "console" and (app.debug or app.testing):
        return provider
    return None


def _phone_enforced():
    return _sms_provider() is not None and os.environ.get("REQUIRE_PHONE_VERIFICATION", "1") != "0"


def _intl_phone(phone):
    """0241234567 / +233 24 123 4567 -> 233241234567 (what SMS providers expect)."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10 and digits.startswith("0"):
        digits = "233" + digits[1:]
    return digits


def _mask_phone(phone):
    number = _norm_phone(phone)
    return number if len(number) <= 5 else f"{number[:3]}{'•' * (len(number) - 5)}{number[-2:]}"


def _send_sms(to_number, message):
    """Send one SMS. Returns True/False and never raises. `to_number` is digits only, e.g. 233241234567."""
    provider = _sms_provider()
    if provider is None:
        return False
    if provider == "console":
        logger.warning("DEV ONLY SMS to %s: %s", to_number, message)
        return True
    try:
        if provider == "arkesel":
            response = requests.post(
                "https://sms.arkesel.com/api/v2/sms/send",
                headers={"api-key": _cfg("ARKESEL_API_KEY"), "Content-Type": "application/json"},
                json={"sender": _cfg("SMS_SENDER_ID"), "message": message, "recipients": [to_number]},
                timeout=10)
            try:
                body = response.json()
            except ValueError:
                body = {}
            ok = response.status_code == 200 and str(body.get("status", "success")).lower() != "error"
        else:  # twilio
            sid, sender = _cfg("TWILIO_ACCOUNT_SID"), _cfg("TWILIO_FROM")
            data = {"To": f"+{to_number}", "Body": message}
            data["MessagingServiceSid" if sender.startswith("MG") else "From"] = sender
            response = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                                     auth=(sid, _cfg("TWILIO_AUTH_TOKEN")), data=data, timeout=10)
            ok = response.status_code in (200, 201)
        if not ok:
            logger.warning("SMS provider %s refused the message: HTTP %s %s",
                           provider, response.status_code, response.text[:200])
        return ok
    except requests.RequestException:
        logger.exception("Sending SMS via %s failed", provider)
        return False


def _hash_code(role, user_id, phone, code):
    key = str(app.config["SECRET_KEY"]).encode()
    return hmac.new(key, f"otp:{role}:{user_id}:{_intl_phone(phone)}:{code}".encode(), hashlib.sha256).hexdigest()


def _seconds_until_resend(role, user):
    last = (PhoneOTP.query.filter_by(role=role, user_id=user.id)
            .order_by(PhoneOTP.created_at.desc()).first())
    if last is None or last.created_at is None:
        return 0
    return max(0, int(OTP_RESEND_SECONDS - (datetime.utcnow() - last.created_at).total_seconds()))


def _issue_otp(role, user, skip_cooldown=False):
    """Create a fresh code and text it. Returns (ok, message_for_the_user)."""
    if not user.phone:
        return False, "Please add your phone number first."
    now = datetime.utcnow()
    ip_key = f"sms-ip:{request.remote_addr}"
    if _is_locked(ip_key, OTP_IP_LIMIT):
        return False, "Too many requests from your network. Please try again in a few minutes."

    PhoneOTP.query.filter(PhoneOTP.created_at < now - timedelta(days=2)).delete(synchronize_session=False)
    recent = (PhoneOTP.query.filter(PhoneOTP.role == role, PhoneOTP.user_id == user.id,
                                    PhoneOTP.created_at > now - timedelta(hours=24))
              .order_by(PhoneOTP.created_at.desc()).all())
    if len(recent) >= OTP_DAILY_CAP:
        return False, "You have asked for too many codes today. Please try again tomorrow."
    if recent and not skip_cooldown:
        wait = _seconds_until_resend(role, user)
        if wait > 0:
            return False, f"Please wait {wait} seconds before asking for another code."

    code = f"{secrets.randbelow(10 ** 6):06d}"
    PhoneOTP.query.filter_by(role=role, user_id=user.id, consumed=False).update(
        {"consumed": True}, synchronize_session=False)   # only the newest code works
    row = PhoneOTP(role=role, user_id=user.id, phone=user.phone,
                   code_hash=_hash_code(role, user.id, user.phone, code),
                   created_at=now, expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
                   attempts=0, consumed=False)
    db.session.add(row)
    db.session.commit()

    message = (f"{SMS_APP_NAME}: your verification code is {code}. "
               f"It expires in {OTP_TTL_SECONDS // 60} minutes. Never share it with anyone.")
    if not _send_sms(_intl_phone(user.phone), message):
        db.session.delete(row)   # a failed send should not use up the person's daily allowance
        db.session.commit()
        return False, "We couldn't send the SMS right now. Please try again in a moment."
    _record_failure(ip_key)       # counts sends for the per-IP limit
    return True, f"We sent a 6-digit code to {_mask_phone(user.phone)}."


def _check_otp(role, user, submitted):
    """Check a code. On success marks the phone verified. Returns (ok, message)."""
    code = re.sub(r"\D", "", submitted or "")
    if len(code) != 6:
        return False, "Please enter the 6-digit code."
    now = datetime.utcnow()
    row = (PhoneOTP.query.filter_by(role=role, user_id=user.id, consumed=False)
           .order_by(PhoneOTP.created_at.desc()).with_for_update().first())
    if row is None or row.expires_at < now or row.phone != user.phone:
        return False, "That code has expired. Please ask for a new one."
    row.attempts = (row.attempts or 0) + 1
    if not hmac.compare_digest(row.code_hash, _hash_code(role, user.id, user.phone, code)):
        left = OTP_MAX_ATTEMPTS - row.attempts
        if left <= 0:
            row.consumed = True
        db.session.commit()
        if left <= 0:
            return False, "Too many wrong attempts. Please ask for a new code."
        return False, f"That code is not right. {left} attempt{'s' if left != 1 else ''} left."
    PhoneOTP.query.filter_by(role=role, user_id=user.id, consumed=False).update(
        {"consumed": True}, synchronize_session=False)
    user.phone_verified = True
    db.session.commit()
    return True, ""


def _pending_verification():
    """(role, user) for the person partway through verification, else (None, None)."""
    pending = session.get("pv")
    try:
        role, user_id, started = pending["r"], int(pending["i"]), int(pending["t"])
    except (TypeError, KeyError, ValueError):
        return None, None
    if role not in PHONE_MODELS or time.time() - started > VERIFY_SESSION_SECONDS:
        session.pop("pv", None)
        return None, None
    user = db.session.get(PHONE_MODELS[role], user_id)
    if user is None:
        session.pop("pv", None)
        return None, None
    return role, user


def _begin_verification(role, user, send=True):
    """Park the person on the verification page. They are NOT logged in until the code checks out."""
    logout_user()
    session.clear()
    session["pv"] = {"r": role, "i": user.id, "t": int(time.time())}
    if not user.phone:
        flash("Please add your phone number to continue.", "info")
    elif send:
        ok, message = _issue_otp(role, user)
        flash(message, "success" if ok else "danger")
    else:
        flash("Please verify your phone number to continue.", "info")
    response = make_response(redirect(url_for("verify_phone")))
    response.delete_cookie("remember_token")
    return response


def _complete_login(role, user):
    logout_user()
    session.clear()
    if role == "customer":
        session["customer_id"] = user.id
    else:
        login_user(user, remember=True)
    session.permanent = True
    response = make_response(redirect(url_for("worker_dashboard" if role == "worker" else "index")))
    if role == "customer":
        response.delete_cookie("remember_token")
    return response


@app.route("/verify-phone", methods=["GET", "POST"])
def verify_phone():
    role, user = _pending_verification()
    if user is None:
        flash("Please log in to verify your phone number.")
        return redirect(url_for("login_choice"))
    if user.phone_verified:
        return _complete_login(role, user)

    def page(status=200):
        response = make_response(render_template(
            "verify_phone.html", role=role, masked=_mask_phone(user.phone), has_phone=bool(user.phone),
            resend_in=_seconds_until_resend(role, user) if user.phone else 0), status)
        return _no_store(response)

    if request.method == "POST":
        key = _throttle_key("otp-check", f"{role}:{user.id}")
        if _is_locked(key, 15):
            flash("Too many wrong codes. Please wait 15 minutes, then ask for a new code.", "danger")
            return page(429)
        ok, message = _check_otp(role, user, request.form.get("code"))
        if not ok:
            _record_failure(key)
            flash(message, "danger")
            return page()
        _clear_failures(key)
        flash("Phone number verified. Welcome!", "success")
        return _complete_login(role, user)
    return page()


@app.route("/verify-phone/resend", methods=["POST"])
def verify_phone_resend():
    role, user = _pending_verification()
    if user is None:
        return redirect(url_for("login_choice"))
    ok, message = _issue_otp(role, user)
    flash(message, "success" if ok else "danger")
    return redirect(url_for("verify_phone"))


@app.route("/verify-phone/change", methods=["POST"])
def verify_phone_change():
    role, user = _pending_verification()
    if user is None:
        return redirect(url_for("login_choice"))
    phone = _norm_phone(request.form.get("phone"))
    if not PHONE_RE.match(phone):
        flash("Please enter a valid phone number.", "danger")
        return redirect(url_for("verify_phone"))
    model = PHONE_MODELS[role]
    if model.query.filter(model.phone.in_(_phone_variants(phone)), model.id != user.id).first():
        flash("That number is already registered to another account.", "danger")
        return redirect(url_for("verify_phone"))
    try:
        user.phone = phone
        user.phone_verified = False
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("That number is already registered to another account.", "danger")
        return redirect(url_for("verify_phone"))
    ok, message = _issue_otp(role, user, skip_cooldown=True)
    flash(message, "success" if ok else "danger")
    return redirect(url_for("verify_phone"))


# ---------------------------------------------------------------------------
# Password reset (signed, expiring, single-use links; no database changes needed)
# ---------------------------------------------------------------------------
RESET_MODELS = {"customer": Customer, "worker": Worker}


def _mail_setting(name, default=None):
    return os.environ.get(name) or app.config.get(name) or default


def _mail_configured():
    return bool(_mail_setting("MAIL_SERVER") and _mail_setting("MAIL_USERNAME") and _mail_setting("MAIL_PASSWORD"))


def _send_email(to_address, subject, body):
    """Send a plain-text email over SMTP. Returns True/False and never raises.
    Configure with env vars: MAIL_SERVER, MAIL_PORT (587), MAIL_USERNAME, MAIL_PASSWORD,
    MAIL_USE_TLS (1), MAIL_FROM (defaults to MAIL_USERNAME)."""
    if not _mail_configured():
        return False
    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = _mail_setting("MAIL_FROM") or _mail_setting("MAIL_USERNAME")
        message["To"] = to_address
        message.set_content(body)
        host, port = _mail_setting("MAIL_SERVER"), int(_mail_setting("MAIL_PORT", 587))
        user, password = _mail_setting("MAIL_USERNAME"), _mail_setting("MAIL_PASSWORD")
        context = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10, context=context) as smtp:
                smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                if str(_mail_setting("MAIL_USE_TLS", "1")) != "0":
                    smtp.starttls(context=context)
                smtp.login(user, password)
                smtp.send_message(message)
        return True
    except (smtplib.SMTPException, OSError, ValueError):
        logger.exception("Sending email to %s failed", to_address)
        return False


def _reset_serializer(role):
    return URLSafeTimedSerializer(app.config["SECRET_KEY"], salt=f"password-reset-{role}")


def _pw_fingerprint(user):
    # Part of the token: once the password changes, every earlier link stops working.
    return hashlib.sha256((user.password_hash or "").encode()).hexdigest()[:20]


def _make_reset_token(role, user):
    return _reset_serializer(role).dumps({"id": user.id, "f": _pw_fingerprint(user)})


def _load_reset_user(role, token):
    """Return the account a valid, unexpired, unused reset token belongs to, else None."""
    try:
        data = _reset_serializer(role).loads(token, max_age=RESET_TOKEN_MAX_AGE)
        user = db.session.get(RESET_MODELS[role], int(data["id"]))
        fingerprint = str(data["f"])
    except (BadSignature, KeyError, TypeError, ValueError):
        return None
    if user is None or not hmac.compare_digest(fingerprint.encode(), _pw_fingerprint(user).encode()):
        return None
    return user


def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"   # keep the token out of Referer headers
    return response


@app.route("/forgot-password/<role>", methods=["GET", "POST"])
def forgot_password(role):
    if role not in RESET_MODELS:
        abort(404)
    if request.method == "POST":
        identifier = _clean(request.form.get("identifier") or request.form.get("email"), 120)
        key = _throttle_key(f"forgot-{role}", identifier)
        if _is_locked(key):
            flash("Too many requests. Please try again in 15 minutes.")
            return render_template("forgot_password.html", role=role, sent=False), 429
        _record_failure(key)   # every request counts, so this can't be used to spam someone's inbox

        user = _find_by_identifier(RESET_MODELS[role], identifier) if identifier else None
        if user is not None and user.email and EMAIL_RE.match(user.email):
            link = url_for("reset_password", role=role, token=_make_reset_token(role, user), _external=True)
            sent = _send_email(
                user.email, "Reset your GetService GH password",
                f"Hello {user.name or ''},\n\nUse this link to choose a new password. "
                f"It works once and expires in 1 hour:\n\n{link}\n\n"
                "If you did not ask for this, you can ignore this email; your password will not change.\n\n"
                "GetService GH")
            if not sent and app.debug:
                logger.warning("DEV ONLY reset link for %s %s: %s", role, user.id, link)
        elif user is not None:
            logger.info("Password reset asked for %s %s, but there is no email on file", role, user.id)
        # Same answer whether or not an account matched, so this can't be used to find who is registered.
        return render_template("forgot_password.html", role=role, sent=True)
    return render_template("forgot_password.html", role=role, sent=False)


@app.route("/reset-password/<role>/<token>", methods=["GET", "POST"])
def reset_password(role, token):
    if role not in RESET_MODELS:
        abort(404)
    user = _load_reset_user(role, token)
    if user is None:
        flash("This reset link is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for("forgot_password", role=role))

    def page():
        return _no_store(make_response(render_template("reset_password.html", role=role, token=token)))

    if request.method == "POST":
        password = (request.form.get("password") or "").strip()
        confirm = (request.form.get("confirm_password") or "").strip()
        if len(password) < MIN_PASSWORD_LENGTH:
            flash(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", "danger")
            return page()
        if password != confirm:
            flash("The two passwords do not match.", "danger")
            return page()
        try:
            user.set_password(password)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            logger.exception("Password reset failed for %s %s", role, user.id)
            flash("Something went wrong. Please try again.", "danger")
            return page()
        flash("Your password has been changed. Please log in.", "success")
        return redirect(url_for("customer_login" if role == "customer" else "worker_login"))
    return page()


@app.route("/admin/reset-link/<role>/<int:user_id>", methods=["GET", "POST"])
@admin_required
def admin_reset_link(role, user_id):
    """For people with no email on file: an admin makes a one-hour link and passes it on
    privately (e.g. WhatsApp). Generating a link changes nothing in the database."""
    if role not in RESET_MODELS:
        abort(404)
    user = db.session.get(RESET_MODELS[role], user_id)
    if user is None:
        abort(404)
    link = url_for("reset_password", role=role, token=_make_reset_token(role, user), _external=True)
    logger.info("Admin %s generated a password-reset link for %s %s", current_user.id, role, user.id)
    return _no_store(make_response(render_template("admin_reset_link.html", user=user, role=role, link=link)))


# ---------------------------------------------------------------------------
# PWA / Android (Trusted Web Activity) support
# ---------------------------------------------------------------------------
@app.route("/manifest.json")
def manifest():
    """Web app manifest at a predictable root URL, with the correct MIME type.
    The file itself lives at static/manifest.json."""
    response = make_response(app.send_static_file("manifest.json"))
    response.headers["Content-Type"] = "application/manifest+json"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/.well-known/assetlinks.json")
def assetlinks():
    """Digital Asset Links. Without this, the Android app built from your AAB shows
    a browser address bar instead of opening full-screen. File: static/assetlinks.json"""
    response = make_response(app.send_static_file("assetlinks.json"))
    response.headers["Content-Type"] = "application/json"
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
# create_all() only creates MISSING tables (e.g. the new `payment` table). It
# does not alter existing ones; see schema_changes.sql, and consider Flask-Migrate.
with app.app_context():
    db.create_all()
