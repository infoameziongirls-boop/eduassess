from flask_sqlalchemy import SQLAlchemy
from flask import current_app
from sqlalchemy.engine import make_url
import re


def redact_database_url(value):
	"""Return a safe representation of a database URL or error message."""
	text = str(value)
	try:
		return make_url(text).render_as_string(hide_password=True)
	except Exception:
		return re.sub(
			r'((?:postgres(?:ql)?|mysql(?:\+[^:/\s]+)?|sqlite)://[^:/\s]+:)[^@\s]+(@)',
			r'\1***\2',
			text,
		)

db = SQLAlchemy()

# Defensive wrappers for test runs: some tests set `app.config['TESTING']`
# at runtime and then call `db.drop_all()` or `db.create_all()` inside an
# application context. If `SQLALCHEMY_DATABASE_URI` hasn't been set yet,
# Flask-SQLAlchemy raises an UnboundExecutionError. Ensure a sensible
# in-memory default is applied automatically when the app is in testing
# mode so test helpers can call DB lifecycle methods without extra setup.
_orig_drop_all = db.drop_all
def _drop_all_with_test_default(*args, **kwargs):
	try:
		app = current_app._get_current_object()
	except RuntimeError:
		app = None
	if app and app.config.get('TESTING') and not app.config.get('SQLALCHEMY_DATABASE_URI'):
		app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
	# Ensure the SQLAlchemy extension has an engine for this app when we
	# set the DB URI late during tests. This mirrors the logic used in
	# models.init_db to create a per-app engine so `drop_all` succeeds.
	try:
		ext = db
		if getattr(ext, '_app_engines', None) is not None:
			options = {'url': app.config['SQLALCHEMY_DATABASE_URI'], **getattr(ext, '_engine_options', {})}
			try:
				engine = ext._make_engine(None, options, app)
				ext._app_engines.setdefault(app, {})[None] = engine
			except Exception:
				pass
	except Exception:
		pass
	return _orig_drop_all(*args, **kwargs)

db.drop_all = _drop_all_with_test_default

_orig_create_all = db.create_all
def _create_all_with_test_default(*args, **kwargs):
	try:
		app = current_app._get_current_object()
	except RuntimeError:
		app = None
	if app and app.config.get('TESTING') and not app.config.get('SQLALCHEMY_DATABASE_URI'):
		app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
	try:
		ext = db
		if getattr(ext, '_app_engines', None) is not None:
			options = {'url': app.config['SQLALCHEMY_DATABASE_URI'], **getattr(ext, '_engine_options', {})}
			try:
				engine = ext._make_engine(None, options, app)
				ext._app_engines.setdefault(app, {})[None] = engine
			except Exception:
				pass
	except Exception:
		pass
	return _orig_create_all(*args, **kwargs)

db.create_all = _create_all_with_test_default
