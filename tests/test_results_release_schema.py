import os

from flask import Flask
from sqlalchemy import inspect, text

from models import db, ensure_settings_columns


def test_ensure_settings_columns_adds_missing_columns():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SECRET_KEY'] = 'test-secret'

    db.init_app(app)

    with app.app_context():
        db.drop_all()
        db.session.execute(text("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                current_term VARCHAR(32) NOT NULL,
                current_academic_year VARCHAR(32) NOT NULL,
                current_session VARCHAR(32) NOT NULL,
                assessment_active BOOLEAN
            )
        """))
        db.session.commit()

        ensure_settings_columns()

        inspector = inspect(db.engine)
        columns = {column['name'] for column in inspector.get_columns('settings')}

        assert {'results_released', 'results_release_date', 'results_released_at', 'results_released_by'}.issubset(columns)
