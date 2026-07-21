#!/usr/bin/env python3
"""Migration: Notification system tables + settings columns."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from models.database import engine, Base
from sqlalchemy import text, inspect
import models.notification  # noqa


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

        for t in ('notifications', 'notification_preferences', 'client_notification_templates', 'notification_logs'):
            if t in tables:
                cols = [c['name'] for c in insp.get_columns(t)]
                print(f"  [OK] {t} ({len(cols)} columns)")
            else:
                print(f"  [MISSING] {t}")

        if 'organization_settings' in tables:
            for col, defn in [
                ('notifications_enabled', 'BOOLEAN NOT NULL DEFAULT 1'),
                ('client_notifications_enabled', 'BOOLEAN NOT NULL DEFAULT 1'),
                ('email_from_name', 'VARCHAR(100)'),
                ('email_from_address', 'VARCHAR(255)'),
                ('email_reply_to', 'VARCHAR(255)'),
                ('sms_enabled', 'BOOLEAN NOT NULL DEFAULT 0'),
                ('sms_provider', 'VARCHAR(20)'),
                ('sms_api_key', 'VARCHAR(500)'),
                ('sms_from_number', 'VARCHAR(20)'),
                ('notification_polling_interval', 'INTEGER NOT NULL DEFAULT 30'),
                ('appointment_reminder_hours', 'INTEGER NOT NULL DEFAULT 24'),
                ('invoice_reminder_days', "VARCHAR(50) DEFAULT '[7, 14, 30]'"),
            ]:
                if not column_exists(conn, 'organization_settings', col):
                    conn.execute(text(f"ALTER TABLE organization_settings ADD COLUMN {col} {defn}"))
                    print(f"  [PATCHED] organization_settings.{col}")

    print("\nNotification migration complete.")


if __name__ == '__main__':
    run_migration()
