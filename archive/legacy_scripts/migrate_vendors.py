#!/usr/bin/env python3
"""Migration: Vendor management tables + Part/Expense FK columns."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from models.database import engine, Base
from sqlalchemy import text, inspect
import models.vendor          # noqa
import models.vendor_price    # noqa
import models.supplier_po     # noqa
import models.vendor_payment  # noqa


def column_exists(conn, table, column):
    result = conn.execute(text("SELECT COUNT(*) FROM pragma_table_info(:t) WHERE name=:c"), {"t": table, "c": column})
    return result.scalar() > 0


def run_migration():
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        insp = inspect(conn)
        tables = insp.get_table_names()

        for t in ('vendors', 'vendor_prices', 'supplier_purchase_orders', 'supplier_po_line_items', 'vendor_payments'):
            if t in tables:
                cols = [c['name'] for c in insp.get_columns(t)]
                print(f"  [OK] {t} ({len(cols)} columns)")
            else:
                print(f"  [MISSING] {t}")

        # Add preferred_vendor_id to parts
        if 'parts' in tables and not column_exists(conn, 'parts', 'preferred_vendor_id'):
            conn.execute(text("ALTER TABLE parts ADD COLUMN preferred_vendor_id INTEGER REFERENCES vendors(id)"))
            print("  [PATCHED] parts.preferred_vendor_id")

        # Add vendor_id to expenses
        if 'expenses' in tables and not column_exists(conn, 'expenses', 'vendor_id'):
            conn.execute(text("ALTER TABLE expenses ADD COLUMN vendor_id INTEGER REFERENCES vendors(id)"))
            print("  [PATCHED] expenses.vendor_id")

    print("\nVendor migration complete.")


if __name__ == '__main__':
    run_migration()
