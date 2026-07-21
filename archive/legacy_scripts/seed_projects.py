#!/usr/bin/env python3
"""
seed_projects.py — Create demo projects and link existing jobs.
Run: python seed_projects.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta
from models.database import get_session, Base, engine
from models import Project, ProjectNote, Job, Client, User, Technician, Division, Contract


def seed():
    Base.metadata.create_all(engine)
    db = get_session()
    try:
        if db.query(Project).count() > 0:
            print("Projects already exist — skipping seed.")
            return

        org = db.query(User).first()
        if not org:
            print("No users found.")
            return
        org_id = org.organization_id
        user_id = org.id

        tech = db.query(Technician).first()
        div = db.query(Division).first()
        today = date.today()

        print("=== Seeding Projects ===\n")

        # Project 1: Perimeter Development
        c1 = db.query(Client).filter(Client.company_name.ilike('%Perimeter%')).first()
        if not c1:
            c1 = db.query(Client).filter_by(client_type='commercial').first()
        if c1:
            p1 = Project(
                organization_id=org_id,
                project_number='PRJ-2026-0001',
                title='Grand Flats Phase 2 — Units 301-310',
                description='Complete plumbing, HVAC, and electrical for 10 residential units.',
                client_id=c1.id, division_id=div.id if div else None,
                status='active', priority='high',
                estimated_start_date=today - timedelta(days=75),
                estimated_end_date=today + timedelta(days=90),
                actual_start_date=today - timedelta(days=70),
                estimated_budget=65000, approved_budget=65000,
                percent_complete=60,
                project_manager_id=user_id,
                site_supervisor_id=tech.id if tech else None,
                client_contact_name='Marcus Chen', client_contact_phone='519-555-0101',
                created_by=user_id,
            )
            db.add(p1)
            db.flush()
            for num in range(30, 35):
                j = db.query(Job).filter_by(job_number=f'JOB-{num:05d}').first()
                if j:
                    j.project_id = p1.id
                    print(f"  Linked JOB-{num:05d} to PRJ-2026-0001")
            db.add(ProjectNote(project_id=p1.id, content='Kickoff meeting held. All trades confirmed.', note_type='meeting', created_by=user_id))
            print("  + PRJ-2026-0001: Grand Flats Phase 2")

        # Project 2: Catalyst137
        c2 = db.query(Client).filter(Client.company_name.ilike('%Catalyst%')).first()
        if c2:
            p2 = Project(
                organization_id=org_id,
                project_number='PRJ-2026-0002',
                title='Catalyst137 Facility Upgrades',
                description='HVAC replacement, plumbing modernization, panel upgrades.',
                client_id=c2.id, division_id=div.id if div else None,
                status='active', priority='medium',
                estimated_start_date=today - timedelta(days=60),
                estimated_end_date=today + timedelta(days=45),
                actual_start_date=today - timedelta(days=55),
                estimated_budget=25000, approved_budget=25000,
                percent_complete=40,
                project_manager_id=user_id,
                client_contact_name='Sarah Kim', client_contact_phone='519-555-0202',
                created_by=user_id,
            )
            db.add(p2)
            db.flush()
            for num in range(40, 43):
                j = db.query(Job).filter_by(job_number=f'JOB-{num:05d}').first()
                if j:
                    j.project_id = p2.id
                    print(f"  Linked JOB-{num:05d} to PRJ-2026-0002")
            db.add(ProjectNote(project_id=p2.id, content='Equipment delivery confirmed. Electrical rough-in starting.', note_type='general', created_by=user_id))
            print("  + PRJ-2026-0002: Catalyst137 Facility Upgrades")

        # Project 3: Schlegel Villages
        c3 = db.query(Client).filter(Client.company_name.ilike('%Schlegel%')).first()
        contract = db.query(Contract).filter_by(client_id=c3.id).first() if c3 else None
        if c3:
            p3 = Project(
                organization_id=org_id,
                project_number='PRJ-2026-0003',
                title='Winston Park Systems Overhaul',
                description='Boiler replacement, hot water upgrades, bathroom renovations in 40 suites.',
                client_id=c3.id, division_id=div.id if div else None,
                status='planning', priority='medium',
                estimated_start_date=today + timedelta(days=15),
                estimated_end_date=today + timedelta(days=180),
                estimated_budget=45000, approved_budget=45000,
                percent_complete=20,
                project_manager_id=user_id,
                contract_id=contract.id if contract else None,
                client_contact_name='Tom Reeves', client_contact_phone='519-555-0303',
                created_by=user_id,
            )
            db.add(p3)
            db.flush()
            for num in range(25, 30):
                j = db.query(Job).filter_by(job_number=f'JOB-{num:05d}').first()
                if j:
                    j.project_id = p3.id
                    print(f"  Linked JOB-{num:05d} to PRJ-2026-0003")
            db.add(ProjectNote(project_id=p3.id, content='Engineering assessment completed. Scope finalized.', note_type='general', created_by=user_id))
            print("  + PRJ-2026-0003: Winston Park Systems Overhaul")

        db.commit()
        print("\n=== Project Seed Complete ===")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    seed()
