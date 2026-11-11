# fix_db.py - Run once to fix missing columns
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

# All columns your code expects but DB is missing
fixes = [
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS payout_network VARCHAR(20) DEFAULT 'MTN'",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS payout_name VARCHAR(100)",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS payout_number VARCHAR(20)",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS paystack_recipient_code VARCHAR(100)",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS paystack_recipient_id VARCHAR(100)",
    # Also fix booking table for momo.py we just built
    "ALTER TABLE booking ADD COLUMN IF NOT EXISTS worker_paid BOOLEAN DEFAULT FALSE",
    "ALTER TABLE booking ADD COLUMN IF NOT EXISTS transfer_reference VARCHAR(100)",
    "ALTER TABLE booking ADD COLUMN IF NOT EXISTS momo_reference VARCHAR(100)",
]

with engine.connect() as conn:
    for sql in fixes:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"OK: {sql[:60]}")
        except Exception as e:
            print(f"SKIP: {e}")
print("DONE - Database fixed")
