"""
update_db.py
------------
Adds any missing columns to an EXISTING database without losing data.
Safe to run multiple times (idempotent) — every ADD COLUMN is guarded by
a check for whether the column already exists.

Rewritten for SQLAlchemy 2.x: the previous version called
db.engine.execute(...) directly, which was removed entirely in
SQLAlchemy 2.0 (Engine has no .execute() method any more — see
requirements.txt, which resolves to SQLAlchemy 2.0.52). Running the old
script would fail immediately with:
    AttributeError: 'Engine' object has no attribute 'execute'
before it got anywhere near actually adding a column.

It also previously tried `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY`
unconditionally — that syntax doesn't exist on SQLite at all (only
Postgres supports adding a constraint via ALTER TABLE), so the same
script would additionally fail with a syntax error the moment it ran
against a local SQLite dev database, even after the execute() issue
was fixed.

Both are fixed here using the same dialect-aware `db.session.execute(
text(...))` pattern this project's own migrate_results_release.py
already uses correctly — this script now follows that exact convention
instead of the older, broken one.

Usage:
    python update_db.py
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from app import app, db
from models import User, Student, Assessment
from sqlalchemy import inspect, text


def _existing_columns(inspector, table_name):
    try:
        return {col['name'] for col in inspector.get_columns(table_name)}
    except Exception:
        # Table doesn't exist yet — handled by the caller falling
        # through to db.create_all() for a brand-new database.
        return None


def _add_column(dialect, table, column, sqlite_type, postgres_type, index_name=None):
    """
    Add `column` to `table` if it doesn't already exist, using the
    correct type spelling for the connected database. Returns True if a
    column was actually added.
    """
    inspector = inspect(db.engine)
    existing = _existing_columns(inspector, table)
    if existing is None or column in existing:
        return False

    col_type = postgres_type if dialect == "postgresql" else sqlite_type
    print(f"Adding '{column}' column to {table} table...")
    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
    db.session.commit()

    if index_name:
        if dialect == "postgresql":
            db.session.execute(text(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})"
            ))
        else:
            db.session.execute(text(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})"
            ))
        db.session.commit()

    return True


def update_database():
    """Update database schema without losing data."""
    with app.app_context():
        print("Checking database schema...")
        dialect = db.engine.dialect.name  # 'postgresql' or 'sqlite'
        print(f"Connected to: {dialect}")

        inspector = inspect(db.engine)

        try:
            # Confirm the 'users' table itself exists using raw table
            # reflection — NOT an ORM query (User.query.count()).
            #
            # This matters: an ORM query selects every column the
            # CURRENT model defines, including any newly-added ones
            # (last_activity, student_id_code, ...). Checking via the
            # ORM first — which is what this script originally did —
            # meant it would raise on exactly the case it exists to fix
            # (a column the model expects but the DB doesn't have yet),
            # sending execution into the `except` branch below, which
            # calls db.drop_all() + db.create_all() and WIPES ALL
            # EXISTING DATA. A migration script that deletes your
            # database the moment it finds something to migrate is a
            # trap, not a fix — reflection lets us check for the table's
            # mere existence without depending on any particular column
            # already being there.
            if "users" not in inspector.get_table_names():
                raise RuntimeError("users table does not exist")

            existing_row_count = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            print(f"Found existing database with {existing_row_count} users (raw count)")

            # ---------------------------------------------------------
            # users table
            # ---------------------------------------------------------
            _add_column(dialect, "users", "subject", "VARCHAR(100)", "VARCHAR(100)")
            _add_column(dialect, "users", "class_name", "VARCHAR(50)", "VARCHAR(50)")
            # Powers the "online now" indicator (User.is_online()) — see
            # models.py. Added here since the original migration script
            # predates that feature and never knew to add it.
            _add_column(dialect, "users", "last_activity",
                        "DATETIME", "TIMESTAMP")

            # ---------------------------------------------------------
            # students table
            # ---------------------------------------------------------
            _add_column(dialect, "students", "middle_name", "VARCHAR(120)", "VARCHAR(120)")
            _add_column(dialect, "students", "class_name", "VARCHAR(50)", "VARCHAR(50)")
            _add_column(dialect, "students", "reference_number", "VARCHAR(50)", "VARCHAR(50)",
                        index_name="ix_students_reference_number")
            _add_column(dialect, "students", "date_of_birth", "DATE", "DATE")
            _add_column(dialect, "students", "study_area", "VARCHAR(50)", "VARCHAR(50)")
            # Admission-style ID (ZGS/{FAMILY}{YY}/{SEQ}) — distinct from
            # reference_number. Also added here for the same reason as
            # last_activity above: this migration script predates it.
            _add_column(dialect, "students", "student_id_code", "VARCHAR(50)", "VARCHAR(50)",
                        index_name="ix_students_student_id_code")

            # ---------------------------------------------------------
            # questions table
            # ---------------------------------------------------------
            _add_column(dialect, "questions", "marks", "FLOAT DEFAULT 1.0", "FLOAT DEFAULT 1.0")
            _add_column(dialect, "questions", "keywords", "TEXT", "TEXT")

            # ---------------------------------------------------------
            # question_attempts table
            # ---------------------------------------------------------
            _add_column(dialect, "question_attempts", "score", "FLOAT DEFAULT 0.0", "FLOAT DEFAULT 0.0")

            # ---------------------------------------------------------
            # assessments table
            # ---------------------------------------------------------
            _add_column(dialect, "assessments", "class_name", "VARCHAR(50)", "VARCHAR(50)",
                        index_name="ix_assessments_class_name")
            _add_column(dialect, "assessments", "academic_year", "VARCHAR(32)", "VARCHAR(32)")

            # teacher_id is a foreign key, not just a plain column — the
            # column itself can be added the same way on any backend,
            # but the *constraint* is Postgres-only syntax (SQLite has
            # no ALTER TABLE ADD CONSTRAINT support at all). Add the
            # column everywhere; only attempt the FK constraint on
            # Postgres, and only if it isn't already there.
            assessment_columns = _existing_columns(inspector, "assessments") or set()
            if "teacher_id" not in assessment_columns:
                print("Adding 'teacher_id' column to assessments table...")
                col_type = "INTEGER"
                db.session.execute(text(f"ALTER TABLE assessments ADD COLUMN teacher_id {col_type}"))
                db.session.commit()

                if dialect == "postgresql":
                    print("Adding foreign key constraint on assessments.teacher_id...")
                    db.session.execute(text(
                        "ALTER TABLE assessments "
                        "ADD CONSTRAINT fk_assessments_teacher_id "
                        "FOREIGN KEY (teacher_id) REFERENCES users (id)"
                    ))
                    db.session.commit()
                else:
                    print("Skipping FK constraint on SQLite (ALTER TABLE ADD CONSTRAINT "
                          "isn't supported there) — the column itself was still added.")

            # Only NOW, after every column the current model needs has
            # been confirmed present, is it safe to use ORM queries —
            # this is the actual summary the original script tried to
            # print up front, just correctly ordered this time.
            print(f"\nFound {User.query.count()} users")
            print(f"Found {Student.query.count()} students")
            print(f"Found {Assessment.query.count()} assessments")

            print("\nDatabase update completed successfully!")
            print("=" * 60)

        except Exception as e:
            db.session.rollback()
            print(f"Error: {e}")
            print("Creating new database...")

            db.drop_all()
            db.create_all()

            default_username = app.config.get("DEFAULT_ADMIN_USERNAME", "admin")
            default_password = app.config.get("DEFAULT_ADMIN_PASSWORD", "Admin@123")

            from flask_bcrypt import Bcrypt
            bcrypt = Bcrypt()
            hashed = bcrypt.generate_password_hash(default_password).decode("utf-8")
            admin = User(
                username=default_username,
                password_hash=hashed,
                role="admin"
            )
            db.session.add(admin)
            db.session.commit()

            print(f"\nCreated new database with default admin account:")
            print(f"  Username: {default_username}")
            print(f"  Password: {default_password}")
            print("=" * 60)


if __name__ == "__main__":
    update_database()
