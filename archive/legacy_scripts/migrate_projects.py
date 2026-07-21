#!/usr/bin/env python3
"""
migrate_projects.py — Creates project tables and adds project_id to related models.
Run: python migrate_projects.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import Base, engine
from models import Project, ProjectNote
from sqlalchemy import inspect, text


def migrate():
    print("=== Project Management Migration ===\n")

    Base.metadata.create_all(engine)

    insp = inspect(engine)
    existing = insp.get_table_names()

    for table in ['projects', 'project_notes']:
        status = 'OK' if table in existing else 'MISSING'
        print(f"  [{status}] {table}")

    # Add project_id columns to existing tables
    tables_needing_project_id = ['jobs', 'invoices', 'purchase_orders', 'permits', 'documents']
    with engine.connect() as conn:
        for table in tables_needing_project_id:
            if table in existing:
                cols = {c['name'] for c in insp.get_columns(table)}
                if 'project_id' not in cols:
                    try:
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN project_id INTEGER REFERENCES projects(id)'))
                        conn.commit()
                        print(f"  [ADDED] {table}.project_id")
                    except Exception as e:
                        print(f"  [SKIP] {table}.project_id — {e}")
                else:
                    print(f"  [OK] {table}.project_id")

    print("\nProject migration complete.")


if __name__ == '__main__':
    migrate()
