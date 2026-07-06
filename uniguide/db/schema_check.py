"""Fail loudly at startup if the DB hasn't had every Alembic migration
applied, instead of discovering it later as a confusing 500 mid-request
(e.g. "no such column: planned_courses.mandatory").

init_db()'s Base.metadata.create_all() only adds brand-new tables — it
never alters existing ones — so a DB created before a schema change (a new
column, a new table) silently keeps its old shape until `alembic upgrade
head` is actually run against it.

Deliberately does not go through alembic.ini/Config: script_location in that
file is relative, and resolves against the process's current working
directory rather than the ini's own location — which differs depending on
whether you're running uvicorn (repo root) or invoking alembic directly
(uniguide/), the same landmine DATABASE_URL/GOOGLE_SERVICE_ACCOUNT_FILE hit
earlier. Building ScriptDirectory from an absolute path sidesteps that.
"""

from pathlib import Path

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect as sa_inspect

from uniguide.db.database import engine

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class SchemaOutOfDateError(RuntimeError):
    pass


def check_schema_up_to_date() -> None:
    """Raises SchemaOutOfDateError if the live DB isn't at the latest
    migration head. Call this once at process startup, after init_db().
    """
    script = ScriptDirectory(str(MIGRATIONS_DIR))
    head = script.get_current_head()

    inspector = sa_inspect(engine)
    existing_tables = inspector.get_table_names()

    if "alembic_version" not in existing_tables:
        if existing_tables:
            raise SchemaOutOfDateError(
                "Database has tables but was never stamped with an Alembic "
                "revision. Run `alembic stamp <revision>` (if the tables "
                "already match a known migration) or `alembic upgrade head` "
                "from uniguide/ before starting."
            )
        # A genuinely brand-new DB with no tables at all yet is fine —
        # init_db() just created it from the current models.
        return

    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()

    if current != head:
        raise SchemaOutOfDateError(
            f"Database schema is out of date (at revision {current!r}, "
            f"latest is {head!r}). Run `alembic upgrade head` from "
            "uniguide/ before starting."
        )
