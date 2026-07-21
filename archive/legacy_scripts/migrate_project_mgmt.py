#!/usr/bin/env python3
"""Migration: RFI, Submittal, PunchList, PunchListItem, DailyLog tables."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from models.database import engine, Base
from sqlalchemy import inspect
import models.rfi          # noqa
import models.submittal    # noqa
import models.punch_list   # noqa
import models.daily_log    # noqa


def run_migration():
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        insp = inspect(conn)
        tables = insp.get_table_names()

        for t in ('rfis', 'submittals', 'punch_lists', 'punch_list_items', 'daily_logs'):
            if t in tables:
                cols = [c['name'] for c in insp.get_columns(t)]
                print(f"  [OK] {t} ({len(cols)} columns)")
            else:
                print(f"  [MISSING] {t}")

    print("\nProject management migration complete.")


if __name__ == '__main__':
    run_migration()
