"""GetService GH: application factory.

Run locally:   python app.py
Production:    gunicorn app:app
"""
import logging
import os
from datetime import timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()   # must run BEFORE anything below reads the environment
except ImportError:  # python-dotenv is optional in production
    pass

import cloudinary
from flask import Flask
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix

from extensions import db, login_manager
import models  # noqa: F401  (importing registers every table with SQLAlchemy)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("getservice")

INSECURE_KEYS = {"", "dev-secret-key", "changeme", "secret"}


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
def _secret_key():
    """Sessions, password-reset links and SMS codes are all signed with this key, so a guessable
    key would let anyone forge a login. Refuse to start in production without a real one."""
    key = os.getenv("SECRET_KEY", "")
    if key not in INSECURE_KEYS:
        return key
    if os.getenv("FLASK_DEBUG") == "1" or os.getenv("FLASK_ENV") == "development":
        log.warning("SECRET_KEY is not set: using an INSECURE development key. Never do this in production.")
        return "dev-secret-key"
    raise RuntimeError(
        "SECRET_KEY is missing or insecure. Set a long random SECRET_KEY in your environment, for example: "
        "python -c \"import secrets; print(secrets.token_hex(32))\"")


def _database_url():
    url = os.getenv("DATABASE_URL", "sqlite:///getservice.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://") and "psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


# ---------------------------------------------------------------------------
# Database upkeep that runs at startup (additive only: nothing is ever dropped or changed)
# ---------------------------------------------------------------------------
def _sql_default(column, dialect_name):
    """A DEFAULT clause for a column's plain Python default (so existing rows get it too)."""
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return ""
    value = default.arg
    if isinstance(value, bool):
        if dialect_name == "sqlite":
            return " DEFAULT 1" if value else " DEFAULT 0"
        return " DEFAULT TRUE" if value else " DEFAULT FALSE"
    if isinstance(value, (int, float)):
        return f" DEFAULT {value}"
    if isinstance(value, str):
        return " DEFAULT '" + value.replace("'", "''") + "'"
    return ""


def add_missing_schema(engine=None, metadata=None):
    """Add any column or index the models define but the database does not have yet.
    db.create_all() only creates missing TABLES; this covers the gap for existing tables,
    so new releases no longer need hand-written ALTER statements."""
    engine = engine or db.engine
    metadata = metadata if metadata is not None else db.metadata
    dialect = engine.dialect
    quote = dialect.identifier_preparer.quote

    for table in metadata.sorted_tables:
        inspector = inspect(engine)
        if not inspector.has_table(table.name):
            continue   # create_all has just built it, complete
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            if not column.nullable and column.default is None and column.server_default is None:
                log.warning("Cannot auto-add NOT NULL column %s.%s without a default; add it by hand.",
                            table.name, column.name)
                continue
            if_not_exists = "IF NOT EXISTS " if dialect.name == "postgresql" else ""
            ddl = (f"ALTER TABLE {quote(table.name)} ADD COLUMN {if_not_exists}{quote(column.name)} "
                   f"{column.type.compile(dialect=dialect)}{_sql_default(column, dialect.name)}")
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                log.info("Database: added column %s.%s", table.name, column.name)
            except SQLAlchemyError as exc:
                log.warning("Database: could not add column %s.%s (%s)", table.name, column.name,
                            str(exc).splitlines()[0][:160])

        present = {i["name"] for i in inspect(engine).get_indexes(table.name)}
        for index in table.indexes:
            if index.name and index.name not in present:
                try:
                    index.create(engine)
                    log.info("Database: created index %s", index.name)
                except SQLAlchemyError as exc:
                    log.warning("Database: could not create index %s (%s)", index.name,
                                str(exc).splitlines()[0][:160])


def bootstrap_admin():
    """Create the first super admin from ADMIN_EMAIL + ADMIN_PASSWORD, but only while NO admin exists.
    Remove ADMIN_PASSWORD from the environment once you have logged in."""
    email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD") or ""
    if not email or not password:
        return
    try:
        if models.User.query.filter_by(is_admin=True).first() is not None:
            return
        if len(password) < 10:
            log.error("ADMIN_PASSWORD must be at least 10 characters. No admin was created.")
            return
        user = models.User.query.filter(db.func.lower(models.User.email) == email).first()
        if user is None:
            user = models.User(username=os.getenv("ADMIN_USERNAME") or email.split("@")[0], email=email)
            db.session.add(user)
        user.role, user.is_admin, user.is_super_admin = "super_admin", True, True
        user.admin_permissions = user.admin_permissions or {}
        user.set_password(password)
        db.session.commit()
        log.warning("Created the first super admin (%s). Remove ADMIN_PASSWORD from your environment now.", email)
    except (SQLAlchemyError, IntegrityError):
        db.session.rollback()
        log.exception("Could not create the first admin")


def log_feature_status(routes_module):
    """One line per integration, so a missing environment variable is obvious in the logs."""
    def has(*names):
        return all(os.getenv(n) for n in names)
    sms = getattr(routes_module, "_sms_provider", lambda: None)()
    features = {
        "Paystack payments": has("PAYSTACK_SECRET_KEY"),
        "Scheduled payout retries (CRON_SECRET)": has("CRON_SECRET"),
        "Email for password reset": has("MAIL_SERVER", "MAIL_USERNAME", "MAIL_PASSWORD"),
        f"SMS phone verification ({sms})" if sms else "SMS phone verification": sms is not None,
        "Phone alerts (VAPID keys)": has("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY"),
        "Cloudinary photo uploads": has("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"),
    }
    for name, enabled in features.items():
        log.info("%-48s %s", name, "ON" if enabled else "off")


# ---------------------------------------------------------------------------
# The application factory
# ---------------------------------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=_secret_key(),
        SQLALCHEMY_DATABASE_URI=_database_url(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # Drop dead connections instead of failing the request (hosted Postgres closes idle ones).
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 280},
        PERMANENT_SESSION_LIFETIME=timedelta(days=365),
        REMEMBER_COOKIE_DURATION=timedelta(days=365),
        # Kept from your original file; the current routes do not use Google sign-in.
        GOOGLE_CLIENT_ID=os.getenv("GOOGLE_CLIENT_ID"),
        GOOGLE_CLIENT_SECRET=os.getenv("GOOGLE_CLIENT_SECRET"),
        GOOGLE_REDIRECT_URI=os.getenv("GOOGLE_REDIRECT_URI"),
    )

    # Behind Render/Heroku-style proxies the app only sees the proxy's address and plain http.
    # Without this, every visitor shares one IP (breaking the login and SMS rate limits) and
    # Paystack callback / password-reset links are built as http:// instead of https://.
    if os.getenv("BEHIND_PROXY", "1") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    db.init_app(app)
    login_manager.init_app(app)

    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
        secure=True,
    )

    with app.app_context():
        import routes   # registers every route; must be imported inside the app context
        db.create_all()   # new tables
        if os.getenv("AUTO_MIGRATE", "1") == "1":
            add_missing_schema()   # new columns and indexes on existing tables
        bootstrap_admin()
        log_feature_status(routes)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
