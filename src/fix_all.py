from app import app, db
from sqlalchemy import text
with app.app_context():
    db.session.execute(text("""
        -- CUSTOMER - this is the one failing now
        ALTER TABLE customer ADD COLUMN IF NOT EXISTS phone_verified BOOLEAN DEFAULT FALSE;
        ALTER TABLE customer ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP NULL;
        ALTER TABLE customer ADD COLUMN IF NOT EXISTS fcm_token VARCHAR(255) NULL;
        ALTER TABLE customer ADD COLUMN IF NOT EXISTS profile_pic VARCHAR(255) NULL;
        ALTER TABLE customer ADD COLUMN IF NOT EXISTS otp_code VARCHAR(10) NULL;
        ALTER TABLE customer ADD COLUMN IF NOT EXISTS otp_expiry TIMESTAMP NULL;

        -- WORKER - just in case
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS phone_verified BOOLEAN DEFAULT FALSE;
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP NULL;
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS fcm_token VARCHAR(255) NULL;
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS is_approved BOOLEAN DEFAULT FALSE;
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS otp_code VARCHAR(10) NULL;
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS otp_expiry TIMESTAMP NULL;

        -- BOOKING - from before
        ALTER TABLE booking ADD COLUMN IF NOT EXISTS paid_amount FLOAT DEFAULT 0.0;
        ALTER TABLE booking ADD COLUMN IF NOT EXISTS proposed_amount FLOAT NULL;
        ALTER TABLE booking ADD COLUMN IF NOT EXISTS proposed_by VARCHAR(20) NULL;
        ALTER TABLE booking ADD COLUMN IF NOT EXISTS proposed_status VARCHAR(20) DEFAULT 'none';
    """))
    db.session.commit()
    print("FIXED ALL TABLES")
