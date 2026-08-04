import os

bind = f"0.0.0.0:{os.environ.get('PORT', 10000)}"
workers = 2
timeout = 120
preload_app = True


def post_fork(server, worker):
    from app import app, db

    with app.app_context():
        db.engine.dispose()

    server.log.info("Worker %s: DB engine disposed after fork", worker.pid)