import os

bind = f"0.0.0.0:{os.environ.get('PORT', 10000)}"
# Keep the Render web process within the memory budget. The teacher tracking
# dashboard can materialize a large roster, so concurrent workers amplify its
# peak memory use on the small service plan.
workers = 1
# Threads let requests waiting on the remote database progress concurrently
# without the memory cost of starting a second Python worker process.
worker_class = "gthread"
threads = 4
timeout = 120
preload_app = True
max_requests = 100
max_requests_jitter = 20


def post_fork(server, worker):
    from app import app, db

    with app.app_context():
        db.engine.dispose()

    server.log.info("Worker %s: DB engine disposed after fork", worker.pid)