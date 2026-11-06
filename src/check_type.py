from app import app, db
from sqlalchemy import inspect
with app.app_context():
    for c in inspect(db.engine).get_columns('booking'):
        if 'propos' in c['name'] or 'paid' in c['name']:
            print(c['name'], "->", c['type'])
