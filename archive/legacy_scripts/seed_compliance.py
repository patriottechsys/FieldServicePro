#!/usr/bin/env python3
"""
seed_compliance.py — Seed data for Compliance and Documentation module.
Run: python seed_compliance.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta
from models.database import get_session, Base, engine
from models import (
    Job, Technician,
    Permit, InsurancePolicy,
    TechnicianCertification, JobCertificationRequirement,
    ChecklistTemplate, ChecklistItem,
    LienWaiver,
)


def seed():
    # Ensure tables exist
    Base.metadata.create_all(engine)

    db = get_session()
    try:
        print("=== Seeding Compliance Data ===\n")

        # ---- Permits ----
        jobs = db.query(Job).limit(3).all()
        if jobs:
            permits_data = [
                {
                    'permit_number': 'BP-2024-00451',
                    'job_id': jobs[0].id,
                    'permit_type': 'building',
                    'description': 'Building permit for commercial renovation',
                    'issuing_authority': 'City Building Department',
                    'status': 'active',
                    'application_date': date.today() - timedelta(days=30),
                    'issue_date': date.today() - timedelta(days=20),
                    'expiry_date': date.today() + timedelta(days=180),
                    'cost': 450.00,
                },
                {
                    'permit_number': 'EP-2024-00892',
                    'job_id': jobs[0].id,
                    'permit_type': 'electrical',
                    'description': 'Electrical permit for panel upgrade',
                    'issuing_authority': 'Electrical Safety Authority',
                    'status': 'inspection_required',
                    'application_date': date.today() - timedelta(days=25),
                    'issue_date': date.today() - timedelta(days=15),
                    'expiry_date': date.today() + timedelta(days=90),
                    'cost': 275.00,
                    'inspector_name': 'John Marshall',
                    'inspector_phone': '(555) 123-4567',
                },
                {
                    'permit_number': 'PP-2024-01233',
                    'job_id': jobs[1].id if len(jobs) > 1 else jobs[0].id,
                    'permit_type': 'plumbing',
                    'description': 'Plumbing permit for bathroom rough-in',
                    'issuing_authority': 'City Building Department',
                    'status': 'approved',
                    'application_date': date.today() - timedelta(days=10),
                    'issue_date': date.today() - timedelta(days=3),
                    'expiry_date': date.today() + timedelta(days=10),
                    'cost': 200.00,
                },
            ]
            for pd in permits_data:
                if not db.query(Permit).filter_by(permit_number=pd['permit_number']).first():
                    db.add(Permit(**pd))
            print(f"  + {len(permits_data)} permits")

        # ---- Insurance Policies ----
        policies_data = [
            {
                'policy_type': 'general_liability',
                'policy_number': 'GL-2024-5001',
                'provider': 'Intact Insurance',
                'coverage_amount': 2000000.00,
                'deductible': 5000.00,
                'premium': 4500.00,
                'start_date': date(2024, 1, 1),
                'end_date': date(2024, 12, 31),
                'status': 'active',
                'auto_renew': True,
            },
            {
                'policy_type': 'workers_comp',
                'policy_number': 'WC-2024-3200',
                'provider': 'WSIB Ontario',
                'coverage_amount': 1000000.00,
                'premium': 8200.00,
                'start_date': date(2024, 1, 1),
                'end_date': date.today() + timedelta(days=25),
                'status': 'active',
            },
            {
                'policy_type': 'commercial_auto',
                'policy_number': 'CA-2024-7890',
                'provider': 'Aviva Canada',
                'coverage_amount': 1000000.00,
                'premium': 3800.00,
                'start_date': date(2024, 3, 1),
                'end_date': date(2025, 3, 1),
                'status': 'active',
                'auto_renew': True,
            },
        ]
        for pd in policies_data:
            if not db.query(InsurancePolicy).filter_by(policy_number=pd['policy_number']).first():
                policy = InsurancePolicy(**pd)
                policy.update_status()
                db.add(policy)
        print(f"  + {len(policies_data)} insurance policies")

        # ---- Technician Certifications ----
        technicians = db.query(Technician).limit(4).all()
        cert_count = 0
        if technicians:
            for i, tech in enumerate(technicians):
                certs = [
                    {
                        'technician_id': tech.id,
                        'certification_type': 'first_aid',
                        'certification_name': 'Standard First Aid / CPR-C',
                        'issuing_body': 'Canadian Red Cross',
                        'certificate_number': f'FA-2024-{1000 + i}',
                        'issue_date': date.today() - timedelta(days=180),
                        'expiry_date': date.today() + timedelta(days=185),
                        'is_required': True,
                    },
                    {
                        'technician_id': tech.id,
                        'certification_type': 'safety_training',
                        'certification_name': 'WHMIS 2015',
                        'issuing_body': 'Safety Training Inc.',
                        'issue_date': date.today() - timedelta(days=300),
                        'expiry_date': date.today() + timedelta(days=65),
                        'is_required': True,
                    },
                ]
                for cd in certs:
                    if not db.query(TechnicianCertification).filter_by(
                        technician_id=cd['technician_id'],
                        certification_type=cd['certification_type']
                    ).first():
                        cert = TechnicianCertification(**cd)
                        cert.update_status()
                        db.add(cert)
                        cert_count += 1

            # First tech gets extra certs (one expired)
            extras = [
                {
                    'technician_id': technicians[0].id,
                    'certification_type': 'gas_fitter',
                    'certification_name': 'G2 Gas Fitter License',
                    'issuing_body': 'TSSA',
                    'certificate_number': 'GF-12345',
                    'issue_date': date(2023, 6, 1),
                    'expiry_date': date(2026, 6, 1),
                    'is_required': True,
                },
                {
                    'technician_id': technicians[0].id,
                    'certification_type': 'confined_space',
                    'certification_name': 'Confined Space Entry',
                    'issuing_body': 'SafetyFirst Training',
                    'issue_date': date.today() - timedelta(days=400),
                    'expiry_date': date.today() - timedelta(days=35),  # EXPIRED
                    'is_required': False,
                },
            ]
            for cd in extras:
                if not db.query(TechnicianCertification).filter_by(
                    technician_id=cd['technician_id'],
                    certification_type=cd['certification_type']
                ).first():
                    cert = TechnicianCertification(**cd)
                    cert.update_status()
                    db.add(cert)
                    cert_count += 1

        print(f"  + {cert_count} certifications")

        # ---- Job Certification Requirements ----
        requirements = [
            {'job_type': 'gas', 'certification_type': 'gas_fitter', 'is_mandatory': True},
            {'job_type': 'hvac', 'certification_type': 'refrigerant_handling', 'is_mandatory': True},
            {'job_type': 'electrical', 'certification_type': 'trade_license', 'is_mandatory': True},
            {'job_type': 'confined_space', 'certification_type': 'confined_space', 'is_mandatory': True},
        ]
        req_count = 0
        for req in requirements:
            if not db.query(JobCertificationRequirement).filter_by(
                job_type=req['job_type'],
                certification_type=req['certification_type']
            ).first():
                db.add(JobCertificationRequirement(**req))
                req_count += 1
        print(f"  + {req_count} certification requirements")

        # ---- Checklist Templates ----
        templates_data = [
            {
                'name': 'General Site Safety Checklist',
                'description': 'Standard pre-job safety checklist for all job sites.',
                'checklist_type': 'pre_job',
                'category': 'general_safety',
                'items': [
                    {'question': 'Is the work area properly secured and cordoned off?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'warning'},
                    {'question': 'Are all workers wearing required PPE?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'Is a first aid kit accessible on site?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'Are emergency exits clearly marked and accessible?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'warning'},
                    {'question': 'Are all electrical cords and tools in good condition?', 'item_type': 'pass_fail', 'is_required': True, 'failure_action': 'warning'},
                    {'question': 'Is the area free of trip hazards?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'warning'},
                    {'question': 'Additional safety observations', 'item_type': 'text', 'is_required': False, 'failure_action': 'warning'},
                    {'question': 'Site photo', 'item_type': 'photo', 'is_required': False, 'failure_action': 'warning', 'help_text': 'Take a photo of the work area before starting.'},
                    {'question': 'Supervisor signature', 'item_type': 'signature', 'is_required': True, 'failure_action': 'block_work'},
                ],
            },
            {
                'name': 'Confined Space Entry Checklist',
                'description': 'Required before any confined space entry work.',
                'checklist_type': 'pre_job',
                'category': 'confined_space',
                'items': [
                    {'question': 'Has the confined space been identified and posted?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'Has atmospheric testing been completed?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'Oxygen level (%)', 'item_type': 'number', 'is_required': True, 'failure_action': 'block_work', 'help_text': 'Acceptable range: 19.5% - 23.5%'},
                    {'question': 'Is ventilation equipment in place and operational?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'Is rescue equipment available?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'Is a designated attendant assigned?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'All entrants have confined space training?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'Entry supervisor signature', 'item_type': 'signature', 'is_required': True, 'failure_action': 'block_work'},
                ],
            },
            {
                'name': 'Hot Work Permit Checklist',
                'description': 'Required for welding, cutting, and other hot work operations.',
                'checklist_type': 'pre_job',
                'category': 'hot_work',
                'items': [
                    {'question': 'Are combustible materials removed or protected within 35 feet?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'Is a fire extinguisher within 10 feet?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'Is a fire watch assigned?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'Are fire detection/sprinkler systems operational?', 'item_type': 'yes_no', 'is_required': True, 'failure_action': 'notify_supervisor'},
                    {'question': 'Hot work area photo', 'item_type': 'photo', 'is_required': False, 'failure_action': 'warning'},
                ],
            },
            {
                'name': 'Daily Site Inspection',
                'description': 'Daily walkthrough inspection for active job sites.',
                'checklist_type': 'daily',
                'category': 'general_safety',
                'items': [
                    {'question': 'Site conditions acceptable for work?', 'item_type': 'pass_fail', 'is_required': True, 'failure_action': 'warning'},
                    {'question': 'All scaffolding/ladders properly secured?', 'item_type': 'pass_fail', 'is_required': True, 'failure_action': 'block_work'},
                    {'question': 'Weather conditions', 'item_type': 'text', 'is_required': False, 'failure_action': 'warning'},
                    {'question': 'Number of workers on site', 'item_type': 'number', 'is_required': True, 'failure_action': 'warning'},
                    {'question': 'Any incidents or near-misses to report?', 'item_type': 'text', 'is_required': False, 'failure_action': 'notify_supervisor'},
                ],
            },
        ]
        tpl_count = 0
        for td in templates_data:
            items = td.pop('items')
            if not db.query(ChecklistTemplate).filter_by(name=td['name']).first():
                template = ChecklistTemplate(**td)
                db.add(template)
                db.flush()
                for i, item_data in enumerate(items):
                    item_data['template_id'] = template.id
                    item_data['sort_order'] = i
                    db.add(ChecklistItem(**item_data))
                tpl_count += 1
        print(f"  + {tpl_count} checklist templates")

        # ---- Lien Waivers ----
        waiver_count = 0
        if jobs:
            waivers_data = [
                {
                    'job_id': jobs[0].id,
                    'waiver_type': 'conditional_progress',
                    'party_type': 'subcontractor',
                    'party_name': 'Elite Electrical Services',
                    'amount': 15000.00,
                    'through_date': date.today() - timedelta(days=15),
                    'status': 'accepted',
                    'requested_date': date.today() - timedelta(days=20),
                    'received_date': date.today() - timedelta(days=10),
                },
                {
                    'job_id': jobs[0].id,
                    'waiver_type': 'conditional_progress',
                    'party_type': 'supplier',
                    'party_name': 'BuildPro Supply Co.',
                    'amount': 8500.00,
                    'through_date': date.today() - timedelta(days=15),
                    'status': 'requested',
                    'requested_date': date.today() - timedelta(days=5),
                },
                {
                    'job_id': jobs[0].id,
                    'waiver_type': 'unconditional_final',
                    'party_type': 'subcontractor',
                    'party_name': 'Premium Plumbing Inc.',
                    'amount': 22000.00,
                    'status': 'received',
                    'requested_date': date.today() - timedelta(days=3),
                    'received_date': date.today() - timedelta(days=1),
                },
            ]
            for wd in waivers_data:
                if not db.query(LienWaiver).filter_by(
                    job_id=wd['job_id'], party_name=wd['party_name'],
                    waiver_type=wd['waiver_type']
                ).first():
                    db.add(LienWaiver(**wd))
                    waiver_count += 1
            print(f"  + {waiver_count} lien waivers")

        db.commit()
        print("\nCompliance seed data complete.")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == '__main__':
    seed()
