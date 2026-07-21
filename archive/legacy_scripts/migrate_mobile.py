"""
Migration: Mobile view — ensure required columns and tables exist.
Run: python migrate_mobile.py
"""
import sqlite3
import os

DB_PATH = os.environ.get('DATABASE_URL', 'fieldservicepro.db')
if DB_PATH.startswith('sqlite:///'):
    DB_PATH = DB_PATH.replace('sqlite:///', '')


def migrate():
    """Add missing columns and tables for mobile views."""
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ── Column additions (idempotent) ──
    alterations = [
        ("jobs", "portal_access_instructions", "TEXT"),
        ("jobs", "started_at", "DATETIME"),
        ("jobs", "completed_at", "DATETIME"),
        ("time_entries", "source", "VARCHAR(20) DEFAULT 'manual'"),
    ]

    for table, column, col_type in alterations:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            print(f"  Added {table}.{column}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                pass
            else:
                print(f"  Skip {table}.{column}: {e}")

    # ── RestockRequest table ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS restock_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            technician_id INTEGER NOT NULL REFERENCES users(id),
            part_id INTEGER NOT NULL REFERENCES parts(id),
            quantity_requested REAL NOT NULL DEFAULT 1,
            notes TEXT,
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  Ensured restock_requests table exists")

    conn.commit()
    conn.close()
    print("Mobile migration complete.")


if __name__ == '__main__':
    migrate()
