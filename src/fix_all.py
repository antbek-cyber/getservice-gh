from app import app, db
from sqlalchemy import text
with app.app_context():
    db.session.execute(text("""
        -- NOTIFICATION - this is the one failing now
        ALTER TABLE notification ADD COLUMN IF NOT EXISTS proposed_amount FLOAT NULL;
        ALTER TABLE notification ADD COLUMN IF NOT EXISTS proposed_by VARCHAR(20) NULL;
        ALTER TABLE notification ADD COLUMN IF NOT EXISTS proposed_status VARCHAR(20) NULL;
        ALTER TABLE notification ADD COLUMN IF NOT EXISTS customer_id INTEGER NULL;
        ALTER TABLE notification ADD COLUMN IF NOT EXISTS worker_id INTEGER NULL;
        ALTER TABLE notification ADD COLUMN IF NOT EXISTS booking_id INTEGER NULL;
        ALTER TABLE notification ADD COLUMN IF NOT EXISTS message TEXT NULL;
        ALTER TABLE notification ADD COLUMN IF NOT EXISTS is_read BOOLEAN DEFAULT FALSE;
        ALTER TABLE notification ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NULL;

        -- Keep the previous fixes too, so they don't get lost
        ALTER TABLE customer ADD COLUMN IF NOT EXISTS phone_verified BOOLEAN DEFAULT FALSE;
        ALTER TABLE worker ADD COLUMN IF NOT EXISTS phone_verified BOOLEAN DEFAULT FALSE;
        ALTER TABLE booking ADD COLUMN IF NOT EXISTS proposed_amount FLOAT NULL;
        ALTER TABLE booking ADD COLUMN IF NOT EXISTS proposed_by VARCHAR(20) NULL;
        ALTER TABLE booking ADD COLUMN IF NOT EXISTS proposed_status VARCHAR(20) NULL;
    """))
    db.session.commit()
    print("FIXED NOTIFICATION TABLE")
