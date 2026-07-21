#!/usr/bin/env python3
"""Migration: recurring_schedules, recurring_job_logs tables + contract_line_items patches."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from models.database import engine, Base
from sqlalchemy import text, inspect


def column_exists(conn, table, column):
    result = conn.execute(text(
        "SELECT COUNT(*) FROM pragma_table_info(:t) WHERE name=:c"
    ), {"t": table, "c": column})
    return result.scalar() > 0


def run_migration():
    import models.recurring_schedule  # noqa
    import models  # noqa

    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        insp = inspect(conn)
        tables = insp.get_table_names()

        for t in ('recurring_schedules', 'recurring_job_logs'):
            if t in tables:
                cols = [c['name'] for c in insp.get_columns(t)]
                print(f"  [OK] {t} ({len(cols)} columns)")
            else:
                print(f"  [MISSING] {t}")

        # Patch contract_line_items
        if 'contract_line_items' in tables:
            patches = [
                ('auto_generate_jobs', 'BOOLEAN NOT NULL DEFAULT 0'),
                ('advance_generation_days', 'INTEGER NOT NULL DEFAULT 14'),
                ('last_generated_job_id', 'INTEGER REFERENCES jobs(id)'),
                ('last_generated_date', 'DATE'),
            ]
            for col, definition in patches:
                if not column_exists(conn, 'contract_line_items', col):
                    conn.execute(text(
                        f"ALTER TABLE contract_line_items ADD COLUMN {col} {definition}"
                    ))
                    print(f"  [PATCHED] contract_line_items.{col}")
                else:
                    print(f"  [OK] contract_line_items.{col}")

    print("\nRecurring migration complete.")


if __name__ == '__main__':
    run_migration()
