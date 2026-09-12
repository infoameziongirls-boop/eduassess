import os
import sys

import pytest
from sqlalchemy.exc import OperationalError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import _is_disconnect_error, app, db, db_retry


def test_disconnect_marker_is_recognized():
    assert _is_disconnect_error(Exception('SSL connection has been closed unexpectedly'))
    assert not _is_disconnect_error(Exception('duplicate key value violates unique constraint'))


def test_db_retry_retries_disconnect_once(monkeypatch):
    calls = []

    @db_retry
    def flaky_view():
        calls.append(True)
        if len(calls) == 1:
            raise OperationalError(
                'SELECT 1', {}, Exception('connection reset by peer')
            )
        return 'ok'

    with app.app_context():
        monkeypatch.setattr(db.session, 'rollback', lambda: None)
        monkeypatch.setattr(db.session, 'remove', lambda: None)
        monkeypatch.setattr(db.engine, 'dispose', lambda: None)
        with app.test_request_context('/test'):
            assert flaky_view() == 'ok'
    assert len(calls) == 2