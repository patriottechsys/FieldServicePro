#!/usr/bin/env python3
"""
seed_portal.py — Seed data for client portal demo.
Run: python seed_portal.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import get_session, Base, engine
from models import (
    Client, Property, PortalUser, PortalSettings,
)


def seed():
    # Ensure tables exist
    Base.metadata.create_all(engine)

    db = get_session()
    try:
        print("=== Seeding Portal Data ===\n")

        # Ensure portal settings exist and are enabled
        settings = db.query(PortalSettings).first()
        if not settings:
            settings = PortalSettings()
            db.add(settings)
            db.flush()

        settings.portal_enabled = True
        settings.welcome_message = (
            'Welcome to your client portal! Here you can track jobs, '
            'review quotes, view invoices, and communicate with our team.'
        )
        settings.payment_instructions = (
            'Payment can be made by:\n'
            '- ACH Transfer: Routing 123456789, Account 987654321\n'
            '- Check: Mail to 123 Service St, Suite 100, Your City, ST 12345\n'
            '- Credit Card: Call (555) 123-4567'
        )
        settings.company_contact_info = 'FieldServicePro Demo | (555) 123-4567 | support@fieldservicepro.demo'
        settings.allow_service_requests = True
        settings.allow_quote_approval = True
        settings.allow_change_order_approval = True
        db.commit()
        print("  + Portal settings configured (enabled)")

        # Get or create a client
        client = db.query(Client).first()
        if not client:
            print("  ! No clients found — create clients first via the main app")
            return

        print(f"  Using client: {client.display_name} (id={client.id})")

        # Create properties for the client
        properties_data = [
            {'name': 'Main Office', 'address': '100 Corporate Blvd', 'city': 'Springfield',
             'province': 'IL', 'postal_code': '62701', 'property_type': 'commercial'},
            {'name': 'Warehouse A', 'address': '200 Industrial Ave', 'city': 'Springfield',
             'province': 'IL', 'postal_code': '62702', 'property_type': 'industrial'},
            {'name': 'Downtown Branch', 'address': '50 Main Street', 'city': 'Springfield',
             'province': 'IL', 'postal_code': '62703', 'property_type': 'commercial'},
        ]

        prop_count = 0
        for pd in properties_data:
            if not db.query(Property).filter_by(client_id=client.id, name=pd['name']).first():
                db.add(Property(client_id=client.id, **pd))
                prop_count += 1
        if prop_count:
            db.flush()
            print(f"  + {prop_count} properties created")

        # Create portal users
        portal_users_data = [
            {
                'email': 'john.primary@acmecorp.com',
                'first_name': 'John', 'last_name': 'Anderson',
                'role': 'primary', 'phone': '(555) 100-0001',
            },
            {
                'email': 'sarah.manager@acmecorp.com',
                'first_name': 'Sarah', 'last_name': 'Chen',
                'role': 'manager', 'phone': '(555) 100-0002',
            },
            {
                'email': 'mike.standard@acmecorp.com',
                'first_name': 'Mike', 'last_name': 'Johnson',
                'role': 'standard',
            },
            {
                'email': 'lisa.billing@acmecorp.com',
                'first_name': 'Lisa', 'last_name': 'Williams',
                'role': 'billing_only',
            },
            {
                'email': 'dave.viewer@acmecorp.com',
                'first_name': 'Dave', 'last_name': 'Brown',
                'role': 'view_only',
            },
        ]

        user_count = 0
        for pu_data in portal_users_data:
            if not db.query(PortalUser).filter_by(email=pu_data['email']).first():
                pu = PortalUser(
                    client_id=client.id,
                    invitation_accepted=True,
                    **pu_data,
                )
                pu.set_password('Portal123')
                db.add(pu)
                user_count += 1
                print(f"  + Created: {pu_data['email']} ({pu_data['role']})")
            else:
                print(f"  = Exists: {pu_data['email']}")

        db.commit()
        print(f"\n  {user_count} new portal users created")

        print("\n=== Portal Seed Complete ===")
        print("\nTest accounts (password: Portal123):")
        print("  Primary:     john.primary@acmecorp.com")
        print("  Manager:     sarah.manager@acmecorp.com")
        print("  Standard:    mike.standard@acmecorp.com")
        print("  Billing:     lisa.billing@acmecorp.com")
        print("  View Only:   dave.viewer@acmecorp.com")
        print("\nPortal URL: /portal/login")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == '__main__':
    seed()
