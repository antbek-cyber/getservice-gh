-- Run ONCE against your existing database BEFORE deploying the new code.
-- Back up first. Section 0 can only be run once (re-running says the column already exists; that is fine).
-- Sections 1 to 3 are safe to re-run.
-- (The new `payment` table is created automatically by db.create_all().)

-- 0. SMS phone verification: new columns (PostgreSQL and SQLite) ---------------
-- Existing accounts start as "not verified". The new `phone_otp` table is created by db.create_all().
ALTER TABLE customer ADD COLUMN phone_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE worker   ADD COLUMN phone_verified BOOLEAN DEFAULT FALSE;
-- OPTIONAL: if you would rather NOT make existing users verify at their next login, run these two lines.
-- (Only do this if you trust the phone numbers you already hold.)
-- UPDATE customer SET phone_verified = TRUE;
-- UPDATE worker   SET phone_verified = TRUE;

-- 1. Indexes (work on PostgreSQL and SQLite) ---------------------------------
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

-- 2. Data clean-up ------------------------------------------------------------
-- Customers registered without a phone were stored as '' which collides with the
-- UNIQUE constraint. The new code stores NULL instead.
UPDATE customer SET phone = NULL WHERE phone = '';

-- Worker.status was set to 'approved' at signup even though approval is pending.
-- Align it with is_approved (the field the app actually filters on).
UPDATE worker SET status = CASE WHEN is_approved THEN 'approved' ELSE 'pending' END;

-- 3. notification.customer_id foreign key -- PostgreSQL ONLY -------------------
-- It pointed at "user"(id) (admins) instead of customer(id), so inserting a
-- notification for a customer could fail. SQLite doesn't enforce FKs by
-- default, so skip this block there.
-- Orphaned rows (ids that aren't customers) must go before the new FK can be added.
BEGIN;
DELETE FROM notification
 WHERE customer_id IS NOT NULL
   AND customer_id NOT IN (SELECT id FROM customer);
ALTER TABLE notification DROP CONSTRAINT IF EXISTS notification_customer_id_fkey;
ALTER TABLE notification
  ADD CONSTRAINT notification_customer_id_fkey
  FOREIGN KEY (customer_id) REFERENCES customer (id);
COMMIT;
