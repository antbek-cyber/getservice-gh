from flask import Flask
import os
import cloudinary
from extensions import db, login_manager
import models
import routes # this registers routes

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    
    db.init_app(app)
    login_manager.init_app(app)
    
    cloudinary.config( ... )

    from routes import * # import routes inside

    with app.app_context():
        db.create_all()

    return app

app = create_app()


 


    


if __name__ == '__main__':
    app.run(debug=True)
