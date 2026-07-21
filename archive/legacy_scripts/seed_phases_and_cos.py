#!/usr/bin/env python3
"""
seed_phases_and_cos.py
Seeds multi-phase jobs and change orders for development/demo.
Run: python seed_phases_and_cos.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta, datetime
from models.database import Base, engine, get_session
from models.user import Organization
from models.job import Job
from models.job_phase import JobPhase
from models.change_order import ChangeOrder, ChangeOrderLineItem
from models.division import Division


def seed():
    Base.metadata.create_all(engine)
    db = get_session()
    try:
        print("Seeding multi-phase jobs and change orders...\n")

        org = db.query(Organization).first()
        if not org:
            print("ERROR: No organization found. Register a user first.")
            return
        org_id = org.id

        division = db.query(Division).filter_by(organization_id=org_id).first()
        div_id = division.id if division else None

        today = date.today()

        # Find or create a suitable job
        job = db.query(Job).filter(
            Job.organization_id == org_id,
            Job.status.in_(['scheduled', 'in_progress'])
        ).first()

        if not job:
            print("  Creating demo multi-phase job...")
            job = Job(
                organization_id=org_id, division_id=div_id, client_id=1,
                title='Commercial HVAC System Replacement -- Building A',
                job_number='JOB-DEMO-001', status='in_progress',
                estimated_amount=85000.0, original_estimated_cost=85000.0,
                is_multi_phase=True,
                project_manager_notes='Multi-building HVAC replacement. Coordinate with building mgmt for access.',
            )
            db.add(job)
            db.flush()
        else:
            print(f"  Using existing job: {job.job_number}")

        job.is_multi_phase = True
        if job.original_estimated_cost is None:
            job.original_estimated_cost = float(job.estimated_amount or 0)

        # Remove existing phases/COs for this job (re-seed)
        db.query(ChangeOrderLineItem).filter(
            ChangeOrderLineItem.change_order_id.in_(
                db.query(ChangeOrder.id).filter_by(job_id=job.id)
            )
        ).delete(synchronize_session=False)
        db.query(ChangeOrder).filter_by(job_id=job.id).delete()
        db.query(JobPhase).filter_by(job_id=job.id).delete()
        db.flush()

        # Create 5 phases
        phases_data = [
            dict(phase_number=1, title='Phase 1: Site Assessment & Demo',
                 description='Complete site survey, remove existing units.',
                 status='completed',
                 scheduled_start_date=today - timedelta(days=30),
                 scheduled_end_date=today - timedelta(days=23),
                 actual_start_date=today - timedelta(days=30),
                 actual_end_date=today - timedelta(days=22),
                 estimated_hours=40, actual_hours=42.5,
                 estimated_cost=12000, actual_cost=12400,
                 sort_order=10,
                 completion_notes='Demo complete. Discovered asbestos on two units.'),
            dict(phase_number=2, title='Phase 2: Rough-In & Ductwork',
                 description='Install new duct runs and air handlers.',
                 status='completed',
                 scheduled_start_date=today - timedelta(days=20),
                 scheduled_end_date=today - timedelta(days=10),
                 actual_start_date=today - timedelta(days=19),
                 actual_end_date=today - timedelta(days=9),
                 estimated_hours=80, actual_hours=85,
                 estimated_cost=25000, actual_cost=26200,
                 sort_order=20,
                 requires_inspection=True, inspection_status='passed',
                 completion_notes='Ductwork complete. Passed mechanical inspection.'),
            dict(phase_number=3, title='Phase 3: Equipment Installation',
                 description='Install rooftop units, condensers, and split systems.',
                 status='in_progress',
                 scheduled_start_date=today - timedelta(days=7),
                 scheduled_end_date=today + timedelta(days=7),
                 actual_start_date=today - timedelta(days=6),
                 estimated_hours=60, actual_hours=28,
                 estimated_cost=35000, sort_order=30),
            dict(phase_number=4, title='Phase 4: Controls & Testing',
                 description='Install thermostats, BAS integration, commission units.',
                 status='scheduled',
                 scheduled_start_date=today + timedelta(days=8),
                 scheduled_end_date=today + timedelta(days=14),
                 estimated_hours=24, estimated_cost=8000, sort_order=40,
                 requires_inspection=True, inspection_status='not_required'),
            dict(phase_number=5, title='Phase 5: Final Inspection & Closeout',
                 description='Final city inspection, client training, documentation.',
                 status='not_started',
                 scheduled_start_date=today + timedelta(days=15),
                 scheduled_end_date=today + timedelta(days=17),
                 estimated_hours=8, estimated_cost=5000, sort_order=50,
                 requires_inspection=True, inspection_status='not_required'),
        ]

        for pd in phases_data:
            db.add(JobPhase(job_id=job.id, **pd))
        db.flush()
        print(f"  + 5 phases created")

        # Create 3 change orders
        # CO 1: Approved (asbestos removal)
        co1 = ChangeOrder(
            change_order_number=f'CO-{job.job_number}-01',
            job_id=job.id,
            title='Asbestos Abatement -- Units 3 & 4',
            description='Discovered asbestos insulation during demo. Requires certified specialist.',
            reason='unforeseen_condition', status='approved',
            requested_by='field_tech',
            requested_date=today - timedelta(days=28),
            cost_type='addition',
            original_amount=85000, revised_amount=88500,
            labor_hours_impact=0,
            requires_client_approval=True, client_approved=True,
            client_approved_by='John Smith (Facilities Manager)',
            client_approved_date=datetime.combine(today - timedelta(days=26), datetime.min.time()),
            internal_approved_date=datetime.combine(today - timedelta(days=26), datetime.min.time()),
        )
        db.add(co1)
        db.flush()
        db.add(ChangeOrderLineItem(change_order_id=co1.id, description='Asbestos specialist labor', quantity=1, unit_price=2800, is_addition=True))
        db.add(ChangeOrderLineItem(change_order_id=co1.id, description='Hazardous material disposal', quantity=1, unit_price=700, is_addition=True))

        # CO 2: Pending (additional unit)
        co2 = ChangeOrder(
            change_order_number=f'CO-{job.job_number}-02',
            job_id=job.id,
            title='Additional Split System -- Server Room',
            description='Client requested dedicated mini-split for server room.',
            reason='client_request', status='pending_approval',
            requested_by='client',
            requested_date=today - timedelta(days=5),
            cost_type='addition',
            original_amount=88500, revised_amount=93200,
            labor_hours_impact=16,
            requires_client_approval=True,
        )
        db.add(co2)
        db.flush()
        db.add(ChangeOrderLineItem(change_order_id=co2.id, description='Mitsubishi 2-ton mini-split', quantity=1, unit_price=3200, is_addition=True))
        db.add(ChangeOrderLineItem(change_order_id=co2.id, description='Installation labor', quantity=16, unit_price=95, is_addition=True))
        db.add(ChangeOrderLineItem(change_order_id=co2.id, description='Dedicated 30A circuit', quantity=1, unit_price=280, is_addition=True))

        # CO 3: Draft (scope reduction)
        co3 = ChangeOrder(
            change_order_number=f'CO-{job.job_number}-03',
            job_id=job.id,
            title='Remove BAS Integration -- Budget Constraint',
            description='Client deferring BAS integration to next year.',
            reason='client_request', status='draft',
            requested_by='project_manager',
            requested_date=today - timedelta(days=1),
            cost_type='deduction',
            original_amount=93200, revised_amount=90200,
            labor_hours_impact=-8,
            requires_client_approval=True,
        )
        db.add(co3)
        db.flush()
        db.add(ChangeOrderLineItem(change_order_id=co3.id, description='BAS integration (removed)', quantity=1, unit_price=3000, is_addition=False))

        # Update job cost from approved COs
        from web.utils.change_order_utils import apply_approved_change_order
        apply_approved_change_order(db, co1)

        db.commit()
        print(f"  + 3 change orders (1 approved, 1 pending, 1 draft)")
        print(f"\n  Job: {job.job_number} -- {job.title}")
        print(f"  Phases: 2 complete, 1 in progress, 1 scheduled, 1 not started")
        print(f"  URL: /jobs/{job.id}")
        print("\nSeed complete.")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    seed()
