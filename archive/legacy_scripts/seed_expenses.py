#!/usr/bin/env python3
"""Seed data: Expenses."""
import sys, os, random
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import get_session, Base, engine
from models.expense import Expense
from models.job import Job
from models.user import User


def seed():
    Base.metadata.create_all(engine)
    db = get_session()
    try:
        admin = db.query(User).first()
        if not admin:
            print("No users found.")
            return

        if db.query(Expense).count() > 0:
            print(f"Already have {db.query(Expense).count()} expenses. Skipping.")
            return

        org_id = admin.organization_id
        today = date.today()
        year = today.year
        random.seed(42)

        jobs = db.query(Job).filter_by(organization_id=org_id).limit(10).all()

        expenses_data = [
            ('Excavator rental — 2 days', 'equipment_rental', 850, 110.50, True, 15, 'ABC Rentals'),
            ('Dumpster rental — debris disposal', 'disposal', 450, 58.50, True, 10, 'WM Services'),
            ('Subcontractor — drywall finishing', 'subcontractor', 1200, 0, True, 0, 'Dave Drywall Co'),
            ('Plumbing permit — City of KW', 'permit_fee', 175, 0, False, 0, 'City of Kitchener'),
            ('Fuel for service van', 'fuel_mileage', 85.50, 0, False, 0, 'Shell'),
            ('Electrical inspection fee', 'inspection_fee', 225, 0, True, 10, 'ESA Ontario'),
            ('Copper fittings — Home Depot', 'supplies', 67.50, 8.78, True, 20, 'Home Depot'),
            ('Team lunch — overtime crew', 'meals', 45.00, 5.85, False, 0, 'Tim Hortons'),
            ('Parking — downtown job site', 'parking', 24.00, 0, False, 0, 'Impark'),
            ('Shipping — specialty parts', 'shipping', 35.00, 4.55, True, 0, 'UPS'),
            ('Temp power hookup', 'utility_connection', 350, 45.50, True, 10, 'Waterloo Hydro'),
            ('Safety harnesses — new set', 'tools', 189.99, 24.70, False, 0, 'Safety Supply'),
            ('Porta-potty rental — job site', 'temporary_services', 275, 35.75, True, 10, 'Blue Line'),
            ('Office supplies — project binders', 'office_supplies', 32.50, 4.23, False, 0, 'Staples'),
            ('Concrete delivery', 'other', 680, 88.40, True, 15, 'Lafarge'),
        ]

        seq = 0
        for title, cat, amount, tax, billable, markup, vendor in expenses_data:
            seq += 1
            job = random.choice(jobs) if jobs else None
            days_ago = random.randint(1, 30)
            status = random.choice(['draft', 'submitted', 'approved', 'approved', 'approved'])

            exp = Expense(
                expense_number=f"EXP-{year}-{seq:04d}",
                title=title, expense_category=cat,
                amount=amount, tax_amount=tax,
                is_billable=billable, markup_percentage=markup,
                vendor_name=vendor, payment_method='company_card',
                expense_date=today - timedelta(days=days_ago),
                status=status,
                submitted_date=(today - timedelta(days=days_ago - 1)) if status != 'draft' else None,
                approved_date=(today - timedelta(days=days_ago - 2)) if status == 'approved' else None,
                approved_by=admin.id if status == 'approved' else None,
                job_id=job.id if job else None,
                client_id=job.client_id if job else None,
                division_id=job.division_id if job else None,
                paid_by=admin.id,
                created_by=admin.id,
            )
            exp.compute_totals()
            db.add(exp)

        db.commit()
        print(f"Created {seq} expenses.")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    seed()
