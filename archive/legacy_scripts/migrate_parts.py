#!/usr/bin/env python3
"""Migration script — create/recreate Parts & Materials tables."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import Base, engine
from models import (
    Part, InventoryLocation, InventoryStock, InventoryTransaction,
    JobMaterial, StockTransfer, StockTransferItem,
)

def migrate():
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    existing = inspector.get_table_names()

    # Check if stock_transfer_items needs schema update
    if 'stock_transfer_items' in existing:
        cols = {c['name'] for c in inspector.get_columns('stock_transfer_items')}
        if 'quantity' in cols and 'quantity_requested' not in cols:
            print("Transfer items schema changed — dropping transfer tables...")
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS stock_transfer_items"))
                conn.execute(text("DROP TABLE IF EXISTS stock_transfers"))
            print("  Dropped old transfer tables.")

    # Check if job_materials needs schema update
    if 'job_materials' in existing:
        cols = {c['name'] for c in inspector.get_columns('job_materials')}
        if 'quantity_used' in cols or 'custom_description' not in cols:
            print("Job materials schema changed — dropping table...")
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS job_materials"))
            print("  Dropped old job_materials table.")

    # Check if parts needs schema update
    if 'parts' in existing:
        cols = {c['name'] for c in inspector.get_columns('parts')}
        if 'unit_cost' in cols or 'trade' not in cols:
            print("Parts schema changed — dropping parts table...")
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS parts"))
            print("  Dropped old parts table.")

    print("Creating Parts & Materials tables...")
    Base.metadata.create_all(engine)

    # Verify all tables
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    expected = [
        'parts', 'inventory_locations', 'inventory_stock',
        'inventory_transactions', 'job_materials',
        'stock_transfers', 'stock_transfer_items',
    ]

    for t in expected:
        if t in tables:
            cols = [c['name'] for c in inspector.get_columns(t)]
            print(f"  [OK] {t} ({len(cols)} columns)")
        else:
            print(f"  [MISSING] {t}")

    print("\nMigration complete.")


if __name__ == '__main__':
    migrate()
