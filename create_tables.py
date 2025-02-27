from app import create_app
from models import db

app = create_app()

with app.app_context():
    # Create all tables
    db.create_all()
    print("Database tables created successfully")
