# fix_db.py - V3 - Add exact columns from error log
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

fixes = [
    # WorkerPayout - EXACT columns from your error log
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS customer_paid FLOAT DEFAULT 0",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS platform_fee FLOAT DEFAULT 0",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS worker_earnings FLOAT DEFAULT 0",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS released_at TIMESTAMP",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS attempts INTEGER DEFAULT 0",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS failure_reason TEXT",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMP",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS paystack_transfer_ref VARCHAR(100)",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS recipient_code VARCHAR(100)",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'queued'",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS worker_id INTEGER",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS booking_id INTEGER",
    # Keep old ones too so nothing breaks
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS amount FLOAT DEFAULT 0",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS momo_reference VARCHAR(100)",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS transfer_reference VARCHAR(100)",

    # Worker table
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS payout_network VARCHAR(20) DEFAULT 'MTN'",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS payout_name VARCHAR(100)",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS payout_number VARCHAR(20)",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS paystack_recipient_code VARCHAR(100)",

    # Booking table for momo.py
    "ALTER TABLE booking ADD COLUMN IF NOT EXISTS worker_paid BOOLEAN DEFAULT FALSE",
    "ALTER TABLE booking ADD COLUMN IF NOT EXISTS transfer_reference VARCHAR(100)",
    "ALTER TABLE booking ADD COLUMN IF NOT EXISTS momo_reference VARCHAR(100)",
]

with engine.connect() as conn:
    for sql in fixes:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"OK: {sql[:70]}")
        except Exception as e:
            print(f"SKIP: {e}")
print("DONE - V3 Fixed")
