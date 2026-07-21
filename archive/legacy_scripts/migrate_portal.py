#!/usr/bin/env python3
"""
migrate_portal.py — Creates all client portal tables and adds new Job columns.
Run: python migrate_portal.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import Base, engine
from models import (
    PortalUser, portal_user_properties,
    PortalMessage, PortalNotification,
    PortalSettings,
)
from sqlalchemy import inspect, text


def migrate():
    print("=== Client Portal Migration ===\n")

    # Create all new tables
    Base.metadata.create_all(engine)

    # Verify tables
    insp = inspect(engine)
    expected = [
        'portal_users', 'portal_user_properties',
        'portal_messages', 'portal_notifications',
        'portal_settings',
    ]
    existing = insp.get_table_names()
    for table in expected:
        status = 'OK' if table in existing else 'MISSING'
        print(f"  [{status}] {table}")

    # Check if new Job columns exist (SQLite ALTER TABLE)
    job_cols = {c['name'] for c in insp.get_columns('jobs')}
    new_cols = {
        'source': 'VARCHAR(30)',
        'portal_contact_name': 'VARCHAR(200)',
        'portal_contact_phone': 'VARCHAR(30)',
        'portal_access_instructions': 'TEXT',
    }
    with engine.connect() as conn:
        for col_name, col_type in new_cols.items():
            if col_name not in job_cols:
                try:
                    conn.execute(text(f'ALTER TABLE jobs ADD COLUMN {col_name} {col_type}'))
                    conn.commit()
                    print(f"  [ADDED] jobs.{col_name}")
                except Exception as e:
                    print(f"  [SKIP] jobs.{col_name} — {e}")
            else:
                print(f"  [OK] jobs.{col_name}")

    # Check for new Document column
    if 'documents' in existing:
        doc_cols = {c['name'] for c in insp.get_columns('documents')}
        if 'uploaded_by_portal_user_id' not in doc_cols:
            with engine.connect() as conn:
                try:
                    conn.execute(text('ALTER TABLE documents ADD COLUMN uploaded_by_portal_user_id INTEGER REFERENCES portal_users(id)'))
                    conn.commit()
                    print("  [ADDED] documents.uploaded_by_portal_user_id")
                except Exception as e:
                    print(f"  [SKIP] documents.uploaded_by_portal_user_id — {e}")
        else:
            print("  [OK] documents.uploaded_by_portal_user_id")

    # Check for new Quote columns
    if 'quotes' in existing:
        quote_cols = {c['name'] for c in insp.get_columns('quotes')}
        quote_new = {
            'portal_approved_by': 'INTEGER REFERENCES portal_users(id)',
            'portal_approved_at': 'DATETIME',
            'portal_approval_note': 'TEXT',
        }
        with engine.connect() as conn:
            for col_name, col_type in quote_new.items():
                if col_name not in quote_cols:
                    try:
                        conn.execute(text(f'ALTER TABLE quotes ADD COLUMN {col_name} {col_type}'))
                        conn.commit()
                        print(f"  [ADDED] quotes.{col_name}")
                    except Exception as e:
                        print(f"  [SKIP] quotes.{col_name} — {e}")
                else:
                    print(f"  [OK] quotes.{col_name}")

    # Check for new ChangeOrder columns
    if 'change_orders' in existing:
        co_cols = {c['name'] for c in insp.get_columns('change_orders')}
        co_new = {
            'client_approved_by_portal_id': 'INTEGER REFERENCES portal_users(id)',
            'client_rejection_reason': 'TEXT',
        }
        with engine.connect() as conn:
            for col_name, col_type in co_new.items():
                if col_name not in co_cols:
                    try:
                        conn.execute(text(f'ALTER TABLE change_orders ADD COLUMN {col_name} {col_type}'))
                        conn.commit()
                        print(f"  [ADDED] change_orders.{col_name}")
                    except Exception as e:
                        print(f"  [SKIP] change_orders.{col_name} — {e}")
                else:
                    print(f"  [OK] change_orders.{col_name}")

    # Ensure default portal_settings row exists
    from models.database import get_session
    db = get_session()
    try:
        if not db.query(PortalSettings).first():
            db.add(PortalSettings())
            db.commit()
            print("  [CREATED] Default portal_settings row")
        else:
            print("  [OK] portal_settings row exists")
    finally:
        db.close()

    print("\nPortal migration complete.")


if __name__ == '__main__':
    migrate()
