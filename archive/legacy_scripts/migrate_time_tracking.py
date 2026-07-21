#!/usr/bin/env python3
"""Migration: Create time tracking tables and add related columns."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import inspect, text
from models.database import engine, Base
from models.time_entry import TimeEntry, ActiveClock


def migrate():
    print("=== Time Tracking Migration ===\n")
    Base.metadata.create_all(engine)

    insp = inspect(engine)
    existing = insp.get_table_names()

    for table in ['time_entries', 'active_clocks']:
        status = 'OK' if table in existing else 'MISSING'
        print(f"  [{status}] {table}")

    # Add billable_rate to technicians if missing
    if 'technicians' in existing:
        tech_cols = {c['name'] for c in insp.get_columns('technicians')}
        with engine.connect() as conn:
            if 'billable_rate' not in tech_cols:
                try:
                    conn.execute(text("ALTER TABLE technicians ADD COLUMN billable_rate FLOAT DEFAULT 95.0"))
                    conn.commit()
                    print("  [ADDED] technicians.billable_rate")
                except Exception as e:
                    print(f"  [SKIP] technicians.billable_rate — {e}")
            else:
                print("  [OK] technicians.billable_rate")

    # Add actual_labor_cost to jobs if missing
    if 'jobs' in existing:
        job_cols = {c['name'] for c in insp.get_columns('jobs')}
        with engine.connect() as conn:
            for col, coltype in [('actual_labor_cost', 'FLOAT DEFAULT 0'), ('actual_hours', 'FLOAT DEFAULT 0')]:
                if col not in job_cols:
                    try:
                        conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col} {coltype}"))
                        conn.commit()
                        print(f"  [ADDED] jobs.{col}")
                    except Exception as e:
                        print(f"  [SKIP] jobs.{col} — {e}")
                else:
                    print(f"  [OK] jobs.{col}")

    print("\nTime tracking migration complete.")


if __name__ == '__main__':
    migrate()
