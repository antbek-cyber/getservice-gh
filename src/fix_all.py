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

        CREATE INDEX IF NOT EXISTS ix_worker_approved_rating      ON worker (is_approved, rating);
        CREATE INDEX IF NOT EXISTS ix_booking_worker_created      ON booking (worker_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_booking_customer_created    ON booking (customer_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_booking_paystack_ref        ON booking (paystack_ref);
        CREATE INDEX IF NOT EXISTS ix_notification_worker_unread  ON notification (worker_id, is_read);
        CREATE INDEX IF NOT EXISTS ix_notification_customer_unread ON notification (customer_id, is_read);
        CREATE INDEX IF NOT EXISTS ix_notification_booking        ON notification (booking_id);
        CREATE INDEX IF NOT EXISTS ix_review_worker_id            ON review (worker_id);
        CREATE INDEX IF NOT EXISTS ix_worker_payout_worker_id     ON worker_payout (worker_id);
        CREATE INDEX IF NOT EXISTS ix_job_customer_id             ON job (customer_id);
        CREATE INDEX IF NOT EXISTS ix_work_photo_worker_id        ON work_photo (worker_id);
        CREATE INDEX IF NOT EXISTS ix_push_subscription_user_id   ON push_subscription (user_id);

        -- BOOKING - from before
        ALTER TABLE booking ADD COLUMN IF NOT EXISTS paid_amount FLOAT DEFAULT 0.0;
        ALTER TABLE booking ADD COLUMN IF NOT EXISTS proposed_amount FLOAT NULL;
        ALTER TABLE booking ADD COLUMN IF NOT EXISTS proposed_by VARCHAR(20) NULL;
        ALTER TABLE booking ADD COLUMN IF NOT EXISTS proposed_status VARCHAR(20) DEFAULT 'none';
    """))
    db.session.commit()
    print("FIXED ALL TABLES")
