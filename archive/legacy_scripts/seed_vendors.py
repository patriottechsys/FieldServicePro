#!/usr/bin/env python3
"""Seed: Vendors, vendor pricing, supplier POs, and payments."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta
from models.database import get_session
from models.vendor import Vendor
from models.vendor_price import VendorPrice
from models.supplier_po import SupplierPurchaseOrder, SupplierPOLineItem
from models.vendor_payment import VendorPayment
from models.part import Part
from models.user import User


SAMPLE_VENDORS = [
    {
        'company_name': 'Northern HVAC Supply',
        'vendor_type': 'parts_supplier', 'status': 'preferred',
        'contact_name': 'Mike Chen', 'contact_email': 'mike@northernhvac.ca',
        'contact_phone': '416-555-0101', 'phone': '416-555-0100',
        'email': 'orders@northernhvac.ca', 'website': 'https://northernhvac.ca',
        'address_line1': '150 Industrial Blvd', 'city': 'Toronto',
        'state_province': 'ON', 'postal_code': 'M5V 2T3', 'country': 'Canada',
        'payment_terms': 'net_30', 'currency': 'CAD',
        'quality_rating': 5, 'delivery_rating': 4, 'price_rating': 4,
        'insurance_verified': True, 'insurance_expiry': date.today() + timedelta(days=200),
        'notes': 'Primary HVAC parts supplier. Excellent quality, fast turnaround.',
    },
    {
        'company_name': 'ProPlumb Distributors',
        'vendor_type': 'parts_supplier', 'status': 'active',
        'contact_name': 'Sarah Williams', 'contact_email': 'sarah@proplumb.ca',
        'contact_phone': '905-555-0201', 'phone': '905-555-0200',
        'email': 'sales@proplumb.ca',
        'address_line1': '88 Plumber Lane', 'city': 'Mississauga',
        'state_province': 'ON', 'postal_code': 'L5B 3C7',
        'payment_terms': 'net_30', 'currency': 'CAD',
        'quality_rating': 4, 'delivery_rating': 4, 'price_rating': 3,
        'insurance_verified': True, 'insurance_expiry': date.today() + timedelta(days=120),
    },
    {
        'company_name': 'ElectroParts Ontario',
        'vendor_type': 'parts_supplier', 'status': 'active',
        'contact_name': 'James Park', 'contact_email': 'james@electroparts.ca',
        'contact_phone': '647-555-0301', 'phone': '647-555-0300',
        'email': 'orders@electroparts.ca',
        'address_line1': '220 Circuit Dr', 'city': 'Brampton',
        'state_province': 'ON', 'postal_code': 'L6T 4K8',
        'payment_terms': 'net_45', 'currency': 'CAD',
        'quality_rating': 4, 'delivery_rating': 3, 'price_rating': 5,
        'insurance_verified': True, 'insurance_expiry': date.today() + timedelta(days=300),
    },
    {
        'company_name': 'CanWaste Solutions',
        'vendor_type': 'waste_disposal', 'status': 'active',
        'contact_name': 'Tom Fraser', 'contact_email': 'tom@canwaste.ca',
        'contact_phone': '416-555-0401', 'phone': '416-555-0400',
        'address_line1': '500 Recycling Rd', 'city': 'Toronto',
        'state_province': 'ON', 'postal_code': 'M4B 1B3',
        'payment_terms': 'net_15', 'currency': 'CAD',
        'quality_rating': 3, 'delivery_rating': 3, 'price_rating': 4,
    },
    {
        'company_name': 'Atlas Equipment Rentals',
        'vendor_type': 'equipment_rental', 'status': 'preferred',
        'contact_name': 'Diana Rodriguez', 'contact_email': 'diana@atlasrental.ca',
        'contact_phone': '905-555-0501', 'phone': '905-555-0500',
        'email': 'booking@atlasrental.ca', 'website': 'https://atlasrental.ca',
        'address_line1': '75 Equipment Way', 'city': 'Hamilton',
        'state_province': 'ON', 'postal_code': 'L8N 3T7',
        'payment_terms': 'due_on_receipt', 'currency': 'CAD',
        'quality_rating': 5, 'delivery_rating': 5, 'price_rating': 3,
        'insurance_verified': True, 'insurance_expiry': date.today() + timedelta(days=365),
    },
    {
        'company_name': 'RapidFix Subcontracting',
        'vendor_type': 'subcontractor', 'status': 'active',
        'contact_name': 'Kevin Osei', 'contact_email': 'kevin@rapidfix.ca',
        'contact_phone': '416-555-0601',
        'address_line1': '30 Trades Blvd', 'city': 'Toronto',
        'state_province': 'ON', 'postal_code': 'M6K 2W1',
        'payment_terms': 'net_30', 'currency': 'CAD',
        'quality_rating': 4, 'delivery_rating': 3, 'price_rating': 4,
        'wsib_verified': True, 'wsib_number': 'WSIB-2024-8832',
    },
    {
        'company_name': 'Shell Fleet Fueling',
        'vendor_type': 'fuel', 'status': 'active',
        'contact_name': 'Fleet Services', 'contact_email': 'fleet@shell.ca',
        'contact_phone': '1-800-555-0700',
        'address_line1': '1 Shell Plaza', 'city': 'Calgary',
        'state_province': 'AB', 'postal_code': 'T2P 4H5', 'country': 'Canada',
        'payment_terms': 'net_15', 'currency': 'CAD',
        'quality_rating': 4, 'delivery_rating': 5, 'price_rating': 3,
    },
    {
        'company_name': 'AllSafe Insurance Brokers',
        'vendor_type': 'insurance', 'status': 'on_hold',
        'contact_name': 'Priya Sharma', 'contact_email': 'priya@allsafe.ca',
        'contact_phone': '416-555-0801',
        'address_line1': '400 Bay St Suite 1200', 'city': 'Toronto',
        'state_province': 'ON', 'postal_code': 'M5H 2Y4',
        'payment_terms': 'due_on_receipt', 'currency': 'CAD',
        'notes': 'On hold - reviewing renewal terms for 2026.',
    },
]


def seed_vendors():
    db = get_session()
    try:
        existing = db.query(Vendor).count()
        if existing > 0:
            print(f"  Vendors already seeded ({existing} found). Skipping.")
            return

        user = db.query(User).first()
        user_id = user.id if user else None

        # Create vendors
        vendors = []
        for i, data in enumerate(SAMPLE_VENDORS, 1):
            v = Vendor(
                vendor_number=f"VND-{date.today().year}-{i:04d}",
                created_by=user_id,
                is_active=data.get('status') != 'on_hold',
                **{k: v for k, v in data.items()},
            )
            db.add(v)
            vendors.append(v)

        db.flush()
        print(f"  Created {len(vendors)} vendors")

        # Add pricing records (link first 3 vendors to parts if available)
        parts = db.query(Part).limit(6).all()
        price_count = 0
        if parts:
            for part in parts[:4]:
                for vi, vendor in enumerate(vendors[:3]):
                    base = float(part.cost_price or 10) * (0.9 + vi * 0.1)
                    vp = VendorPrice(
                        vendor_id=vendor.id,
                        part_id=part.id,
                        unit_price=round(base, 2),
                        bulk_price=round(base * 0.9, 2) if vi < 2 else None,
                        bulk_threshold=10 if vi < 2 else None,
                        lead_time_days=[1, 3, 5][vi],
                        is_preferred=(vi == 0),
                        vendor_part_number=f"{vendor.company_name[:3].upper()}-{part.part_number}" if part.part_number else None,
                    )
                    db.add(vp)
                    price_count += 1
            print(f"  Created {price_count} vendor price records")

        # Create 4 supplier POs
        po_data = [
            {'vendor_idx': 0, 'status': 'received', 'days_ago': 30,
             'items': [('HVAC Filter - 20x25x1', 20, 12.50), ('Refrigerant R-410A', 5, 85.00)]},
            {'vendor_idx': 1, 'status': 'submitted', 'days_ago': 5,
             'items': [('Copper Pipe 1/2" x 10ft', 50, 8.75), ('PVC Elbow 90deg 2"', 100, 2.40)]},
            {'vendor_idx': 2, 'status': 'partially_received', 'days_ago': 15,
             'items': [('Circuit Breaker 20A', 30, 14.99), ('Conduit EMT 1" x 10ft', 40, 6.50)]},
            {'vendor_idx': 0, 'status': 'draft', 'days_ago': 0,
             'items': [('Thermostat - Smart WiFi', 10, 129.99)]},
        ]

        pos = []
        for i, pd in enumerate(po_data, 1):
            vendor = vendors[pd['vendor_idx']]
            order_date = date.today() - timedelta(days=pd['days_ago'])
            po = SupplierPurchaseOrder(
                po_number=f"SPO-{date.today().year}-{i:04d}",
                vendor_id=vendor.id,
                status=pd['status'],
                order_date=order_date,
                expected_delivery_date=order_date + timedelta(days=14),
                tax_rate=13.0,
                shipping_cost=25.00 if i <= 2 else 0,
                payment_terms=vendor.payment_terms,
                payment_due_date=order_date + timedelta(days=vendor.payment_days),
                created_by=user_id,
                requested_by=user_id,
            )
            if pd['status'] == 'received':
                po.actual_delivery_date = order_date + timedelta(days=10)
            db.add(po)
            db.flush()

            for j, (desc, qty, price) in enumerate(pd['items']):
                li = SupplierPOLineItem(
                    po_id=po.id,
                    description=desc,
                    quantity_ordered=qty,
                    quantity_received=qty if pd['status'] == 'received' else (qty // 2 if pd['status'] == 'partially_received' else 0),
                    unit_price=price,
                    sort_order=j,
                )
                if pd['status'] == 'received':
                    li.received_date = po.actual_delivery_date
                db.add(li)

            db.flush()
            po.recalculate_totals()
            pos.append(po)

        print(f"  Created {len(pos)} supplier POs")

        # Create 2 payments (for the received PO)
        received_po = pos[0]
        pay1 = VendorPayment(
            payment_number=f"VP-{date.today().year}-0001",
            vendor_id=received_po.vendor_id,
            po_id=received_po.id,
            amount=round(float(received_po.total) * 0.6, 2),
            payment_date=received_po.order_date + timedelta(days=15),
            payment_method='bank_transfer',
            reference_number='EFT-20260315',
            memo='Partial payment per terms',
            status='completed',
            created_by=user_id,
        )
        pay2 = VendorPayment(
            payment_number=f"VP-{date.today().year}-0002",
            vendor_id=received_po.vendor_id,
            po_id=received_po.id,
            amount=round(float(received_po.total) * 0.4, 2),
            payment_date=received_po.order_date + timedelta(days=28),
            payment_method='bank_transfer',
            reference_number='EFT-20260328',
            memo='Final payment',
            status='completed',
            created_by=user_id,
        )
        db.add_all([pay1, pay2])
        db.flush()

        # Update paid amounts
        received_po.amount_paid = round(pay1.amount + pay2.amount, 2)
        received_po.payment_status = 'paid'

        # Update vendor balances
        for po in pos:
            if po.status not in ('cancelled', 'draft'):
                vendor = db.query(Vendor).filter_by(id=po.vendor_id).first()
                if vendor:
                    vendor.current_balance = float(vendor.current_balance or 0) + po.balance_due

        db.commit()
        print(f"  Created 2 vendor payments")
        print("  Vendor seed complete!")

    except Exception as e:
        db.rollback()
        print(f"  ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == '__main__':
    print("Seeding vendor data...")
    seed_vendors()
    print("Done!")
