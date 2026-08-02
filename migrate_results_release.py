#!/usr/bin/env python3
"""
migrate_results_release.py
---------------------------
One-time migration: adds the results-release columns to the existing
`settings` table. Safe to run multiple times (idempotent).

Works against both PostgreSQL (Neon, Render Postgres, RDS, etc.) and
SQLite (local dev). Uses each database's own "add column if it doesn't
already exist" mechanism, so there's no manual type-name branching that
can drift out of sync — that's what caused the earlier failure ("DATETIME"
is a SQLite-only type name; PostgreSQL's equivalent is "TIMESTAMP").

Usage:
    python migrate_results_release.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from sqlalchemy import inspect, text


def run():
    with app.app_context():
        dialect = db.engine.dialect.name  # 'postgresql' or 'sqlite'
        print(f"Connected to: {dialect}")

        if dialect == "postgresql":
            # Postgres supports "ADD COLUMN IF NOT EXISTS" natively —
            # no need to introspect first, and no room for a type-name
            # mismatch since we spell out real Postgres types directly.
            statements = [
                "ALTER TABLE settings ADD COLUMN IF NOT EXISTS results_released BOOLEAN DEFAULT FALSE",
                "ALTER TABLE settings ADD COLUMN IF NOT EXISTS results_release_date TIMESTAMP",
                "ALTER TABLE settings ADD COLUMN IF NOT EXISTS results_released_at TIMESTAMP",
                "ALTER TABLE settings ADD COLUMN IF NOT EXISTS results_released_by INTEGER",
            ]
            for stmt in statements:
                print(f"[RUN]  {stmt}")
                db.session.execute(text(stmt))
            db.session.commit()

            db.session.execute(text(
                "UPDATE settings SET results_released = FALSE WHERE results_released IS NULL"
            ))
            db.session.commit()

        elif dialect == "sqlite":
            # SQLite's ALTER TABLE doesn't support IF NOT EXISTS reliably
            # across versions, so check first via the inspector.
            inspector = inspect(db.engine)
            existing = {c['name'] for c in inspector.get_columns('settings')}

            additions = [
                ("results_released",     "BOOLEAN DEFAULT 0"),
                ("results_release_date", "DATETIME"),
                ("results_released_at",  "DATETIME"),
                ("results_released_by",  "INTEGER"),
            ]
            for column, col_type in additions:
                if column in existing:
                    print(f"[SKIP] settings.{column} already exists")
                    continue
                stmt = f"ALTER TABLE settings ADD COLUMN {column} {col_type}"
                print(f"[RUN]  {stmt}")
                db.session.execute(text(stmt))
            db.session.commit()

            db.session.execute(text(
                "UPDATE settings SET results_released = 0 WHERE results_released IS NULL"
            ))
            db.session.commit()

        else:
            print(f"Unrecognized dialect '{dialect}' — please add a branch for it.")
            sys.exit(1)

        print("Migration complete.")


if __name__ == "__main__":
    run()
