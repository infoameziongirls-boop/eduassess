#!/usr/bin/env python3
"""
migrate_results_release.py
---------------------------
One-time migration: adds the results-release columns to the existing
`settings` table. Safe to run multiple times (it checks first).

Why this is needed: db.create_all() (used in models.init_db) only creates
tables that don't exist yet — it never ALTERs an existing table to add
new columns. Since `settings` already existed before this feature was
added, the new Setting.results_released / results_release_date /
results_released_at / results_released_by columns are NOT actually in
your database yet, even though the Python model now defines them. Any
route that touches Setting.query will fail (or misbehave) until this
migration is run once.

Usage:
    python migrate_results_release.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from sqlalchemy import inspect, text


def column_exists(table, column):
    inspector = inspect(db.engine)
    existing = [c['name'] for c in inspector.get_columns(table)]
    return column in existing


def run():
    with app.app_context():
        dialect = db.engine.dialect.name  # 'sqlite' or 'postgresql'
        print(f"Connected to: {dialect}")

        additions = [
            ("results_released",      "BOOLEAN DEFAULT 0" if dialect == "sqlite" else "BOOLEAN DEFAULT FALSE"),
            ("results_release_date",  "DATETIME"           if dialect == "sqlite" else "TIMESTAMP"),
            ("results_released_at",   "DATETIME"           if dialect == "sqlite" else "TIMESTAMP"),
            ("results_released_by",   "INTEGER"),
        ]

        for column, col_type in additions:
            if column_exists("settings", column):
                print(f"[SKIP] settings.{column} already exists")
                continue
            ddl = f"ALTER TABLE settings ADD COLUMN {column} {col_type}"
            print(f"[RUN]  {ddl}")
            db.session.execute(text(ddl))

        db.session.commit()

        # Normalize any NULL results_released rows to False so the
        # is_results_visible() boolean check behaves predictably.
        db.session.execute(
            text("UPDATE settings SET results_released = 0 WHERE results_released IS NULL")
            if dialect == "sqlite" else
            text("UPDATE settings SET results_released = FALSE WHERE results_released IS NULL")
        )
        db.session.commit()

        print("Migration complete.")


if __name__ == "__main__":
    run()
