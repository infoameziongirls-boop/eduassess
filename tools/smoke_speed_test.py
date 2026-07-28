import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import Student, User

ENDPOINTS = [
    '/',
    '/login',
    '/student/login',
    '/static/css/bootstrap.min.css',
]

def measure(client, path, iterations=10):
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        r = client.get(path)
        t1 = time.perf_counter()
        times.append((t1 - t0, r.status_code, len(r.data)))
    return times


def summarize(times):
    durations = [t[0] for t in times]
    return min(durations), sum(durations)/len(durations), max(durations)


def main():
    with app.app_context():
        # ensure DB exists and a test user if needed
        client = app.test_client()

        print('Endpoint, min(s), avg(s), max(s), status_sample, bytes')
        for ep in ENDPOINTS:
            times = measure(client, ep, iterations=8)
            mn, avg, mx = summarize(times)
            status = times[0][1]
            bts = times[0][2]
            print(f'{ep}, {mn:.4f}, {avg:.4f}, {mx:.4f}, {status}, {bts}')


if __name__ == '__main__':
    main()
