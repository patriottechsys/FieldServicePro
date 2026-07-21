#!/usr/bin/env python3
"""Migration: Warranty and Callback tracking tables + column patches."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from models.database import engine, Base
from sqlalchemy import text, inspect
import models.warranty, models.callback  # noqa


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

        for t in ('warranties', 'warranty_claims', 'callbacks'):
            if t in tables:
                cols = [c['name'] for c in insp.get_columns(t)]
                print(f"  [OK] {t} ({len(cols)} columns)")
            else:
                print(f"  [MISSING] {t}")

        # Patch jobs table
        print("Patching jobs table...")
        for col, defn in [
            ('is_callback', 'BOOLEAN NOT NULL DEFAULT 0'),
            ('is_warranty_work', 'BOOLEAN NOT NULL DEFAULT 0'),
            ('original_job_id', 'INTEGER REFERENCES jobs(id)'),
        ]:
            if not column_exists(conn, 'jobs', col):
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col} {defn}"))
                print(f"  [PATCHED] jobs.{col}")
            else:
                print(f"  [OK] jobs.{col}")

        # Patch time_entries
        print("Patching time_entries table...")
        if not column_exists(conn, 'time_entries', 'is_warranty_work'):
            conn.execute(text("ALTER TABLE time_entries ADD COLUMN is_warranty_work BOOLEAN NOT NULL DEFAULT 0"))
            print("  [PATCHED] time_entries.is_warranty_work")
        else:
            print("  [OK] time_entries.is_warranty_work")

        # Patch organization_settings
        if 'organization_settings' in tables:
            print("Patching organization_settings...")
            for col, defn in [
                ('default_labor_warranty_months', 'INTEGER NOT NULL DEFAULT 12'),
                ('default_parts_warranty_months', 'INTEGER NOT NULL DEFAULT 12'),
                ('default_max_claim_value', 'NUMERIC(10,2)'),
                ('callback_lookback_days', 'INTEGER NOT NULL DEFAULT 90'),
                ('callback_rate_threshold', 'NUMERIC(5,2) NOT NULL DEFAULT 5.0'),
                ('auto_create_warranty_on_completion', 'BOOLEAN NOT NULL DEFAULT 0'),
                ('default_warranty_terms', 'TEXT'),
            ]:
                if not column_exists(conn, 'organization_settings', col):
                    conn.execute(text(f"ALTER TABLE organization_settings ADD COLUMN {col} {defn}"))
                    print(f"  [PATCHED] organization_settings.{col}")

    print("\nWarranty migration complete.")


if __name__ == '__main__':
    run_migration()
