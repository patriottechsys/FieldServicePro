#!/usr/bin/env python3
"""Seed data: Parts catalog, inventory locations, stock levels, job materials, transfers."""
import sys, os, random
from datetime import datetime, timedelta, date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import get_session, Base, engine
from models.part import Part
from models.inventory import InventoryLocation, InventoryStock, InventoryTransaction
from models.job_material import JobMaterial
from models.stock_transfer import StockTransfer, StockTransferItem
from models.technician import Technician
from models.user import User
from models.job import Job


def seed():
    Base.metadata.create_all(engine)
    db = get_session()
    try:
        admin = db.query(User).first()
        if not admin:
            print("No users found. Run main seed first.")
            return
        org_id = admin.organization_id
        admin_id = admin.id

        # ── 1. PARTS CATALOG ─────────────────────────────────────────────
        print("[1/5] Parts catalog...")
        parts_data = [
            # Plumbing
            ('PRT-PLM-0001', '3/4" Copper 90 Elbow', 'pipe_fittings', 'plumbing', 'each', 2.50, 100.0, 5.00, 20, 'Mueller Industries'),
            ('PRT-PLM-0002', '1/2" Copper Tee', 'pipe_fittings', 'plumbing', 'each', 3.00, 100.0, 6.00, 15, 'Mueller Industries'),
            ('PRT-PLM-0003', '3/4" Ball Valve', 'valves', 'plumbing', 'each', 12.00, 100.0, 24.00, 10, 'Apollo'),
            ('PRT-PLM-0004', '3/4" SharkBite Coupling', 'pipe_fittings', 'plumbing', 'each', 8.50, 100.0, 17.00, 10, 'SharkBite'),
            ('PRT-PLM-0005', '1/2" PEX Tubing', 'pipe_fittings', 'plumbing', 'foot', 0.75, 100.0, 1.50, 200, 'Uponor'),
            ('PRT-PLM-0006', 'P-Trap 1-1/2"', 'fixtures', 'plumbing', 'each', 6.00, 100.0, 12.00, 5, None),
            ('PRT-PLM-0007', 'Wax Ring (toilet)', 'fixtures', 'plumbing', 'each', 3.50, 128.6, 8.00, 8, 'Fluidmaster'),
            ('PRT-PLM-0008', 'Water Heater Anode Rod', 'fixtures', 'plumbing', 'each', 25.00, 100.0, 50.00, 4, 'Camco'),
            ('PRT-PLM-0009', 'Backflow Preventer 3/4"', 'valves', 'plumbing', 'each', 85.00, 100.0, 170.00, 3, 'Watts'),
            ('PRT-PLM-0010', 'Sump Pump 1/3HP', 'fixtures', 'plumbing', 'each', 120.00, 108.3, 250.00, 2, 'Wayne'),
            # HVAC
            ('PRT-HVAC-0001', 'Furnace Filter 16x25x1', 'hvac_components', 'hvac', 'each', 8.00, 100.0, 16.00, 20, 'Filtrete'),
            ('PRT-HVAC-0002', 'Refrigerant R-410A (25lb)', 'hvac_components', 'hvac', 'each', 150.00, 100.0, 300.00, 2, 'Chemours'),
            ('PRT-HVAC-0003', 'Condensate Pump', 'hvac_components', 'hvac', 'each', 45.00, 111.1, 95.00, 3, 'Little Giant'),
            ('PRT-HVAC-0004', 'Thermostat Wire 18/5 (250ft)', 'wire_cable', 'hvac', 'roll', 55.00, 100.0, 110.00, 3, None),
            ('PRT-HVAC-0005', 'Smart Thermostat', 'controls_thermostats', 'hvac', 'each', 130.00, 111.5, 275.00, 2, 'Ecobee'),
            ('PRT-HVAC-0006', 'Capacitor 40/5 MFD', 'hvac_components', 'hvac', 'each', 15.00, 133.3, 35.00, 8, None),
            ('PRT-HVAC-0007', 'Contactor 2-Pole 40A', 'controls_thermostats', 'hvac', 'each', 18.00, 122.2, 40.00, 5, None),
            ('PRT-HVAC-0008', 'Flex Duct 6" (25ft)', 'ductwork', 'hvac', 'roll', 35.00, 100.0, 70.00, 4, None),
            ('PRT-HVAC-0009', 'Condensing Unit Fan Motor', 'hvac_components', 'hvac', 'each', 95.00, 110.5, 200.00, 2, None),
            # Electrical
            ('PRT-ELEC-0001', '14/2 Romex NMD Wire (75m)', 'wire_cable', 'electrical', 'roll', 85.00, 100.0, 170.00, 3, 'Southwire'),
            ('PRT-ELEC-0002', '12/2 Romex NMD Wire (75m)', 'wire_cable', 'electrical', 'roll', 110.00, 100.0, 220.00, 3, 'Southwire'),
            ('PRT-ELEC-0003', '15A Breaker (single pole)', 'electrical', 'electrical', 'each', 8.00, 125.0, 18.00, 10, 'Square D'),
            ('PRT-ELEC-0004', '20A Breaker (single pole)', 'electrical', 'electrical', 'each', 10.00, 120.0, 22.00, 10, 'Square D'),
            ('PRT-ELEC-0005', '200A Main Panel', 'electrical', 'electrical', 'each', 280.00, 100.0, 560.00, 1, 'Square D'),
            ('PRT-ELEC-0006', 'Duplex Outlet 15A', 'electrical', 'electrical', 'each', 1.50, 233.3, 5.00, 30, 'Leviton'),
            ('PRT-ELEC-0007', 'GFCI Outlet 15A', 'electrical', 'electrical', 'each', 18.00, 122.2, 40.00, 10, 'Leviton'),
            ('PRT-ELEC-0008', 'LED Recessed Light 4"', 'electrical', 'electrical', 'each', 12.00, 133.3, 28.00, 12, 'Halo'),
            ('PRT-ELEC-0009', 'Wire Nuts (assorted, box)', 'fasteners', 'electrical', 'box', 8.00, 100.0, 16.00, 5, 'Ideal'),
            ('PRT-ELEC-0010', '100A Sub-Panel', 'electrical', 'electrical', 'each', 150.00, 106.7, 310.00, 2, 'Square D'),
            # General
            ('PRT-GEN-0001', 'Silicone Caulk (tube)', 'adhesives_sealants', 'general', 'each', 6.00, 100.0, 12.00, 10, 'GE'),
            ('PRT-GEN-0002', 'Teflon Tape', 'adhesives_sealants', 'general', 'roll', 1.50, 100.0, 3.00, 15, None),
            ('PRT-GEN-0003', 'Pipe Dope', 'adhesives_sealants', 'general', 'each', 5.00, 100.0, 10.00, 8, 'Rector Seal'),
            ('PRT-GEN-0004', 'Drop Cloth', 'tools_consumables', 'general', 'each', 4.00, 100.0, 8.00, 10, None),
            ('PRT-GEN-0005', 'Assorted Screws/Anchors Kit', 'fasteners', 'general', 'kit', 12.00, 100.0, 24.00, 5, None),
        ]

        parts = []
        for pn, name, cat, trade, unit, cost, markup, sell, min_stock, mfr in parts_data:
            existing = db.query(Part).filter_by(part_number=pn).first()
            if existing:
                parts.append(existing)
                continue
            p = Part(
                organization_id=org_id, part_number=pn, name=name,
                category=cat, trade=trade, unit_of_measure=unit,
                cost_price=cost, markup_percentage=markup, sell_price=sell,
                minimum_stock_level=min_stock, manufacturer=mfr,
                is_active=True, created_by=admin_id,
            )
            db.add(p)
            parts.append(p)
        db.flush()
        print(f"  {len(parts)} parts in catalog")

        # ── 2. INVENTORY LOCATIONS ────────────────────────────────────────
        print("[2/5] Inventory locations...")
        techs = db.query(Technician).filter_by(is_active=True).limit(4).all()

        loc_data = [
            ('Main Warehouse', 'warehouse', '123 Industrial Blvd', None),
        ]
        for i, tech in enumerate(techs):
            loc_data.append((f'Van {i+1:02d} — {tech.full_name}', 'truck', None, tech.id))

        locations = []
        for name, ltype, addr, tech_id in loc_data:
            existing = db.query(InventoryLocation).filter_by(name=name, organization_id=org_id).first()
            if existing:
                locations.append(existing)
                continue
            loc = InventoryLocation(
                organization_id=org_id, name=name, location_type=ltype,
                address=addr, technician_id=tech_id, is_active=True,
            )
            db.add(loc)
            locations.append(loc)
        db.flush()
        print(f"  {len(locations)} inventory locations")

        # ── 3. STOCK LEVELS ───────────────────────────────────────────────
        print("[3/5] Stock levels...")
        random.seed(42)
        warehouse = locations[0]
        vans = locations[1:]

        stock_count = 0
        for part in parts:
            # Warehouse stock
            if not db.query(InventoryStock).filter_by(part_id=part.id, location_id=warehouse.id).first():
                qty = random.randint(20, 100)
                if part.part_number in ('PRT-PLM-0010', 'PRT-PLM-0009', 'PRT-ELEC-0005'):
                    qty = random.randint(0, part.minimum_stock_level)  # low stock
                db.add(InventoryStock(part_id=part.id, location_id=warehouse.id, quantity_on_hand=qty))
                db.add(InventoryTransaction(
                    organization_id=org_id, part_id=part.id, location_id=warehouse.id,
                    transaction_type='received', quantity=qty,
                    unit_cost=float(part.cost_price or 0),
                    notes='Initial inventory setup', created_by=admin_id,
                    created_at=datetime.utcnow() - timedelta(days=60),
                ))
                stock_count += 1

        # Van stock: match trade
        trade_map = {0: 'plumbing', 1: 'plumbing', 2: 'hvac', 3: 'electrical'}
        for i, van in enumerate(vans):
            trade = trade_map.get(i, 'general')
            van_parts = [p for p in parts if p.trade in (trade, 'general')]
            for part in van_parts:
                if not db.query(InventoryStock).filter_by(part_id=part.id, location_id=van.id).first():
                    qty = random.randint(3, 15)
                    if random.random() < 0.15:
                        qty = random.randint(0, max(1, part.minimum_stock_level - 1))
                    db.add(InventoryStock(part_id=part.id, location_id=van.id, quantity_on_hand=qty))
                    stock_count += 1

        db.flush()
        print(f"  {stock_count} stock records created")

        # ── 4. JOB MATERIALS ──────────────────────────────────────────────
        print("[4/5] Job materials...")
        jobs = db.query(Job).filter(
            Job.organization_id == org_id,
            Job.status.in_(['completed', 'in_progress', 'scheduled'])
        ).limit(10).all()

        random.seed(123)
        mat_count = 0
        plb_parts = [p for p in parts if p.trade == 'plumbing']
        hvac_parts = [p for p in parts if p.trade == 'hvac']
        elec_parts = [p for p in parts if p.trade == 'electrical']
        gen_parts = [p for p in parts if p.trade == 'general']

        for i, job in enumerate(jobs):
            trade_parts = [plb_parts, hvac_parts, elec_parts][i % 3]
            source_loc = vans[min(i % 3, len(vans) - 1)] if vans else warehouse

            selected = random.sample(trade_parts, min(random.randint(3, 5), len(trade_parts)))
            for j, part in enumerate(selected):
                qty = round(random.uniform(1, 8), 2) if part.unit_of_measure == 'foot' else random.randint(1, 4)
                status = 'verified' if job.status == 'completed' else ('verified' if j == 0 else 'logged')
                db.add(JobMaterial(
                    organization_id=org_id, job_id=job.id,
                    project_id=getattr(job, 'project_id', None),
                    part_id=part.id, quantity=qty,
                    unit_of_measure=part.unit_of_measure,
                    unit_cost=float(part.cost_price), markup_percentage=float(part.markup_percentage),
                    sell_price_per_unit=float(part.sell_price),
                    total_cost=round(float(qty) * float(part.cost_price), 2),
                    total_sell=round(float(qty) * float(part.sell_price), 2),
                    source_location_id=source_loc.id, is_billable=True,
                    added_by=admin_id, status=status,
                    added_at=datetime.utcnow() - timedelta(days=random.randint(1, 30)),
                ))
                mat_count += 1

            # Add 1-2 custom items
            for desc, cost, sell in random.sample([
                ('Misc copper fittings', 15.00, 25.00),
                ('PVC cement and primer', 8.50, 18.00),
                ('Electrical tape', 2.00, 4.00),
            ], random.randint(1, 2)):
                db.add(JobMaterial(
                    organization_id=org_id, job_id=job.id,
                    custom_description=desc, quantity=1, unit_of_measure='each',
                    unit_cost=cost, sell_price_per_unit=sell,
                    markup_percentage=round((sell / cost - 1) * 100, 1),
                    total_cost=cost, total_sell=sell,
                    is_billable=True, added_by=admin_id, status='logged',
                    added_at=datetime.utcnow() - timedelta(days=random.randint(1, 15)),
                    notes='Purchased on-site',
                ))
                mat_count += 1

            # General supplies
            for gp in random.sample(gen_parts, min(2, len(gen_parts))):
                db.add(JobMaterial(
                    organization_id=org_id, job_id=job.id, part_id=gp.id,
                    quantity=1, unit_of_measure=gp.unit_of_measure,
                    unit_cost=float(gp.cost_price), sell_price_per_unit=float(gp.sell_price),
                    markup_percentage=float(gp.markup_percentage),
                    total_cost=float(gp.cost_price), total_sell=float(gp.sell_price),
                    source_location_id=source_loc.id, is_billable=True,
                    added_by=admin_id, status='logged',
                    added_at=datetime.utcnow() - timedelta(days=random.randint(1, 20)),
                ))
                mat_count += 1

        db.flush()
        print(f"  {mat_count} material entries across {len(jobs)} jobs")

        # ── 5. STOCK TRANSFERS ────────────────────────────────────────────
        print("[5/5] Stock transfers...")
        if vans and plb_parts:
            if not db.query(StockTransfer).filter_by(transfer_number='TRF-2026-0001').first():
                t1 = StockTransfer(
                    organization_id=org_id, transfer_number='TRF-2026-0001',
                    status='completed', from_location_id=warehouse.id,
                    to_location_id=vans[0].id, requested_by=admin_id,
                    approved_by=admin_id, completed_at=datetime.utcnow() - timedelta(days=7),
                    notes='Weekly restock Van 01',
                )
                db.add(t1)
                db.flush()
                for part in plb_parts[:5]:
                    db.add(StockTransferItem(
                        transfer_id=t1.id, part_id=part.id,
                        quantity_requested=10, quantity_sent=10, quantity_received=10,
                        unit_cost=float(part.cost_price),
                    ))

            if len(vans) > 2 and hvac_parts:
                if not db.query(StockTransfer).filter_by(transfer_number='TRF-2026-0002').first():
                    t2 = StockTransfer(
                        organization_id=org_id, transfer_number='TRF-2026-0002',
                        status='requested', from_location_id=warehouse.id,
                        to_location_id=vans[2].id, requested_by=admin_id,
                        notes='Low on HVAC parts',
                    )
                    db.add(t2)
                    db.flush()
                    for part in hvac_parts[:3]:
                        db.add(StockTransferItem(
                            transfer_id=t2.id, part_id=part.id,
                            quantity_requested=5, unit_cost=float(part.cost_price),
                        ))

        db.commit()
        print(f"\nParts and Materials seed complete!")
        print(f"  - {len(parts)} parts in catalog")
        print(f"  - {len(locations)} inventory locations")
        print(f"  - {mat_count} job material entries")
        print(f"  - 2 sample transfers")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    seed()
