#!/usr/bin/env python3
"""Migration: Communication Log tables."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from models.database import engine, Base
from sqlalchemy import text, inspect
import models.communication  # noqa


def column_exists(conn, table, column):
    result = conn.execute(text(
        "SELECT COUNT(*) FROM pragma_table_info(:t) WHERE name=:c"
    ), {"t": table, "c": column})
    return result.scalar() > 0


def run_migration():
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        insp = inspect(conn)
        tables = insp.get_table_names()

        for t in ('communication_logs', 'communication_templates'):
            if t in tables:
                cols = [c['name'] for c in insp.get_columns(t)]
                print(f"  [OK] {t} ({len(cols)} columns)")
            else:
                print(f"  [MISSING] {t}")

        if 'organization_settings' in tables:
            for col, defn in [
                ('inactive_client_alert_days', 'INTEGER DEFAULT 7'),
                ('default_follow_up_days', 'INTEGER DEFAULT 3'),
                ('require_comm_log_on_status_change', 'BOOLEAN DEFAULT 0'),
            ]:
                if not column_exists(conn, 'organization_settings', col):
                    conn.execute(text(f"ALTER TABLE organization_settings ADD COLUMN {col} {defn}"))
                    print(f"  [PATCHED] organization_settings.{col}")

    print("\nCommunication Log migration complete.")


if __name__ == '__main__':
    run_migration()
