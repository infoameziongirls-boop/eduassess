import os

bind = f"0.0.0.0:{os.environ.get('PORT', 10000)}"

# Upgraded to Render's Standard plan (2 GB RAM / 1 CPU) as of Sep 2026 —
# roughly 4x the memory the previous single-worker setup was budgeted
# for (see the old comment this replaces). Two workers now fit
# comfortably, and — more importantly than the extra throughput — give
# the service redundancy: when one worker recycles (max_requests below)
# or is mid-request on something slow, the other can still serve
# traffic instead of every request queueing behind a single process.
# If you ever see memory pressure in Render's Metrics tab after this
# change, drop back to workers = 1 rather than upgrading compute again —
# the roster-heavy dashboard is the known memory cost driver here.
workers = 2

# Threads still let each worker make progress on multiple requests
# that are waiting on the remote database, without doubling process
# count again.
worker_class = "gthread"
threads = 2

timeout = 120
preload_app = True

# Recycling every 100 requests was conservative because a leaked-memory
# worker on the old plan could tip the whole service into OOM. With
# 2 GB now available and two workers for redundancy, recycle far less
# often — fewer recycles means fewer moments where a worker (and the
# db.create_all() table check it re-runs on boot) is unavailable.
max_requests = 500
max_requests_jitter = 100


def post_fork(server, worker):
    from app import app, db

    with app.app_context():
        db.engine.dispose()

    server.log.info("Worker %s: DB engine disposed after fork", worker.pid)
