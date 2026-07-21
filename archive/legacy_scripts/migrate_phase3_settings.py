#!/usr/bin/env python3
"""
migrate_phase3_settings.py
Creates the organization_settings table and seeds a default row.
Run: python migrate_phase3_settings.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import Base, engine, get_session
from models.settings import OrganizationSettings
from models.user import Organization


def migrate():
    print("=== Phase 3: Organization Settings Migration ===\n")

    # Create all tables (safe, won't drop existing)
    Base.metadata.create_all(engine)
    print("+ organization_settings table ensured")

    # Seed default settings for each organization
    db = get_session()
    try:
        orgs = db.query(Organization).all()
        for org in orgs:
            existing = db.query(OrganizationSettings).filter_by(
                organization_id=org.id
            ).first()
            if not existing:
                settings = OrganizationSettings(
                    organization_id=org.id,
                    invoice_approval_enabled=False,
                    invoice_approval_roles='owner,admin',
                    default_late_fee_rate=1.5,
                    late_fee_grace_days=0,
                    invoice_number_prefix='INV',
                    statement_footer_text='Thank you for your business. Please remit payment by the due date.',
                )
                db.add(settings)
                print(f"  + Created settings for org: {org.name}")
            else:
                print(f"  - Settings already exist for org: {org.name}")
        db.commit()
    finally:
        db.close()

    print("\nMigration complete.")


if __name__ == '__main__':
    migrate()
