"""
Bring an OLD local SQLite database up to the current models by adding any
columns the models define but the database lacks.

Usage (from the project folder, venv active):
    python fix_local_db.py                 # uses assessment.db / instance/assessment.db
    python fix_local_db.py path\to\file.db

Only ADDs missing columns (and creates missing tables). It never drops or
rewrites data, and it saves a timestamped backup first. SQLite only.
"""
import os, shutil, sys, time
from sqlalchemy import create_engine, inspect, Boolean, Integer, Float, Numeric
from sqlalchemy.schema import CreateTable


def _default_sql(col):
    """A literal DEFAULT so NOT NULL columns can be added to tables with rows."""
    d = col.default.arg if col.default is not None and getattr(col.default, "is_scalar", False) else None
    if d is None and col.server_default is not None:
        return str(col.server_default.arg.text if hasattr(col.server_default.arg, "text") else col.server_default.arg)
    if d is None:
        if col.nullable:
            return None
        # Sensible neutral defaults; credentials_enabled must be TRUE or
        # existing accounts would be locked out.
        if col.name == "credentials_enabled":
            return "1"
        if isinstance(col.type, (Boolean, Integer, Float, Numeric)):
            return "0"
        return "''"
    if isinstance(d, bool):
        return "1" if d else "0"
    if isinstance(d, (int, float)):
        return str(d)
    return "'" + str(d).replace("'", "''") + "'"


def repair(engine, metadata):
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    added = []
    with engine.begin() as cx:
        for table in metadata.sorted_tables:
            if table.name not in existing:
                cx.exec_driver_sql(str(CreateTable(table).compile(engine)))
                added.append((table.name, "(whole table)"))
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                dflt = _default_sql(col)
                if dflt is not None:
                    ddl += f" DEFAULT {dflt}"
                if not col.nullable and dflt is not None:
                    ddl += " NOT NULL"
                cx.exec_driver_sql(ddl)
                added.append((table.name, col.name))
    return added


if __name__ == "__main__":
    here = os.getcwd()
    sys.path.insert(0, here)
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    candidates = [arg] if arg else [
        os.path.join(here, "assessment.db"),
        os.path.join(here, "instance", "assessment.db"),
    ]
    path = next((p for p in candidates if p and os.path.exists(p)), None)
    if not path:
        sys.exit("Database file not found. Pass its path: python fix_local_db.py path\\to\\assessment.db")
    backup = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup)
    print("Backup saved:", backup)

    os.environ["FLASK_ENV"] = "development"
    os.environ.pop("DATABASE_URL", None)          # never touch a remote DB from this script
    os.environ["EDUASSESS_MIGRATION_MODE"] = "1"  # avoid bootstrapping the old database before repairing it
    from db import db
    import app as app_module                      # registers every model on db.metadata
    added = repair(create_engine(f"sqlite:///{os.path.abspath(path)}"), db.metadata)
    print("Added:" if added else "Nothing to add - schema already matches.")
    for t, c in added:
        print(f"  {t}.{c}")
