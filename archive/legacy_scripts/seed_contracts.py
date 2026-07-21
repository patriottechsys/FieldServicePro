#!/usr/bin/env python3
"""
seed_contracts.py
Creates test SLAs, contracts, line items, and linked jobs for development.
Run: python seed_contracts.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta, datetime
from models.database import get_session
from models.user import Organization
from models.sla import SLA, PriorityLevel
from models.contract import (
    Contract, ContractLineItem, ContractActivityLog,
    ContractStatus, ContractType, BillingFrequency, ServiceFrequency
)
from models.client import Client
from models.division import Division
from models.job import Job


def seed():
    db = get_session()
    try:
        # Get the first organization (required for all records)
        org = db.query(Organization).first()
        if not org:
            print("ERROR: No organization found. Register a user first.")
            return
        org_id = org.id
        print(f"Using organization: {org.name} (id={org_id})")

        # Get a division for jobs
        division = db.query(Division).filter_by(organization_id=org_id).first()
        division_id = division.id if division else None
        if division:
            print(f"Using division: {division.name}")

        # ── SLA Templates ──
        print("\nSeeding SLA templates...")
        sla_defs = [
            dict(
                sla_name='24/7 Emergency Response',
                priority_level=PriorityLevel.emergency,
                response_time_hours=1.0,
                resolution_time_hours=4.0,
                business_hours_only=False,
                business_hours_start='00:00',
                business_hours_end='23:59',
                business_days='mon,tue,wed,thu,fri,sat,sun',
                penalties='Credit of 10% contract value per breach',
                is_active=True,
            ),
            dict(
                sla_name='Priority 4-Hour Response',
                priority_level=PriorityLevel.high,
                response_time_hours=4.0,
                resolution_time_hours=24.0,
                business_hours_only=True,
                business_hours_start='07:00',
                business_hours_end='18:00',
                business_days='mon,tue,wed,thu,fri,sat',
                penalties='Credit of 5% next invoice',
                is_active=True,
            ),
            dict(
                sla_name='Standard Next Business Day',
                priority_level=PriorityLevel.medium,
                response_time_hours=8.0,
                resolution_time_hours=48.0,
                business_hours_only=True,
                business_hours_start='08:00',
                business_hours_end='17:00',
                business_days='mon,tue,wed,thu,fri',
                penalties=None,
                is_active=True,
            ),
            dict(
                sla_name='Low Priority -- 3 Business Days',
                priority_level=PriorityLevel.low,
                response_time_hours=24.0,
                resolution_time_hours=72.0,
                business_hours_only=True,
                business_hours_start='08:00',
                business_hours_end='17:00',
                business_days='mon,tue,wed,thu,fri',
                penalties=None,
                is_active=True,
            ),
        ]
        sla_count = 0
        for s_def in sla_defs:
            existing = db.query(SLA).filter_by(sla_name=s_def['sla_name']).first()
            if not existing:
                db.add(SLA(**s_def))
                sla_count += 1
        db.flush()
        db.commit()
        print(f"  + {sla_count} SLA templates seeded")

        # Fetch SLAs for assignment
        emergency_sla = db.query(SLA).filter_by(priority_level=PriorityLevel.emergency).first()
        high_sla = db.query(SLA).filter_by(priority_level=PriorityLevel.high).first()
        medium_sla = db.query(SLA).filter_by(priority_level=PriorityLevel.medium).first()
        low_sla = db.query(SLA).filter_by(priority_level=PriorityLevel.low).first()

        # ── Clients ──
        print("\nLooking for clients...")
        clients = db.query(Client).filter_by(
            organization_id=org_id, is_active=True
        ).limit(3).all()

        if not clients:
            print("  No clients found. Creating test clients...")
            for i in range(1, 4):
                c = Client(
                    organization_id=org_id,
                    client_type='commercial',
                    company_name=f'TestCo Commercial {i}',
                    first_name=f'Contact{i}',
                    last_name='Person',
                    email=f'testco{i}@example.com',
                    phone=f'555-010{i}',
                )
                db.add(c)
            db.flush()
            db.commit()
            clients = db.query(Client).filter_by(
                organization_id=org_id, is_active=True
            ).limit(3).all()
            print(f"  + Created {len(clients)} test clients")
        else:
            print(f"  Found {len(clients)} existing clients")

        # ── Contracts ──
        print("\nSeeding contracts...")
        today = date.today()
        created = 0

        # Contract 1: Active HVAC Maintenance
        client1 = clients[0]
        if not db.query(Contract).filter_by(client_id=client1.id).first():
            c1 = Contract(
                organization_id=org_id,
                contract_number=Contract.generate_contract_number(db),
                client_id=client1.id,
                division_id=division_id,
                title='Annual HVAC Maintenance Agreement',
                description='Full preventive maintenance for all HVAC units',
                contract_type=ContractType.preventive_maintenance,
                status=ContractStatus.active,
                start_date=today - timedelta(days=90),
                end_date=today + timedelta(days=275),
                value=24000.00,
                billing_frequency=BillingFrequency.monthly,
                auto_renew=True,
                renewal_reminder_days=45,
                renewal_terms='Automatic renewal at same rate + 3% CPI adjustment',
                terms_and_conditions='Standard commercial HVAC service terms apply.',
                internal_notes='Key contact: Jane Smith, Facilities Manager',
            )
            c1.slas = [s for s in [emergency_sla, high_sla, medium_sla] if s]
            db.add(c1)
            db.flush()

            # Line items
            for li_data in [
                dict(service_type='Quarterly Filter Replacement',
                     description='Replace all HVAC filters per manufacturer spec',
                     frequency=ServiceFrequency.quarterly, quantity=4,
                     unit_price=850.00, estimated_hours_per_visit=3.0,
                     next_scheduled_date=today + timedelta(days=30),
                     is_included=True, sort_order=0),
                dict(service_type='Annual System Inspection',
                     description='Full inspection of all HVAC equipment',
                     frequency=ServiceFrequency.annual, quantity=1,
                     unit_price=1200.00, estimated_hours_per_visit=8.0,
                     next_scheduled_date=today + timedelta(days=180),
                     is_included=True, sort_order=1),
                dict(service_type='Emergency Repair',
                     description='Emergency service calls (up to 4 per year)',
                     frequency=ServiceFrequency.one_time, quantity=4,
                     unit_price=0.00, estimated_hours_per_visit=None,
                     next_scheduled_date=None, is_included=True, sort_order=2),
            ]:
                db.add(ContractLineItem(contract_id=c1.id, **li_data))

            c1.log_activity(db, None, 'Contract created (seeded)',
                            'Initial seed data for development')
            created += 1

        # Contract 2: Expiring soon (for dashboard widget testing)
        if len(clients) > 1:
            client2 = clients[1]
            if not db.query(Contract).filter_by(client_id=client2.id).first():
                c2 = Contract(
                    organization_id=org_id,
                    contract_number=Contract.generate_contract_number(db),
                    client_id=client2.id,
                    division_id=division_id,
                    title='Plumbing Services Agreement -- 3 Locations',
                    description='Preventive maintenance and on-demand plumbing',
                    contract_type=ContractType.full_service,
                    status=ContractStatus.active,
                    start_date=today - timedelta(days=335),
                    end_date=today + timedelta(days=20),  # expiring soon!
                    value=18500.00,
                    billing_frequency=BillingFrequency.quarterly,
                    auto_renew=False,
                    renewal_reminder_days=30,
                    internal_notes='Client has been with us 3 years. Good candidate for renewal.',
                )
                c2.slas = [s for s in [high_sla, medium_sla, low_sla] if s]
                db.add(c2)
                db.flush()
                c2.log_activity(db, None, 'Contract created (seeded)')
                created += 1

        # Contract 3: Draft -- pending approval
        if len(clients) > 2:
            client3 = clients[2]
            if not db.query(Contract).filter_by(client_id=client3.id).first():
                c3 = Contract(
                    organization_id=org_id,
                    contract_number=Contract.generate_contract_number(db),
                    client_id=client3.id,
                    division_id=division_id,
                    title='Electrical Safety Inspection Program',
                    description='Annual electrical inspections and minor repair',
                    contract_type=ContractType.on_demand,
                    status=ContractStatus.pending_approval,
                    start_date=today + timedelta(days=30),
                    end_date=today + timedelta(days=395),
                    value=9800.00,
                    billing_frequency=BillingFrequency.annual,
                    auto_renew=False,
                    renewal_reminder_days=30,
                )
                c3.slas = [s for s in [medium_sla, low_sla] if s]
                db.add(c3)
                db.flush()
                c3.log_activity(db, None, 'Contract created (seeded)')
                created += 1

        db.commit()
        print(f"  + {created} contracts seeded")

        # ── Jobs with SLA tracking ──
        print("\nSeeding jobs with SLA tracking...")
        active_contracts = db.query(Contract)\
                             .filter(Contract.status == ContractStatus.active)\
                             .all()
        jobs_created = 0
        for contract in active_contracts:
            existing_jobs = db.query(Job).filter_by(contract_id=contract.id).count()
            if existing_jobs > 0:
                continue

            sla = contract.slas[0] if contract.slas else None

            # Job created 3 hours ago (may be at-risk depending on SLA)
            created_3h_ago = datetime.utcnow() - timedelta(hours=3)
            j = Job(
                organization_id=org_id,
                division_id=division_id or 1,
                client_id=contract.client_id,
                contract_id=contract.id,
                job_number=f'JOB-SEED-{contract.id:03d}',
                title=f'Test Job -- {contract.title[:30]}',
                description='Auto-created seed job for SLA testing',
                status='scheduled',
                priority='high',
                job_type='maintenance',
                created_at=created_3h_ago,
            )
            if sla:
                j.sla_id = sla.id
                j.sla_response_deadline = sla.calculate_deadline(
                    created_3h_ago, sla.response_time_hours)
                if sla.resolution_time_hours:
                    j.sla_resolution_deadline = sla.calculate_deadline(
                        created_3h_ago, sla.resolution_time_hours)
            db.add(j)
            jobs_created += 1

        db.commit()
        print(f"  + {jobs_created} test jobs seeded")
        print("\nSeed data complete. Open /contracts to verify.")

    except Exception as e:
        db.rollback()
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    seed()
