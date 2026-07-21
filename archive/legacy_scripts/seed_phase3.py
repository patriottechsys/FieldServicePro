#!/usr/bin/env python3
"""
seed_phase3.py
Seeds Phase 3 commercial invoicing data:
  - Updates clients with billing/commercial fields
  - Creates purchase orders with varying states
  - Creates commercial invoices linked to POs
  - Sets up approval queue scenarios
  - Seeds aging scenarios across all buckets

Run: python seed_phase3.py  (after seed_contracts.py and migrations)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta, datetime
from models.database import get_session, Base, engine
from models.user import User, Organization
from models.client import Client
from models.invoice import Invoice, InvoiceItem
from models.purchase_order import PurchaseOrder
from models.settings import OrganizationSettings
from models.division import Division


def seed():
    # Ensure tables exist
    Base.metadata.create_all(engine)

    db = get_session()
    try:
        print("Seeding Phase 3 commercial invoicing data...\n")

        org = db.query(Organization).first()
        if not org:
            print("ERROR: No organization found. Register a user first.")
            return
        org_id = org.id

        owner = db.query(User).filter_by(organization_id=org_id, role='owner').first()
        if not owner:
            owner = db.query(User).filter_by(organization_id=org_id).first()
        if not owner:
            print("ERROR: No users found. Register first.")
            return
        print(f"Using org: {org.name}, user: {owner.full_name}")

        # Get a division
        division = db.query(Division).filter_by(organization_id=org_id).first()

        # -- Organization Settings --
        settings = OrganizationSettings.get_or_create(db, org_id)
        settings.invoice_approval_enabled = True
        settings.invoice_approval_threshold = 1000.00
        settings.invoice_approval_roles = 'owner,admin'
        settings.invoice_number_prefix = 'INV'
        settings.statement_footer_text = (
            'Payment due per invoice terms. '
            'Please include invoice number with your remittance. '
            'Inquiries: billing@fieldservicepro.com'
        )
        db.flush()

        # -- Update commercial clients with billing fields --
        clients = db.query(Client).filter_by(
            organization_id=org_id, is_active=True
        ).limit(3).all()

        if not clients:
            print("No clients found. Creating sample clients...")
            for i, (name, co) in enumerate([
                ('Sarah', 'Apex Property Management Inc.'),
                ('Rick', 'Ridgeline Retail Group LLC'),
                ('Priya', 'Northern Data Centre Corp.'),
            ]):
                c = Client(
                    organization_id=org_id, client_type='commercial',
                    company_name=co, first_name=name, last_name='Test',
                    email=f'{name.lower()}@example.com', phone=f'555-010{i+1}',
                )
                db.add(c)
            db.flush()
            clients = db.query(Client).filter_by(organization_id=org_id, is_active=True).limit(3).all()

        billing_configs = [
            dict(default_payment_terms='net_30', credit_limit=50000.0,
                 require_po=True, billing_email='ap@apex-pm.com',
                 billing_contact_name='Sarah Chen', billing_contact_phone='416-555-0101'),
            dict(default_payment_terms='net_45', credit_limit=25000.0,
                 require_po=False, billing_email='billing@ridgeline.com',
                 billing_contact_name='Rick Webb', billing_contact_phone='905-555-0202'),
            dict(default_payment_terms='net_60', credit_limit=100000.0,
                 require_po=True, billing_email='facilities@ndc.ca',
                 billing_contact_name='Priya Okonkwo', billing_contact_phone='647-555-0303',
                 tax_exempt=True, tax_exempt_number='TX-2024-NDC-001'),
        ]
        for i, client in enumerate(clients[:3]):
            cfg = billing_configs[i % len(billing_configs)]
            for k, v in cfg.items():
                if hasattr(client, k):
                    setattr(client, k, v)
        db.flush()
        print(f"  + Updated {min(3, len(clients))} clients with billing fields")

        today = date.today()

        # -- Purchase Orders --
        print("\nCreating purchase orders...")
        po_defs = [
            dict(po_number='PO-2025-001', client_id=clients[0].id,
                 description='Annual HVAC maintenance contract', status='active',
                 amount_authorized=20000.0, amount_used=0, issue_date=date(today.year, 1, 15),
                 expiry_date=date(today.year, 12, 31), department='Facilities',
                 cost_code='FAC-HVAC-2025'),
            dict(po_number='PO-2025-002', client_id=clients[0].id,
                 description='Emergency plumbing repairs', status='active',
                 amount_authorized=5000.0, amount_used=0, issue_date=date(today.year, 3, 1),
                 expiry_date=today + timedelta(days=15), department='Operations',
                 cost_code='OPS-PLUMB-2025'),
            dict(po_number='PO-2025-003', client_id=clients[1].id if len(clients) > 1 else clients[0].id,
                 description='Electrical panel upgrades', status='active',
                 amount_authorized=15000.0, amount_used=0, issue_date=date(today.year, 2, 1),
                 expiry_date=date(today.year, 8, 31), department='Capital Projects',
                 cost_code='CAP-ELEC-2025'),
            dict(po_number='PO-2024-099', client_id=clients[2].id if len(clients) > 2 else clients[0].id,
                 description='Data centre cooling - Phase 1', status='exhausted',
                 amount_authorized=8000.0, amount_used=8000.0, issue_date=date(today.year-1, 6, 1),
                 expiry_date=date(today.year-1, 12, 31), department='Infrastructure',
                 cost_code='INFRA-COOLING'),
            dict(po_number='PO-2024-050', client_id=clients[0].id,
                 description='2024 general maintenance (expired)', status='expired',
                 amount_authorized=10000.0, amount_used=3500.0, issue_date=date(today.year-1, 1, 1),
                 expiry_date=date(today.year-1, 12, 31), department='Facilities',
                 cost_code='FAC-GEN-2024'),
        ]

        created_pos = []
        for pd in po_defs:
            existing = db.query(PurchaseOrder).filter_by(po_number=pd['po_number']).first()
            if not existing:
                po = PurchaseOrder(organization_id=org_id, created_by=owner.id, **pd)
                db.add(po)
                created_pos.append(po)
            else:
                created_pos.append(existing)
        db.flush()
        print(f"  + {len([p for p in created_pos if p.id])} POs seeded")

        po1, po2, po3 = created_pos[0], created_pos[1], created_pos[2]

        # -- Commercial Invoices (various aging states) --
        print("\nCreating commercial invoices...")
        inv_counter = [0]

        def next_num():
            inv_counter[0] += 1
            return settings.next_invoice_number(db)

        inv_defs = [
            # Paid
            dict(invoice_number=next_num(), client_id=clients[0].id, po_id=po1.id,
                 po_number_display=po1.po_number, status='paid',
                 issued_date=datetime(today.year, 1, 20), due_date=datetime(today.year, 2, 19),
                 payment_terms='net_30', subtotal=2831.86, tax_rate=13, tax_amount=368.14,
                 total=3200.0, amount_paid=3200.0, balance_due=0,
                 department='Facilities', cost_code='FAC-HVAC-2025',
                 billing_contact='Sarah Chen', approval_status='approved',
                 approved_by=owner.id, approved_at=datetime.utcnow()),
            # Current (not yet due)
            dict(invoice_number=next_num(), client_id=clients[0].id, po_id=po1.id,
                 po_number_display=po1.po_number, status='sent',
                 issued_date=datetime.combine(today - timedelta(days=5), datetime.min.time()),
                 due_date=datetime.combine(today + timedelta(days=25), datetime.min.time()),
                 payment_terms='net_30', subtotal=1592.92, tax_rate=13, tax_amount=207.08,
                 total=1800.0, amount_paid=0, balance_due=1800.0,
                 department='Facilities', cost_code='FAC-HVAC-2025',
                 billing_contact='Sarah Chen', approval_status='approved',
                 approved_by=owner.id, approved_at=datetime.utcnow()),
            # 1-30 days overdue
            dict(invoice_number=next_num(), client_id=clients[1].id if len(clients) > 1 else clients[0].id,
                 po_id=po3.id, po_number_display=po3.po_number, status='overdue',
                 issued_date=datetime.combine(today - timedelta(days=45), datetime.min.time()),
                 due_date=datetime.combine(today - timedelta(days=15), datetime.min.time()),
                 payment_terms='net_30', subtotal=3761.06, tax_rate=13, tax_amount=488.94,
                 total=4250.0, amount_paid=0, balance_due=4250.0,
                 department='Capital Projects', cost_code='CAP-ELEC-2025',
                 billing_contact='Rick Webb', approval_status='approved',
                 approved_by=owner.id, approved_at=datetime.utcnow()),
            # 31-60 days overdue
            dict(invoice_number=next_num(), client_id=clients[1].id if len(clients) > 1 else clients[0].id,
                 status='overdue',
                 issued_date=datetime.combine(today - timedelta(days=80), datetime.min.time()),
                 due_date=datetime.combine(today - timedelta(days=40), datetime.min.time()),
                 payment_terms='net_45', subtotal=2566.37, tax_rate=13, tax_amount=333.63,
                 total=2900.0, amount_paid=0, balance_due=2900.0,
                 billing_contact='Rick Webb', approval_status='approved',
                 approved_by=owner.id, approved_at=datetime.utcnow()),
            # 61-90 days overdue (tax exempt)
            dict(invoice_number=next_num(), client_id=clients[2].id if len(clients) > 2 else clients[0].id,
                 po_number_display='PO-NDC-2024-77', status='overdue',
                 issued_date=datetime.combine(today - timedelta(days=120), datetime.min.time()),
                 due_date=datetime.combine(today - timedelta(days=70), datetime.min.time()),
                 payment_terms='net_60', subtotal=6100.0, tax_rate=0, tax_amount=0,
                 total=6100.0, amount_paid=0, balance_due=6100.0,
                 department='Infrastructure', cost_code='INFRA-COOLING',
                 billing_contact='Priya Okonkwo', approval_status='approved',
                 approved_by=owner.id, approved_at=datetime.utcnow()),
            # 90+ days overdue
            dict(invoice_number=next_num(), client_id=clients[2].id if len(clients) > 2 else clients[0].id,
                 po_number_display='PO-NDC-2024-55', status='overdue',
                 issued_date=datetime.combine(today - timedelta(days=180), datetime.min.time()),
                 due_date=datetime.combine(today - timedelta(days=120), datetime.min.time()),
                 payment_terms='net_60', subtotal=9800.0, tax_rate=0, tax_amount=0,
                 total=9800.0, amount_paid=0, balance_due=9800.0,
                 department='Infrastructure', cost_code='INFRA-NET',
                 billing_contact='Priya Okonkwo', approval_status='approved',
                 approved_by=owner.id, approved_at=datetime.utcnow()),
            # Pending approval (above threshold)
            dict(invoice_number=next_num(), client_id=clients[0].id, po_id=po2.id,
                 po_number_display=po2.po_number, status='draft',
                 issued_date=datetime.combine(today, datetime.min.time()),
                 due_date=datetime.combine(today + timedelta(days=30), datetime.min.time()),
                 payment_terms='net_30', subtotal=2035.40, tax_rate=13, tax_amount=264.60,
                 total=2300.0, amount_paid=0, balance_due=2300.0,
                 department='Operations', cost_code='OPS-PLUMB-2025',
                 billing_contact='Sarah Chen', approval_status='pending'),
            # Rejected
            dict(invoice_number=next_num(), client_id=clients[1].id if len(clients) > 1 else clients[0].id,
                 status='draft',
                 issued_date=datetime.combine(today - timedelta(days=3), datetime.min.time()),
                 due_date=datetime.combine(today + timedelta(days=27), datetime.min.time()),
                 payment_terms='net_30', subtotal=1327.43, tax_rate=13, tax_amount=172.57,
                 total=1500.0, amount_paid=0, balance_due=1500.0,
                 approval_status='rejected',
                 rejection_reason='Line items do not match the work order. Please resubmit with correct quantities.'),
        ]

        inv_count = 0
        for inv_data in inv_defs:
            existing = db.query(Invoice).filter_by(invoice_number=inv_data['invoice_number']).first()
            if not existing:
                inv = Invoice(organization_id=org_id, created_by_id=owner.id, **inv_data)
                db.add(inv)
                inv_count += 1
        db.flush()

        # Recalculate PO balances
        from web.utils.po_utils import recalculate_po_balance
        for po in [po1, po2, po3]:
            recalculate_po_balance(db, po)

        db.commit()

        # Summary
        print(f"\n  + {inv_count} invoices seeded (various aging states)")
        print(f"  + Approval threshold: ${settings.invoice_approval_threshold}")

        active_pos = db.query(PurchaseOrder).filter_by(
            organization_id=org_id, status='active'
        ).all()
        print(f"\nActive POs:")
        for po in active_pos:
            print(f"  {po.po_number}: ${po.amount_remaining:,.2f} remaining ({po.utilization_percentage:.0f}% used)")

        pending = db.query(Invoice).filter_by(
            organization_id=org_id, approval_status='pending'
        ).count()
        overdue = db.query(Invoice).filter_by(
            organization_id=org_id, status='overdue'
        ).count()
        print(f"\nPending approvals: {pending}")
        print(f"Overdue invoices: {overdue}")
        print("\nPhase 3 seeding complete.")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    seed()
