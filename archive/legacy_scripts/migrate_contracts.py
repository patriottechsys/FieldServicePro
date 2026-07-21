#!/usr/bin/env python3
"""
migrate_contracts.py
Run once: python migrate_contracts.py
Creates all new tables and adds new columns to existing tables.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import Base, engine
from models import (
    Contract, ContractLineItem, ContractActivityLog,
    ContractAttachment, SLA,
    contract_property, contract_sla
)

# Import Job so SQLAlchemy sees its updated definition
from models.job import Job  # noqa: F401


def run_migration():
    print("Running Contracts & SLA migration...")

    # Create all new tables (safe - won't drop existing)
    Base.metadata.create_all(engine)
    print("  + Tables created: contracts, contract_line_items, contract_activity_logs,")
    print("    contract_attachments, slas, contract_property, contract_sla")

    # Add new columns to jobs table via raw SQL (SQLite-safe alter table)
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    existing_cols = {c['name'] for c in insp.get_columns('jobs')}

    new_job_cols = [
        ("contract_id",             "INTEGER REFERENCES contracts(id)"),
        ("sla_id",                  "INTEGER REFERENCES slas(id)"),
        ("sla_response_deadline",   "DATETIME"),
        ("sla_resolution_deadline", "DATETIME"),
        ("actual_response_time",    "DATETIME"),
        ("actual_resolution_time",  "DATETIME"),
        ("sla_response_met",        "BOOLEAN"),
        ("sla_resolution_met",      "BOOLEAN"),
    ]

    with engine.connect() as conn:
        for col_name, col_def in new_job_cols:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def}"))
                print(f"  + Added jobs.{col_name}")
            else:
                print(f"  - jobs.{col_name} already exists, skipping")
        conn.commit()

    print("\nMigration complete.")


if __name__ == '__main__':
    run_migration()
