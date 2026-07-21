#!/usr/bin/env python3
"""Migration: Vehicle profiles, mileage/fuel logs, payroll periods/line items."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from models.database import engine, Base
from sqlalchemy import text, inspect
import models.vehicle_profile    # noqa
import models.vehicle_mileage_log  # noqa
import models.vehicle_fuel_log   # noqa
import models.payroll_period     # noqa
import models.payroll_line_item  # noqa


def run_migration():
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        insp = inspect(conn)
        tables = insp.get_table_names()

        for t in ('vehicle_profiles', 'vehicle_mileage_logs', 'vehicle_fuel_logs',
                  'payroll_periods', 'payroll_line_items'):
            if t in tables:
                cols = [c['name'] for c in insp.get_columns(t)]
                print(f"  [OK] {t} ({len(cols)} columns)")
            else:
                print(f"  [MISSING] {t}")

    print("\nVehicle & Payroll migration complete.")


if __name__ == '__main__':
    run_migration()
