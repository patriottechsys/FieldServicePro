#!/usr/bin/env python3
"""
migrate_compliance.py — Creates all compliance module tables.
Run: python migrate_compliance.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import Base, engine
from models import (
    Document, Permit, InsurancePolicy,
    TechnicianCertification, JobCertificationRequirement,
    ChecklistTemplate, ChecklistItem, CompletedChecklist, CompletedChecklistItem,
    LienWaiver,
)
from sqlalchemy import inspect


def migrate():
    print("=== Compliance & Documentation Module Migration ===\n")
    Base.metadata.create_all(engine)

    insp = inspect(engine)
    expected = [
        'documents', 'permits', 'insurance_policies',
        'technician_certifications', 'job_certification_requirements',
        'checklist_templates', 'checklist_items',
        'completed_checklists', 'completed_checklist_items',
        'lien_waivers',
    ]
    existing = insp.get_table_names()
    for table in expected:
        if table in existing:
            cols = [c['name'] for c in insp.get_columns(table)]
            print(f"+ {table}: {len(cols)} columns")
        else:
            print(f"ERROR: {table} not created")

    print("\nMigration complete.")


if __name__ == '__main__':
    migrate()
