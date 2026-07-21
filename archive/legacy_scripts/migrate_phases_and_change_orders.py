#!/usr/bin/env python3
"""
Migration: Add multi-phase job support and change orders.
Run once: python migrate_phases_and_change_orders.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import Base, engine
from models import JobPhase, ChangeOrder, ChangeOrderLineItem
from sqlalchemy import text, inspect


def migrate():
    print("=== Migration: Phases and Change Orders ===\n")

    # Create all tables via SQLAlchemy metadata (safe, won't drop existing)
    Base.metadata.create_all(engine)

    insp = inspect(engine)
    existing_tables = insp.get_table_names()

    for table in ['job_phases', 'change_orders', 'change_order_line_items']:
        if table in existing_tables:
            cols = [c['name'] for c in insp.get_columns(table)]
            print(f"  + {table}: {len(cols)} columns")
        else:
            print(f"  ERROR: {table} not created")

    # Add new columns to jobs table
    print("\nPatching jobs table with phase/CO columns...")
    jobs_columns = {c['name'] for c in insp.get_columns('jobs')}

    new_job_cols = [
        ('is_multi_phase', 'BOOLEAN DEFAULT 0'),
        ('original_estimated_cost', 'REAL'),
        ('adjusted_estimated_cost', 'REAL'),
        ('project_manager_notes', 'TEXT'),
    ]

    with engine.connect() as conn:
        for col_name, col_def in new_job_cols:
            if col_name not in jobs_columns:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def}"))
                print(f"  + jobs.{col_name} added")
            else:
                print(f"  - jobs.{col_name} already exists")
        conn.commit()

    print("\nMigration complete.")


if __name__ == '__main__':
    migrate()
