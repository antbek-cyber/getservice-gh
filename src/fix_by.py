from app import app, db
from sqlalchemy import text
with app.app_context():
    db.session.execute(text("ALTER TABLE booking ALTER COLUMN proposed_by TYPE VARCHAR(20) USING proposed_by::text"))
    db.session.commit()
    print("FIXED proposed_by")
