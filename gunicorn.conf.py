# gunicorn.conf.py
workers = 2
worker_class = "sync"
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
preload_app = True


def post_fork(server, worker):
    from app import db
    db.engine.dispose()