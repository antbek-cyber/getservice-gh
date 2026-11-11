# fix_db.py - V2 - Fix worker_payout table + columns
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

fixes = [
    # 1. CREATE the missing worker_payout table
    """
    CREATE TABLE IF NOT EXISTS worker_payout (
        id SERIAL PRIMARY KEY,
        worker_id INTEGER REFERENCES worker(id),
        booking_id INTEGER REFERENCES booking(id),
        amount FLOAT DEFAULT 0,
        status VARCHAR(20) DEFAULT 'queued',
        reference VARCHAR(100),
        momo_reference VARCHAR(100),
        transfer_reference VARCHAR(100),
        payout_network VARCHAR(20) DEFAULT 'MTN',
        payout_number VARCHAR(20),
        error_message TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    # 2. Fix worker table columns (from last time)
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS payout_network VARCHAR(20) DEFAULT 'MTN'",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS payout_name VARCHAR(100)",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS payout_number VARCHAR(20)",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS paystack_recipient_code VARCHAR(100)",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS paystack_recipient_id VARCHAR(100)",

    # 3. Fix booking table for momo.py
    "ALTER TABLE booking ADD COLUMN IF NOT EXISTS worker_paid BOOLEAN DEFAULT FALSE",
    "ALTER TABLE booking ADD COLUMN IF NOT EXISTS transfer_reference VARCHAR(100)",
    "ALTER TABLE booking ADD COLUMN IF NOT EXISTS momo_reference VARCHAR(100)",
    "ALTER TABLE booking ADD COLUMN IF NOT EXISTS payout_id INTEGER",

    # 4. If worker_payout already exists but missing a column, add it
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS momo_reference VARCHAR(100)",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS transfer_reference VARCHAR(100)",
    "ALTER TABLE worker_payout ADD COLUMN IF NOT EXISTS error_message TEXT",
]

with engine.connect() as conn:
    for sql in fixes:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"OK: {sql.strip()[:60]}")
        except Exception as e:
            print(f"SKIP: {e}")
print("DONE - Database fixed V2")
