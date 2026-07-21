#!/usr/bin/env python3
"""
seed_commercial.py — Comprehensive seed data across all modules.
Ties into existing clients, jobs, technicians, invoices.
Run: python seed_commercial.py

Idempotent — checks for existing records before creating.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, date, timedelta
from sqlalchemy import text
from models.database import get_session, Base, engine


def seed():
    # Ensure all tables exist (including new columns)
    Base.metadata.create_all(engine)

    # Fix SLA table schema mismatch if needed
    from sqlalchemy import inspect
    insp = inspect(engine)
    if 'slas' in insp.get_table_names():
        sla_cols = {c['name'] for c in insp.get_columns('slas')}
        if 'sla_name' not in sla_cols and 'name' in sla_cols:
            with engine.connect() as conn:
                try:
                    conn.execute(text('ALTER TABLE slas RENAME COLUMN name TO sla_name'))
                    conn.commit()
                    print("  [FIX] Renamed slas.name -> sla_name")
                except Exception:
                    # SQLite < 3.25 doesn't support RENAME COLUMN
                    try:
                        conn.execute(text('ALTER TABLE slas ADD COLUMN sla_name VARCHAR(255)'))
                        conn.execute(text('UPDATE slas SET sla_name = name'))
                        conn.commit()
                        print("  [FIX] Added sla_name column to slas")
                    except Exception as e2:
                        print(f"  [WARN] Could not fix sla_name: {e2}")
        # Also check for priority_level column
        if 'priority_level' not in sla_cols and 'priority' in sla_cols:
            with engine.connect() as conn:
                try:
                    conn.execute(text('ALTER TABLE slas ADD COLUMN priority_level VARCHAR(20)'))
                    conn.execute(text('UPDATE slas SET priority_level = priority'))
                    conn.commit()
                    print("  [FIX] Added priority_level column to slas")
                except Exception as e:
                    print(f"  [WARN] Could not fix priority_level: {e}")
        # Add missing SLA columns
        for col, coltype in [
            ('business_hours_only', 'BOOLEAN DEFAULT 1'),
            ('business_hours_start', "VARCHAR(5) DEFAULT '08:00'"),
            ('business_hours_end', "VARCHAR(5) DEFAULT '17:00'"),
            ('business_days', "VARCHAR(50) DEFAULT 'mon,tue,wed,thu,fri'"),
            ('penalties', 'TEXT'),
            ('response_time_hours', 'FLOAT'),
            ('resolution_time_hours', 'FLOAT'),
        ]:
            if col not in sla_cols:
                with engine.connect() as conn:
                    try:
                        conn.execute(text(f'ALTER TABLE slas ADD COLUMN {col} {coltype}'))
                        conn.commit()
                        print(f"  [FIX] Added slas.{col}")
                    except Exception:
                        pass

    db = get_session()
    try:
        from models.user import User, Organization
        from models.division import Division
        from models.client import Client, Property
        from models.technician import Technician
        from models.job import Job
        from models.invoice import Invoice, Payment
        from models.quote import Quote
        from models.sla import SLA, PriorityLevel
        from models.contract import (
            Contract, ContractLineItem, ContractType, ContractStatus,
            BillingFrequency, ServiceFrequency
        )
        from models.purchase_order import PurchaseOrder
        from models.service_request import ServiceRequest
        from models.change_order import ChangeOrder, ChangeOrderLineItem
        from models.certification import TechnicianCertification
        from models.insurance import InsurancePolicy
        from models.permit import Permit
        from models.checklist import ChecklistTemplate, ChecklistItem, CompletedChecklist, CompletedChecklistItem
        from models.lien_waiver import LienWaiver
        from models.document import Document

        # Get existing references
        org = db.query(Organization).first()
        if not org:
            print("ERROR: No organization found. Run the app first.")
            return
        org_id = org.id

        user = db.query(User).first()
        user_id = user.id if user else None

        divs = {d.name: d for d in db.query(Division).all()}
        div_plumbing = divs.get('Plumbing')
        div_hvac = divs.get('HVAC')
        div_electrical = divs.get('Electrical')
        div_gc = divs.get('General Contracting')

        techs = db.query(Technician).all()
        clients_by_name = {}
        for c in db.query(Client).all():
            clients_by_name[c.display_name] = c

        jobs = db.query(Job).all()
        invoices = db.query(Invoice).all()

        now = datetime.utcnow()
        today = date.today()

        counts = {}

        # ══════════════════════════════════════════════════════════════
        #  SLA TEMPLATES
        # ══════════════════════════════════════════════════════════════
        print("\n=== SLA Templates ===")
        sla_data = [
            ("Premium 4-Hour Response", PriorityLevel.emergency, 4, 24),
            ("Premium 4-Hour Response", PriorityLevel.high, 8, 48),
            ("Premium 4-Hour Response", PriorityLevel.medium, 24, 72),
            ("Premium 4-Hour Response", PriorityLevel.low, 48, None),
            ("Standard Next Business Day", PriorityLevel.emergency, 8, 48),
            ("Standard Next Business Day", PriorityLevel.high, 24, 72),
            ("Standard Next Business Day", PriorityLevel.medium, 48, 120),
            ("Standard Next Business Day", PriorityLevel.low, 72, None),
            ("Basic Response", PriorityLevel.emergency, 24, 72),
            ("Basic Response", PriorityLevel.high, 48, 120),
            ("Basic Response", PriorityLevel.medium, 72, None),
            ("Basic Response", PriorityLevel.low, None, None),
        ]
        sla_count = 0
        sla_map = {}
        for name, priority, resp, resol in sla_data:
            existing = db.query(SLA).filter_by(sla_name=name, priority_level=priority).first()
            if not existing:
                sla = SLA(
                    organization_id=org_id,
                    sla_name=name, priority_level=priority,
                    response_time_hours=resp or 0, resolution_time_hours=resol,
                    business_hours_only=True,
                )
                db.add(sla)
                sla_count += 1
                sla_map.setdefault(name, []).append(sla)
            else:
                sla_map.setdefault(name, []).append(existing)
        db.flush()
        # Get first SLA ID for each tier
        premium_sla = db.query(SLA).filter_by(sla_name="Premium 4-Hour Response").first()
        standard_sla = db.query(SLA).filter_by(sla_name="Standard Next Business Day").first()
        basic_sla = db.query(SLA).filter_by(sla_name="Basic Response").first()
        print(f"  + {sla_count} SLA entries")
        counts['SLA entries'] = sla_count

        # ══════════════════════════════════════════════════════════════
        #  CONTRACTS
        # ══════════════════════════════════════════════════════════════
        print("\n=== Contracts ===")
        contract_defs = [
            {
                'client': 'KW Property Management Group', 'title': 'Annual HVAC Maintenance — All Properties',
                'type': ContractType.preventive_maintenance, 'status': ContractStatus.active,
                'value': 48000, 'billing': BillingFrequency.monthly, 'division': div_hvac,
                'start': today - timedelta(days=180), 'end': today + timedelta(days=180),
                'auto_renew': True, 'sla': premium_sla,
                'items': [
                    ('Quarterly filter changes', 'All HVAC units', ServiceFrequency.quarterly, 4, 800),
                    ('Annual inspections', 'Full system inspections', ServiceFrequency.annual, 1, 3200),
                    ('Emergency repairs (included)', 'Up to 20 hours/year', ServiceFrequency.annual, 1, 0),
                ],
            },
            {
                'client': 'Grand River Housing Corp', 'title': 'Full Service Plumbing Contract',
                'type': ContractType.full_service, 'status': ContractStatus.active,
                'value': 36000, 'billing': BillingFrequency.quarterly, 'division': div_plumbing,
                'start': today - timedelta(days=90), 'end': today + timedelta(days=270),
                'sla': standard_sla,
                'items': [
                    ('Monthly inspections', 'All buildings', ServiceFrequency.monthly, 12, 1500),
                    ('On-demand repairs', 'Time and materials', ServiceFrequency.monthly, 1, 1500),
                ],
            },
            {
                'client': 'Centurion Property Management', 'title': 'Electrical Maintenance Agreement',
                'type': ContractType.preventive_maintenance, 'status': ContractStatus.active,
                'value': 24000, 'billing': BillingFrequency.monthly, 'division': div_electrical,
                'start': today - timedelta(days=60), 'end': today + timedelta(days=300),
                'sla': premium_sla,
                'items': [
                    ('Quarterly panel inspections', 'All electrical panels', ServiceFrequency.quarterly, 4, 1200),
                    ('Lighting maintenance', 'Common areas', ServiceFrequency.monthly, 12, 800),
                ],
            },
            {
                'client': 'Schlegel Villages Inc.', 'title': 'General Maintenance Contract',
                'type': ContractType.full_service, 'status': ContractStatus.active,
                'value': 60000, 'billing': BillingFrequency.monthly, 'division': div_gc,
                'start': today - timedelta(days=340), 'end': today + timedelta(days=25),
                'auto_renew': False, 'renewal_reminder_days': 30, 'sla': standard_sla,
                'items': [
                    ('HVAC maintenance', 'All buildings', ServiceFrequency.quarterly, 4, 3000),
                    ('Plumbing maintenance', 'All buildings', ServiceFrequency.quarterly, 4, 2500),
                    ('Electrical maintenance', 'All buildings', ServiceFrequency.quarterly, 4, 2000),
                    ('General repairs', 'On-demand', ServiceFrequency.monthly, 12, 1250),
                ],
            },
            {
                'client': 'Conestoga College Facilities', 'title': 'On-Demand HVAC Services',
                'type': ContractType.on_demand, 'status': ContractStatus.active,
                'value': 15000, 'billing': BillingFrequency.per_service, 'division': div_hvac,
                'start': today - timedelta(days=120), 'end': today + timedelta(days=240),
                'sla': basic_sla,
                'items': [
                    ('On-demand HVAC repair', 'Time and materials basis', ServiceFrequency.one_time, 1, 15000),
                ],
            },
        ]

        contract_count = 0
        created_contracts = []
        for cd in contract_defs:
            client = clients_by_name.get(cd['client'])
            if not client:
                print(f"  ! Client '{cd['client']}' not found, skipping")
                continue
            existing = db.query(Contract).filter_by(client_id=client.id, title=cd['title']).first()
            if existing:
                created_contracts.append(existing)
                continue

            contract = Contract(
                organization_id=org_id,
                contract_number=Contract.generate_contract_number(db),
                client_id=client.id,
                division_id=cd['division'].id if cd.get('division') else div_gc.id,
                title=cd['title'],
                contract_type=cd['type'],
                status=cd['status'],
                start_date=cd['start'],
                end_date=cd['end'],
                value=cd['value'],
                billing_frequency=cd['billing'],
                auto_renew=cd.get('auto_renew', False),
                renewal_reminder_days=cd.get('renewal_reminder_days', 30),
                created_by=user_id,
            )
            db.add(contract)
            db.flush()

            for i, (svc, desc, freq, qty, price) in enumerate(cd.get('items', [])):
                li = ContractLineItem(
                    contract_id=contract.id, service_type=svc, description=desc,
                    frequency=freq, quantity=qty, unit_price=price, sort_order=i,
                )
                db.add(li)

            created_contracts.append(contract)
            contract_count += 1

        db.flush()
        print(f"  + {contract_count} contracts")
        counts['contracts'] = contract_count

        # ══════════════════════════════════════════════════════════════
        #  PURCHASE ORDERS
        # ══════════════════════════════════════════════════════════════
        print("\n=== Purchase Orders ===")
        po_defs = [
            {'client': 'KW Property Management Group', 'po_number': 'KW-2026-0401', 'amount': 15000,
             'department': 'Facilities', 'cost_code': 'HVAC-MAINT-01', 'status': 'active', 'used': 8200,
             'contract_idx': 0},
            {'client': 'KW Property Management Group', 'po_number': 'KW-2026-0250', 'amount': 5000,
             'status': 'exhausted', 'used': 5000},
            {'client': 'Grand River Housing Corp', 'po_number': 'GRHC-2026-1100', 'amount': 12000,
             'department': 'Operations', 'status': 'active', 'used': 3500, 'contract_idx': 1},
            {'client': 'Centurion Property Management', 'po_number': 'CPM-2026-0088', 'amount': 8000,
             'status': 'active', 'used': 6800, 'contract_idx': 2},
            {'client': 'Conestoga College Facilities', 'po_number': 'CC-2026-0500', 'amount': 10000,
             'department': 'Facilities Management', 'cost_code': 'MECH-SVC', 'status': 'active', 'used': 1200,
             'contract_idx': 4},
            {'client': 'Schlegel Villages Inc.', 'po_number': 'SV-2025-0900', 'amount': 20000,
             'status': 'expired', 'used': 18500, 'contract_idx': 3,
             'expiry': today - timedelta(days=14)},
        ]

        po_count = 0
        created_pos = []
        for pd in po_defs:
            client = clients_by_name.get(pd['client'])
            if not client:
                continue
            existing = db.query(PurchaseOrder).filter_by(po_number=pd['po_number']).first()
            if existing:
                created_pos.append(existing)
                continue

            contract_id = None
            if 'contract_idx' in pd and pd['contract_idx'] < len(created_contracts):
                contract_id = created_contracts[pd['contract_idx']].id

            po = PurchaseOrder(
                organization_id=org_id, po_number=pd['po_number'],
                client_id=client.id, contract_id=contract_id,
                description=f"PO for {client.display_name}",
                status=pd['status'], amount_authorized=pd['amount'],
                amount_used=pd.get('used', 0),
                issue_date=today - timedelta(days=60),
                expiry_date=pd.get('expiry', today + timedelta(days=300)),
                department=pd.get('department'),
                cost_code=pd.get('cost_code'),
                created_by=user_id,
            )
            db.add(po)
            created_pos.append(po)
            po_count += 1

        db.flush()

        # Link some invoices to POs and set payment terms
        if created_pos:
            # Link KW invoices to PO 1 (client_id=14 = KW Property Management)
            kw_invoices = [i for i in invoices if i.client_id == 14 and not i.po_id]
            for inv in kw_invoices[:3]:
                inv.po_id = created_pos[0].id
                inv.po_number_display = created_pos[0].po_number
                inv.payment_terms = 'net_30'

            # Link Grand River invoices to PO 3
            gr_invoices = [i for i in invoices if i.client_id == 10 and not i.po_id]
            for inv in gr_invoices[:2]:
                if len(created_pos) > 2:
                    inv.po_id = created_pos[2].id
                    inv.po_number_display = created_pos[2].po_number
                    inv.payment_terms = 'net_60'

        print(f"  + {po_count} purchase orders")
        counts['purchase orders'] = po_count

        # ══════════════════════════════════════════════════════════════
        #  SERVICE REQUESTS
        # ══════════════════════════════════════════════════════════════
        print("\n=== Service Requests ===")
        # Find jobs to link as "converted"
        completed_jobs = [j for j in jobs if j.status == 'completed']
        angela_job = next((j for j in jobs if j.client_id == 19), None)
        terra_job = next((j for j in jobs if j.client_id == 5), None)

        sr_defs = [
            {'contact': 'KW Property Management', 'client': 'KW Property Management Group',
             'source': 'phone', 'priority': 'emergency', 'type': 'hvac',
             'desc': 'Rooftop unit not cooling — tenant complaints in units 3A and 4B at Weber Place',
             'status': 'new', 'days_ago': 0},
            {'contact': 'Grand River Housing', 'client': 'Grand River Housing Corp',
             'source': 'email', 'priority': 'high', 'type': 'plumbing',
             'desc': 'Water heater leaking in basement of 77 Queen St building, possible flood risk',
             'status': 'new', 'days_ago': 0},
            {'contact': 'Centurion Property', 'client': 'Centurion Property Management',
             'source': 'portal', 'priority': 'medium', 'type': 'electrical',
             'desc': 'Parking garage lighting flickering on level 2, multiple fixtures',
             'status': 'reviewed', 'days_ago': 2},
            {'contact_name': 'Sarah Mitchell', 'phone': '(519) 555-8877',
             'source': 'phone', 'priority': 'medium', 'type': 'plumbing',
             'desc': 'Kitchen sink backed up, garbage disposal not working',
             'status': 'new', 'days_ago': 1},
            {'contact': 'Winmar Property', 'client': 'Winmar Property Restoration',
             'source': 'referral', 'priority': 'low', 'type': 'general',
             'desc': 'Quote request for office renovation — 3 rooms, new flooring and paint',
             'status': 'reviewed', 'days_ago': 5},
            {'contact': 'Angela Petrova', 'client': 'Angela Petrova',
             'source': 'phone', 'priority': 'high', 'type': 'electrical',
             'desc': 'Breaker keeps tripping on main panel, burning smell reported',
             'status': 'converted', 'days_ago': 7, 'job': angela_job},
            {'contact': 'Terra Corp', 'client': 'Terra Corp Developments',
             'source': 'email', 'priority': 'medium', 'type': 'hvac',
             'desc': 'Annual rooftop unit servicing due for Terra Towers — 4 units total',
             'status': 'converted', 'days_ago': 14, 'job': terra_job},
            {'contact': 'Tom Brewster', 'client': 'Tom Brewster',
             'source': 'walk_in', 'priority': 'low', 'type': 'plumbing',
             'desc': 'Slow drain in master bathroom, been getting worse over a few weeks',
             'status': 'declined', 'days_ago': 21},
        ]

        sr_count = 0
        for sd in sr_defs:
            contact_name = sd.get('contact_name', sd.get('contact', 'Unknown'))
            existing = db.query(ServiceRequest).filter_by(
                organization_id=org_id, description=sd['desc']
            ).first()
            if existing:
                continue

            client = clients_by_name.get(sd.get('client')) if sd.get('client') else None

            db.flush()  # Flush before generating number so previous SRs are visible
            sr = ServiceRequest(
                organization_id=org_id,
                request_number=ServiceRequest.generate_number(db, org_id),
                contact_name=contact_name,
                contact_phone=sd.get('phone'),
                client_id=client.id if client else None,
                source=sd['source'],
                request_type=sd['type'],
                priority=sd['priority'],
                description=sd['desc'],
                status=sd['status'],
                assigned_to=user_id if sd['status'] == 'reviewed' else None,
                converted_job_id=sd['job'].id if sd.get('job') else None,
                created_by=user_id,
                created_at=now - timedelta(days=sd['days_ago']),
            )
            db.add(sr)
            sr_count += 1

        db.flush()
        print(f"  + {sr_count} service requests")
        counts['service requests'] = sr_count

        # ══════════════════════════════════════════════════════════════
        #  CHANGE ORDERS
        # ══════════════════════════════════════════════════════════════
        print("\n=== Change Orders ===")
        # Pick jobs: highest value commercial in_progress jobs
        ip_jobs = sorted(
            [j for j in jobs if j.status == 'in_progress' and j.estimated_amount and j.estimated_amount > 5000],
            key=lambda j: j.estimated_amount or 0, reverse=True
        )

        co_count = 0
        if len(ip_jobs) >= 2:
            job1 = ip_jobs[0]  # Highest value
            job2 = ip_jobs[1]

            co_defs = [
                {
                    'job': job1, 'title': 'Additional circuit installation',
                    'desc': 'Client requested 4 additional 20A circuits in server room',
                    'reason': 'client_request', 'status': 'approved', 'cost_type': 'addition',
                    'original': 0, 'revised': 2400, 'approved': True, 'days_ago': 14,
                    'items': [('Materials — wire, breakers, conduit', 1, 1200, True),
                              ('Labor — circuit installation', 1, 1200, True)],
                },
                {
                    'job': job1, 'title': 'Upgrade to commercial-grade fixtures',
                    'desc': 'Design change: upgrade all lighting fixtures to commercial LED',
                    'reason': 'design_change', 'status': 'pending_approval', 'cost_type': 'addition',
                    'original': 3200, 'revised': 5800, 'days_ago': 3,
                    'items': [('Commercial LED fixtures (qty 24)', 24, 75, True),
                              ('Installation labor', 16, 65, True),
                              ('Remove existing fixtures', 1, 400, True)],
                },
                {
                    'job': job2, 'title': 'Unforeseen asbestos abatement',
                    'desc': 'Asbestos found in pipe insulation during demolition phase',
                    'reason': 'unforeseen_condition', 'status': 'approved', 'cost_type': 'addition',
                    'original': 0, 'revised': 4500, 'approved': True, 'labor_hours': 16, 'days_ago': 10,
                    'items': [('Asbestos abatement — certified contractor', 1, 3500, True),
                              ('Air quality testing', 1, 1000, True)],
                },
                {
                    'job': job2, 'title': 'Remove scope — client handling painting internally',
                    'desc': 'Client will handle all painting work with their own crew',
                    'reason': 'client_request', 'status': 'approved', 'cost_type': 'deduction',
                    'original': 3000, 'revised': 0, 'approved': True, 'days_ago': 8,
                    'items': [('Painting scope removal', 1, 3000, False)],
                },
            ]

            # Add a 5th CO on a scheduled/multi-phase job if available
            sched_jobs = [j for j in jobs if j.status == 'scheduled' and j.estimated_amount and j.estimated_amount > 3000]
            if sched_jobs:
                co_defs.append({
                    'job': sched_jobs[0], 'title': 'Add Phase 4 — Final inspection prep',
                    'desc': 'Regulatory requirement: additional inspection preparation phase needed',
                    'reason': 'regulatory', 'status': 'draft', 'cost_type': 'addition',
                    'original': 0, 'revised': 1800, 'days_ago': 1,
                    'items': [('Inspection preparation', 1, 1200, True),
                              ('Documentation package', 1, 600, True)],
                })

            for cd in co_defs:
                job = cd['job']
                existing = db.query(ChangeOrder).filter_by(
                    job_id=job.id, title=cd['title']
                ).first()
                if existing:
                    continue

                co = ChangeOrder(
                    change_order_number=ChangeOrder.generate_number(db, job.id),
                    job_id=job.id,
                    title=cd['title'],
                    description=cd['desc'],
                    reason=cd['reason'],
                    status=cd['status'],
                    requested_by='client' if cd['reason'] == 'client_request' else 'project_manager',
                    requested_date=today - timedelta(days=cd['days_ago']),
                    cost_type=cd['cost_type'],
                    original_amount=cd['original'],
                    revised_amount=cd['revised'],
                    labor_hours_impact=cd.get('labor_hours', 0),
                    client_approved=cd.get('approved'),
                    client_approved_by='Client Rep' if cd.get('approved') else None,
                    client_approved_date=now - timedelta(days=cd['days_ago'] - 1) if cd.get('approved') else None,
                    created_by_id=user_id,
                )
                db.add(co)
                db.flush()

                for desc, qty, price, is_add in cd.get('items', []):
                    li = ChangeOrderLineItem(
                        change_order_id=co.id,
                        description=desc, quantity=qty, unit_price=price,
                        is_addition=is_add,
                    )
                    db.add(li)
                co_count += 1

        db.flush()
        print(f"  + {co_count} change orders")
        counts['change orders'] = co_count

        # ══════════════════════════════════════════════════════════════
        #  ADDITIONAL PAYMENTS
        # ══════════════════════════════════════════════════════════════
        print("\n=== Additional Payments ===")
        # Find invoices that could use payments
        unpaid_invoices = [i for i in invoices if i.status in ('sent', 'overdue') and i.balance_due > 0]
        pay_count = 0

        new_payments = [
            {'method': 'credit_card', 'ref': 'CC-4521', 'days_ago': 0,
             'note': None},
            {'method': 'e-transfer', 'ref': 'ET-20260409-01', 'days_ago': 2,
             'note': None},
            {'method': 'cheque', 'ref': 'CHK-10445', 'days_ago': 5,
             'note': None},
            {'method': 'credit_card', 'ref': 'CC-4522', 'days_ago': 30,
             'note': None},
            {'method': 'cheque', 'ref': 'CHK-10390', 'days_ago': 35,
             'note': 'Client disputed line item 3, partial payment pending resolution'},
        ]

        for i, pdef in enumerate(new_payments):
            if i >= len(unpaid_invoices):
                break
            inv = unpaid_invoices[i]
            # Check if this ref already exists
            if db.query(Payment).filter_by(reference_number=pdef['ref']).first():
                continue

            # Partial payment for some, full for others
            if i < 2:
                amt = float(inv.balance_due)  # Full pay
            else:
                amt = round(float(inv.balance_due) * 0.6, 2)  # 60% partial

            p = Payment(
                invoice_id=inv.id, amount=amt,
                payment_method=pdef['method'],
                reference_number=pdef['ref'],
                notes=pdef.get('note'),
                payment_date=now - timedelta(days=pdef['days_ago']),
            )
            db.add(p)

            inv.amount_paid = float(inv.amount_paid or 0) + amt
            inv.balance_due = float(inv.total or 0) - float(inv.amount_paid)
            if inv.balance_due <= 0:
                inv.status = 'paid'
                inv.balance_due = 0
            elif amt > 0 and inv.balance_due > 0:
                inv.status = 'partial'
            pay_count += 1

        db.flush()
        print(f"  + {pay_count} payments")
        counts['payments'] = pay_count

        # ══════════════════════════════════════════════════════════════
        #  TECHNICIAN CERTIFICATIONS
        # ══════════════════════════════════════════════════════════════
        print("\n=== Technician Certifications ===")
        cert_defs = [
            (0, 'trade_license', 'Master Plumber License', 'TSSA Ontario', today + timedelta(days=420)),
            (0, 'first_aid', 'First Aid / CPR-C', 'Red Cross', today + timedelta(days=300)),
            (0, 'confined_space', 'Confined Space Entry', 'SafetyFirst Training', today - timedelta(days=14)),  # EXPIRED
            (1, 'trade_license', 'Journeyman Plumber License', 'TSSA Ontario', today + timedelta(days=420)),
            (1, 'safety_training', 'WHMIS 2015', 'Safety Training Inc.', today + timedelta(days=60)),  # Expiring soon
            (2, 'refrigerant_handling', 'Refrigerant Handling (HRAI)', 'HRAI', today + timedelta(days=540)),
            (2, 'trade_license', 'Gas Fitter Class B', 'TSSA', today + timedelta(days=90)),  # Expiring soon
            (2, 'first_aid', 'First Aid / CPR-C', 'Red Cross', today + timedelta(days=300)),
            (3, 'safety_training', 'WHMIS 2015', 'Safety Training Inc.', today + timedelta(days=60)),
            (3, 'working_at_heights', 'Working at Heights', 'IHSA', today + timedelta(days=30)),  # Expiring very soon
            (4, 'trade_license', 'Master Electrician License', 'ESA Ontario', today + timedelta(days=240)),
            (4, 'safety_training', 'Arc Flash Safety', 'CSA', today + timedelta(days=180)),
            (4, 'first_aid', 'First Aid / CPR-C', 'Red Cross', today + timedelta(days=300)),
            (5, 'safety_training', 'Fall Protection Training', 'IHSA', today + timedelta(days=180)),
            (5, 'forklift', 'Forklift Operator', 'IHSA', None),  # No expiry
            (6, 'trade_license', 'Backflow Prevention Tester', 'OWWA', today - timedelta(days=30)),  # EXPIRED
            (6, 'first_aid', 'First Aid / CPR-C', 'Red Cross', today + timedelta(days=300)),
            (7, 'refrigerant_handling', 'Refrigerant Handling', 'HRAI', today + timedelta(days=540)),
            (7, 'crane_operator', 'Boom/Crane Operator', 'IHSA', today + timedelta(days=365)),
            (8, 'trade_license', 'Journeyman Electrician', 'ESA Ontario', today + timedelta(days=420)),
            (8, 'safety_training', 'WHMIS 2015', 'Safety Training Inc.', today + timedelta(days=60)),
            (9, 'safety_training', 'Fall Protection Training', 'IHSA', today + timedelta(days=180)),
            (9, 'first_aid', 'First Aid / CPR-C', 'Red Cross', today + timedelta(days=300)),
        ]

        cert_count = 0
        for tech_idx, cert_type, cert_name, issuer, expiry in cert_defs:
            if tech_idx >= len(techs):
                continue
            tech = techs[tech_idx]
            existing = db.query(TechnicianCertification).filter_by(
                technician_id=tech.id, certification_type=cert_type, certification_name=cert_name
            ).first()
            if existing:
                continue

            cert = TechnicianCertification(
                technician_id=tech.id,
                certification_type=cert_type,
                certification_name=cert_name,
                issuing_body=issuer,
                issue_date=expiry - timedelta(days=730) if expiry else today - timedelta(days=365),
                expiry_date=expiry,
                is_required=cert_type in ('trade_license', 'first_aid'),
            )
            cert.update_status()
            db.add(cert)
            cert_count += 1

        db.flush()
        print(f"  + {cert_count} certifications")
        counts['certifications'] = cert_count

        # ══════════════════════════════════════════════════════════════
        #  INSURANCE POLICIES
        # ══════════════════════════════════════════════════════════════
        print("\n=== Insurance Policies ===")
        ins_defs = [
            ('general_liability', 'GL-2026-5001', 'Aviva Canada', 2000000, 8500, today + timedelta(days=210), True),
            ('workers_comp', 'WC-2026-3200', 'WSIB Ontario', 1000000, 6200, today + timedelta(days=120), True),
            ('commercial_auto', 'CA-2026-7890', 'Intact Insurance', 1000000, 4800, today + timedelta(days=270), True),
            ('professional_liability', 'PL-2026-1100', 'Northbridge Insurance', 500000, 3200, today + timedelta(days=330), True),
            ('equipment_floater', 'EQ-2025-0400', 'Intact Insurance', 250000, 1800, today - timedelta(days=21), False),  # EXPIRED
        ]

        ins_count = 0
        created_policies = []
        for ptype, pnum, provider, coverage, premium, end, is_active in ins_defs:
            existing = db.query(InsurancePolicy).filter_by(policy_number=pnum).first()
            if existing:
                created_policies.append(existing)
                continue

            start = end - timedelta(days=365)
            policy = InsurancePolicy(
                policy_type=ptype, policy_number=pnum, provider=provider,
                coverage_amount=coverage, premium=premium,
                start_date=start, end_date=end,
                status='active' if is_active else 'expired',
                auto_renew=is_active,
            )
            policy.update_status()
            db.add(policy)
            created_policies.append(policy)
            ins_count += 1

        db.flush()
        print(f"  + {ins_count} insurance policies")
        counts['insurance policies'] = ins_count

        # ══════════════════════════════════════════════════════════════
        #  PERMITS
        # ══════════════════════════════════════════════════════════════
        print("\n=== Permits ===")
        # Pick jobs by type
        gc_jobs = [j for j in jobs if j.division_id == div_gc.id and j.status in ('in_progress', 'scheduled')]
        elec_jobs = [j for j in jobs if j.division_id == div_electrical.id and j.status in ('in_progress', 'scheduled', 'completed')]
        plumb_jobs = [j for j in jobs if j.division_id == div_plumbing.id and j.status in ('in_progress', 'scheduled', 'completed')]
        hvac_jobs = [j for j in jobs if j.division_id == div_hvac.id and j.status in ('in_progress', 'scheduled')]

        permit_defs = [
            ('building', 'BP-2026-04231', gc_jobs[0] if gc_jobs else jobs[0],
             'City of Waterloo Building Dept', 'active', 450, today - timedelta(days=21), today + timedelta(days=180)),
            ('electrical', 'EP-2026-08812', elec_jobs[0] if elec_jobs else jobs[2],
             'Electrical Safety Authority', 'inspection_required', 200, today - timedelta(days=14), today + timedelta(days=90)),
            ('plumbing', 'PP-2026-03344', plumb_jobs[0] if plumb_jobs else jobs[1],
             'City of Kitchener Plumbing Dept', 'inspection_passed', 175, today - timedelta(days=30), today + timedelta(days=150)),
            ('mechanical', 'MP-2026-01122', hvac_jobs[0] if hvac_jobs else jobs[3],
             'City of Cambridge Building Dept', 'inspection_failed', 225, today - timedelta(days=20), today + timedelta(days=120)),
            ('other', 'EX-2026-00567', jobs[10] if len(jobs) > 10 else jobs[0],
             'Region of Waterloo', 'expired', 300, today - timedelta(days=60), today - timedelta(days=5)),
        ]

        permit_count = 0
        created_permits = []
        for ptype, pnum, job, authority, status, cost, issue, expiry in permit_defs:
            existing = db.query(Permit).filter_by(permit_number=pnum).first()
            if existing:
                created_permits.append(existing)
                continue

            permit = Permit(
                job_id=job.id, permit_type=ptype, permit_number=pnum,
                issuing_authority=authority, status=status, cost=cost,
                issue_date=issue, expiry_date=expiry,
                application_date=issue - timedelta(days=14),
            )
            if pnum == 'EP-2026-08812':
                permit.inspector_name = 'Mike Chen'
                permit.inspector_phone = '(519) 555-0199'
            if pnum == 'MP-2026-01122':
                permit.notes = 'Ductwork clearance does not meet code — requires 3-inch gap from combustibles'

            db.add(permit)
            created_permits.append(permit)
            permit_count += 1

        db.flush()
        print(f"  + {permit_count} permits")
        counts['permits'] = permit_count

        # ══════════════════════════════════════════════════════════════
        #  SAFETY CHECKLISTS
        # ══════════════════════════════════════════════════════════════
        print("\n=== Safety Checklists ===")
        tpl_defs = [
            ('General Site Safety Checklist', 'pre_job', 'general_safety', [
                ('Is the work area clear of tripping hazards?', 'yes_no', True, 'warning'),
                ('Are all workers wearing required PPE?', 'yes_no', True, 'block_work'),
                ('Is the first aid kit accessible and stocked?', 'yes_no', True, 'warning'),
                ('Are fire extinguishers present and charged?', 'yes_no', True, 'warning'),
                ('Has the area been checked for overhead hazards?', 'yes_no', True, 'warning'),
                ('Are emergency exits clear and marked?', 'yes_no', True, 'warning'),
                ('Site conditions notes', 'text', False, 'warning'),
                ('Weather conditions', 'text', False, 'warning'),
            ]),
            ('Confined Space Entry Checklist', 'pre_job', 'confined_space', [
                ('Has atmospheric testing been completed?', 'yes_no', True, 'block_work'),
                ('Is rescue equipment staged and accessible?', 'yes_no', True, 'block_work'),
                ('Has the space been ventilated?', 'yes_no', True, 'block_work'),
                ('Is a trained attendant stationed at entry?', 'yes_no', True, 'block_work'),
                ('Gas monitor reading (LEL %)', 'number', True, 'notify_supervisor'),
                ('Entry permit photo', 'photo', True, 'warning'),
            ]),
            ('Electrical Safety Checklist', 'pre_job', 'electrical', [
                ('Has lockout/tagout been performed?', 'yes_no', True, 'block_work'),
                ('Has the circuit been verified de-energized?', 'yes_no', True, 'block_work'),
                ('Are insulated tools being used?', 'yes_no', True, 'warning'),
                ('Is arc flash PPE being worn?', 'yes_no', True, 'block_work'),
                ('Voltage reading at work point', 'number', True, 'warning'),
            ]),
            ('Job Completion Checklist', 'post_job', 'general_safety', [
                ('Has the work area been cleaned?', 'yes_no', True, 'warning'),
                ('Have all tools and equipment been accounted for?', 'yes_no', True, 'warning'),
                ('Has the client been shown the completed work?', 'yes_no', False, 'warning'),
                ('Completion photos taken?', 'photo', True, 'warning'),
                ('Client signature', 'signature', True, 'warning'),
            ]),
        ]

        tpl_count = 0
        created_templates = []
        for tname, ttype, tcat, items in tpl_defs:
            existing = db.query(ChecklistTemplate).filter_by(name=tname).first()
            if existing:
                created_templates.append(existing)
                continue

            tpl = ChecklistTemplate(
                name=tname, checklist_type=ttype, category=tcat,
                is_active=True, created_by=user_id,
            )
            db.add(tpl)
            db.flush()

            for i, (q, itype, req, fail) in enumerate(items):
                db.add(ChecklistItem(
                    template_id=tpl.id, question=q, item_type=itype,
                    is_required=req, failure_action=fail, sort_order=i,
                ))

            created_templates.append(tpl)
            tpl_count += 1

        db.flush()

        # Completed checklists
        comp_count = 0
        completed_jobs_list = [j for j in jobs if j.status == 'completed']
        for i, tpl in enumerate(created_templates[:3]):
            if i >= len(completed_jobs_list):
                break
            job = completed_jobs_list[i]
            existing = db.query(CompletedChecklist).filter_by(
                template_id=tpl.id, job_id=job.id
            ).first()
            if existing:
                continue

            cc = CompletedChecklist(
                template_id=tpl.id, job_id=job.id,
                completed_by=user_id,
                overall_status='passed',
                completed_at=now - timedelta(days=7 * (i + 1)),
                notes='Client satisfied with work quality' if i == 2 else None,
            )
            db.add(cc)
            db.flush()

            for item in tpl.items:
                resp = 'yes' if item.item_type == 'yes_no' else ('0' if item.item_type == 'number' else 'OK')
                db.add(CompletedChecklistItem(
                    completed_checklist_id=cc.id, checklist_item_id=item.id,
                    response=resp, is_compliant=True, sort_order=item.sort_order,
                ))
            comp_count += 1

        db.flush()
        print(f"  + {tpl_count} checklist templates, {comp_count} completions")
        counts['checklist templates'] = tpl_count
        counts['completed checklists'] = comp_count

        # ══════════════════════════════════════════════════════════════
        #  LIEN WAIVERS
        # ══════════════════════════════════════════════════════════════
        print("\n=== Lien Waivers ===")
        commercial_jobs = [j for j in jobs if j.client_id in (14, 10, 13, 12) and j.status in ('in_progress', 'completed')]
        paid_invoices = [i for i in invoices if i.status == 'paid']

        lw_count = 0
        lw_defs = [
            ('conditional_progress', 'general_contractor', 'Patriot Tech Systems', 12000, 'received',
             commercial_jobs[0] if commercial_jobs else jobs[0], paid_invoices[0] if paid_invoices else None),
            ('unconditional_progress', 'general_contractor', 'Patriot Tech Systems', 8500, 'accepted',
             commercial_jobs[1] if len(commercial_jobs) > 1 else jobs[1], paid_invoices[1] if len(paid_invoices) > 1 else None),
            ('conditional_final', 'subcontractor', 'ABC Electrical Sub', 4200, 'requested',
             commercial_jobs[0] if commercial_jobs else jobs[0], None),
            ('conditional_progress', 'supplier', 'Superior Plumbing Supply', 2800, 'received',
             commercial_jobs[1] if len(commercial_jobs) > 1 else jobs[1], None),
        ]

        for wtype, ptype, party, amt, status, job, inv in lw_defs:
            existing = db.query(LienWaiver).filter_by(
                job_id=job.id, party_name=party, waiver_type=wtype
            ).first()
            if existing:
                continue

            lw = LienWaiver(
                job_id=job.id, waiver_type=wtype, party_type=ptype,
                party_name=party, amount=amt, status=status,
                invoice_id=inv.id if inv else None,
                through_date=today - timedelta(days=15),
                requested_date=today - timedelta(days=20),
                received_date=today - timedelta(days=10) if status in ('received', 'accepted') else None,
            )
            db.add(lw)
            lw_count += 1

        db.flush()
        print(f"  + {lw_count} lien waivers")
        counts['lien waivers'] = lw_count

        # ══════════════════════════════════════════════════════════════
        #  DOCUMENTS (placeholder records)
        # ══════════════════════════════════════════════════════════════
        print("\n=== Documents ===")
        doc_defs = [
            ('KW Property Management — Service Agreement 2026.pdf', 'contract', 'contract',
             created_contracts[0].id if created_contracts else None),
            ('Certificate of Insurance — General Liability.pdf', 'insurance', 'insurance_policy',
             created_policies[0].id if created_policies else None),
            (f'Master Electrician License — {techs[4].full_name}.pdf', 'certification', 'certification', None),
            ('Building Permit BP-2026-04231.pdf', 'permit', 'permit',
             created_permits[0].id if created_permits else None),
            ('Site Safety Inspection Report — Weber Place.pdf', 'report', 'job',
             jobs[0].id if jobs else None),
            ('Change Order CO-01 — Signed.pdf', 'other', 'job',
             ip_jobs[0].id if ip_jobs else None),
            ('PO KW-2026-0401.pdf', 'other', 'job', None),
            ('Completion Photos — JOB-00048.zip', 'photo', 'job', 48 if len(jobs) >= 48 else jobs[-1].id),
            ('Lien Waiver — ABC Electrical.pdf', 'lien_waiver', 'job',
             commercial_jobs[0].id if commercial_jobs else None),
            ('Equipment Inspection Report.pdf', 'report', 'job',
             jobs[5].id if len(jobs) > 5 else jobs[0].id),
        ]

        doc_count = 0
        for dname, cat, etype, eid in doc_defs:
            existing = db.query(Document).filter_by(display_name=dname).first()
            if existing:
                continue

            doc = Document(
                filename=dname.lower().replace(' ', '_').replace('—', '-'),
                file_path=f'/placeholder/documents/{dname.lower().replace(" ", "_")}',
                file_type='application/pdf' if dname.endswith('.pdf') else 'application/zip',
                file_size=1024 * 50,  # 50KB placeholder
                display_name=dname,
                category=cat,
                entity_type=etype,
                entity_id=eid,
                uploaded_by=user_id,
            )
            db.add(doc)
            doc_count += 1

        db.flush()
        print(f"  + {doc_count} documents")
        counts['documents'] = doc_count

        # ══════════════════════════════════════════════════════════════
        #  EQUIPMENT
        # ══════════════════════════════════════════════════════════════
        print("\n=== Equipment ===")
        from models.equipment import Equipment

        equip_defs = [
            ('Service Van 01', 'vehicle', 'Ford', 'Transit', 2023, '1FTBW2CM5NKA12345', 'assigned', 85, None, div_plumbing,
             today - timedelta(days=30), today + timedelta(days=60)),
            ('Service Van 02', 'vehicle', 'Ford', 'Transit', 2022, '1FTBW2CM6NKA67890', 'available', 85, None, div_hvac,
             today - timedelta(days=90), today + timedelta(days=7)),
            ('Service Van 03', 'vehicle', 'Chevrolet', 'Express', 2021, '1GCGG25K371000001', 'in_maintenance', 75, None, div_electrical,
             today - timedelta(days=3), today + timedelta(days=90)),
            ('Mini Excavator', 'heavy_equipment', 'Kubota', 'KX040', 2020, 'KX040-5-12345', 'available', 250, 45, div_gc,
             today - timedelta(days=60), today + timedelta(days=120)),
            ('Boom Lift 30ft', 'heavy_equipment', 'JLG', '340AJ', 2019, 'JLG340AJ-99876', 'assigned', 180, None, div_gc,
             today - timedelta(days=45), today + timedelta(days=135)),
            ('Pipe Threading Machine', 'power_tool', 'Ridgid', '300', None, 'RDG-300-001', 'available', None, 15, div_plumbing,
             today - timedelta(days=120), today + timedelta(days=60)),
            ('Wire Puller', 'power_tool', 'Greenlee', '6001', None, 'GL-6001-002', 'assigned', None, None, div_electrical,
             None, None),
            ('Drain Camera', 'specialty', 'RIDGID', 'SeeSnake', None, 'SS-MINI-003', 'available', None, 25, div_plumbing,
             today - timedelta(days=7), today + timedelta(days=180)),
            ('Refrigerant Recovery Unit', 'specialty', 'Appion', 'G5Twin', None, 'APG5-004', 'available', None, None, div_hvac,
             today - timedelta(days=90), today + timedelta(days=90)),
            ('Electrical Test Kit', 'specialty', 'Fluke', '1587FC', None, 'FLK-1587-005', 'out_of_service', None, None, div_electrical,
             today - timedelta(days=420), today - timedelta(days=30)),
        ]

        equip_count = 0
        for name, etype, make, model_name, year, serial, status, daily, hourly, div, last_m, next_m in equip_defs:
            if db.query(Equipment).filter_by(organization_id=org_id, name=name).first():
                continue
            eq = Equipment(
                organization_id=org_id, name=name, equipment_type=etype,
                make=make, model=model_name, year=year, serial_number=serial,
                status=status, daily_rate=daily, hourly_rate=hourly,
                division_id=div.id if div else None,
                last_maintenance=last_m, next_maintenance=next_m,
            )
            if name == 'Service Van 03':
                eq.notes = 'Engine oil leak repair in progress'
            if name == 'Electrical Test Kit':
                eq.notes = 'Needs annual calibration — overdue'
                eq.warranty_expiry = today - timedelta(days=30)
            db.add(eq)
            equip_count += 1

        db.flush()
        print(f"  + {equip_count} equipment items")
        counts['equipment'] = equip_count

        # ══════════════════════════════════════════════════════════════
        #  COMMIT
        # ══════════════════════════════════════════════════════════════
        db.commit()

        print("\n" + "=" * 50)
        print("SEED COMPLETE — Summary:")
        print("=" * 50)
        for k, v in counts.items():
            if v > 0:
                print(f"  Created: {v} {k}")
        print()

    except Exception as e:
        db.rollback()
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    seed()
