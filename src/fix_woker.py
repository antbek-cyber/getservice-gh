from app import app, db
from sqlalchemy import text
with app.app_context():
    db.session.execute(text("""
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS phone_verified BOOLEAN DEFAULT FALSE;
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP NULL;
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS fcm_token VARCHAR(255) NULL;
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS is_approved BOOLEAN DEFAULT FALSE;
    """))
    db.session.commit()
    print("FIXED worker columns")
