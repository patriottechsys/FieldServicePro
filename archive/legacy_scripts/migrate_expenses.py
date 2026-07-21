#!/usr/bin/env python3
"""Migration: Expense Tracking tables + settings columns."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from models.database import engine, Base
from sqlalchemy import text, inspect
import models.expense  # noqa


def column_exists(conn, table, column):
    result = conn.execute(text(
        "SELECT COUNT(*) FROM pragma_table_info(:t) WHERE name=:c"
    ), {"t": table, "c": column})
    return result.scalar() > 0


def run_migration():
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        insp = inspect(conn)
        tables = insp.get_table_names()

        for t in ('expenses', 'mileage_entries'):
            if t in tables:
                cols = [c['name'] for c in insp.get_columns(t)]
                print(f"  [OK] {t} ({len(cols)} columns)")
            else:
                print(f"  [MISSING] {t}")

        if 'organization_settings' in tables:
            for col, defn in [
                ('expense_approval_threshold', 'NUMERIC(10,2) DEFAULT 100.00'),
                ('expense_receipt_required_threshold', 'NUMERIC(10,2) DEFAULT 25.00'),
                ('mileage_rate', 'NUMERIC(6,4) DEFAULT 0.6700'),
                ('default_expense_markup', 'NUMERIC(5,2) DEFAULT 15.00'),
                ('expense_approval_roles', "VARCHAR(100) DEFAULT 'owner,admin'"),
            ]:
                if not column_exists(conn, 'organization_settings', col):
                    conn.execute(text(f"ALTER TABLE organization_settings ADD COLUMN {col} {defn}"))
                    print(f"  [PATCHED] organization_settings.{col}")

    print("\nExpense migration complete.")


if __name__ == '__main__':
    run_migration()
