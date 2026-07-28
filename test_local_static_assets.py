import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db


@pytest.fixture(scope="function")
def app_context():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    with app.app_context():
        ext = app.extensions.get('sqlalchemy')
        if ext and hasattr(ext, '_app_engines'):
            ext._app_engines[app].clear()
            options = {'url': app.config['SQLALCHEMY_DATABASE_URI'], **ext._engine_options}
            engine = ext._make_engine(None, options, app)
            ext._app_engines[app][None] = engine

        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        if ext and hasattr(ext, '_app_engines'):
            ext._app_engines[app].clear()


@pytest.fixture(scope="function")
def client(app_context):
    return app.test_client()


def test_student_login_page_uses_local_static_asset_links(client):
    response = client.get('/student/login')
    assert response.status_code == 200
    html = response.data.decode('utf-8')

    assert '/static/css/bootstrap.min.css' in html
    assert '/static/js/bootstrap.bundle.min.js' in html
    assert '/static/css/bootstrap-icons.css' in html
    assert 'https://fonts.googleapis.com' not in html
    assert 'https://cdn.jsdelivr.net' not in html
    assert 'https://cdnjs.cloudflare.com' not in html


@pytest.mark.parametrize('asset_path', [
    '/static/css/bootstrap.min.css',
    '/static/js/bootstrap.bundle.min.js',
    '/static/css/bootstrap-icons.css',
])
def test_local_static_assets_are_served(client, asset_path):
    response = client.get(asset_path)
    assert response.status_code == 200
    assert len(response.data) > 0
