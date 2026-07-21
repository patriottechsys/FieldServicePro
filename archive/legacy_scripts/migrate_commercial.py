#!/usr/bin/env python3
"""
migrate_commercial.py
Apply the commercial invoicing schema additions.
Usage: python migrate_commercial.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import Base, engine
from models import (
    PurchaseOrder, POAttachment, AppSettings,
    Client, Invoice, PaymentTerms, ApprovalStatus,
)
from sqlalchemy import text, inspect


def column_exists(insp, table, column):
    cols = [c['name'] for c in insp.get_columns(table)]
    return column in cols


def table_exists(insp, table):
    return table in insp.get_table_names()


def migrate():
    print("=== FieldServicePro: Commercial Invoicing Migration ===\n")

    # Create all new tables first (safe -- won't drop existing)
    Base.metadata.create_all(engine)
    print("Tables ensured: purchase_orders, po_attachments, app_settings")

    insp = inspect(engine)

    with engine.connect() as c:
        # -- clients table additions --
        client_additions = [
            ("default_payment_terms", "VARCHAR(20) DEFAULT 'net_30'"),
            ("custom_payment_days", "INTEGER"),
            ("credit_limit", "REAL"),
            ("tax_exempt", "BOOLEAN DEFAULT 0"),
            ("tax_exempt_number", "VARCHAR(100)"),
            ("billing_email", "VARCHAR(255)"),
            ("billing_contact_name", "VARCHAR(200)"),
            ("billing_contact_phone", "VARCHAR(50)"),
            ("require_po", "BOOLEAN DEFAULT 0"),
        ]
        print("\nAdding billing columns to clients table...")
        for col, col_type in client_additions:
            if not column_exists(insp, "clients", col):
                c.execute(text(f"ALTER TABLE clients ADD COLUMN {col} {col_type}"))
                print(f"  + clients.{col}")
            else:
                print(f"  - clients.{col} already exists")

        # -- invoices table additions --
        invoice_additions = [
            ("po_id", "INTEGER REFERENCES purchase_orders(id)"),
            ("po_number_display", "VARCHAR(100)"),
            ("payment_terms", "VARCHAR(20)"),
            ("cost_code", "VARCHAR(100)"),
            ("department", "VARCHAR(100)"),
            ("billing_contact", "VARCHAR(200)"),
            ("approval_status", "VARCHAR(20) DEFAULT 'not_required'"),
            ("approved_by", "INTEGER REFERENCES users(id)"),
            ("approved_at", "DATETIME"),
            ("rejection_reason", "TEXT"),
            ("late_fee_rate", "REAL"),
            ("late_fee_applied", "REAL DEFAULT 0"),
            ("late_fee_date", "DATE"),
        ]
        print("\nAdding commercial columns to invoices table...")
        for col, col_type in invoice_additions:
            if not column_exists(insp, "invoices", col):
                c.execute(text(f"ALTER TABLE invoices ADD COLUMN {col} {col_type}"))
                print(f"  + invoices.{col}")
            else:
                print(f"  - invoices.{col} already exists")

        # -- Seed default app_settings --
        existing_settings = c.execute(text("SELECT COUNT(*) FROM app_settings")).scalar()
        if existing_settings == 0:
            print("\nSeeding default app_settings...")
            default_settings = [
                ("invoice_approval_threshold", "1000.00", "decimal",
                 "Invoices above this amount require internal approval (NULL = no approval needed)"),
                ("invoice_approval_roles", '["owner", "admin"]', "json",
                 "Roles that can approve invoices"),
                ("late_fee_rate_default", "1.5", "decimal",
                 "Default late fee rate percentage per period"),
                ("statement_footer_text",
                 "Thank you for your business. Please remit payment by the due date.",
                 "string", "Footer text on client statements"),
                ("company_name", "FieldServicePro", "string", "Company name on documents"),
                ("company_address", "", "string", "Company address on statements/invoices"),
                ("company_phone", "", "string", "Company phone on documents"),
                ("company_email", "", "string", "Company billing email"),
            ]
            for key, val, vtype, desc in default_settings:
                c.execute(text(
                    "INSERT INTO app_settings (key, value, value_type, description) "
                    "VALUES (:k, :v, :vt, :d)"
                ), {"k": key, "v": val, "vt": vtype, "d": desc})
            print(f"  + {len(default_settings)} default settings seeded")
        else:
            print(f"\n- app_settings already has {existing_settings} rows, skipping seed")

        c.commit()

    print("\nMigration complete.")


if __name__ == '__main__':
    migrate()
