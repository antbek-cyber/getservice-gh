from app import app, db
from sqlalchemy import text, inspect

with app.app_context():
    cols = [c['name'] for c in inspect(db.engine).get_columns('booking')]
    print(cols)
    if 'paid_amount' not in cols:
        db.session.execute(text("ALTER TABLE booking ADD COLUMN paid_amount FLOAT DEFAULT 0"))
        print("Added paid_amount")
    if 'proposed_amount' not in cols:
        db.session.execute(text("ALTER TABLE booking ADD COLUMN proposed_amount FLOAT"))
        print("Added proposed_amount")
    if 'proposed_by' not in cols:
        db.session.execute(text("ALTER TABLE booking ADD COLUMN proposed_by VARCHAR(20)"))
        print("Added proposed_by")
    if 'proposed_status' not in cols:
        db.session.execute(text("ALTER TABLE booking ADD COLUMN proposed_status VARCHAR(20) DEFAULT 'none'"))
        print("Added proposed_status")
    db.session.commit()
    print("DONE")
