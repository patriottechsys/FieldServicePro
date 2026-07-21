#!/usr/bin/env python3
"""Seed: Vehicles, mileage/fuel logs, and payroll settings."""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, timedelta
from models.database import get_session
from models.equipment import Equipment
from models.vehicle_profile import VehicleProfile
from models.vehicle_mileage_log import VehicleMileageLog
from models.vehicle_fuel_log import VehicleFuelLog
from models.technician import Technician
from models.user import User
from models.app_settings import AppSettings


SAMPLE_VEHICLES = [
    {
        'name': 'Truck 1 - Ford F-250',
        'status': 'available',
        'profile': {
            'license_plate': 'FSP-1001', 'make': 'Ford', 'model': 'F-250',
            'year': 2021, 'color': 'White', 'fuel_type': 'gasoline',
            'fuel_tank_capacity': 26.5, 'current_odometer': 42500,
            'registration_expiry': date.today() + timedelta(days=180),
            'insurance_expiry': date.today() + timedelta(days=90),
        },
    },
    {
        'name': 'Van 2 - RAM ProMaster',
        'status': 'assigned',
        'profile': {
            'license_plate': 'FSP-2002', 'make': 'RAM', 'model': 'ProMaster 2500',
            'year': 2020, 'color': 'Blue', 'fuel_type': 'gasoline',
            'fuel_tank_capacity': 24.0, 'current_odometer': 78200,
            'registration_expiry': date.today() + timedelta(days=25),
            'insurance_expiry': date.today() + timedelta(days=15),
        },
    },
    {
        'name': 'Truck 3 - Chevy Colorado',
        'status': 'available',
        'profile': {
            'license_plate': 'FSP-3003', 'make': 'Chevrolet', 'model': 'Colorado',
            'year': 2022, 'color': 'Red', 'fuel_type': 'gasoline',
            'fuel_tank_capacity': 21.0, 'current_odometer': 18100,
            'registration_expiry': date.today() + timedelta(days=300),
            'insurance_expiry': date.today() + timedelta(days=210),
        },
    },
]


def seed():
    db = get_session()
    try:
        admin = db.query(User).filter_by(role='owner').first() or db.query(User).first()
        if not admin:
            print("No users found. Run seed data first.")
            return

        technicians = db.query(Technician).filter_by(is_active=True).all()
        if not technicians:
            print("No technicians found.")
            return

        org_id = admin.organization_id
        created = []

        # Vehicles
        for v_data in SAMPLE_VEHICLES:
            existing = db.query(Equipment).filter_by(
                name=v_data['name'], equipment_type='vehicle', organization_id=org_id
            ).first()
            if existing:
                print(f"  [SKIP] {v_data['name']} exists")
                created.append(existing)
                continue

            equip = Equipment(
                organization_id=org_id,
                name=v_data['name'],
                equipment_type='vehicle',
                status=v_data['status'],
                make=v_data['profile']['make'],
                model=v_data['profile']['model'],
                year=v_data['profile']['year'],
                identifier=v_data['profile'].get('license_plate'),
            )
            db.add(equip)
            db.flush()

            tech = technicians[len(created) % len(technicians)]
            profile = VehicleProfile(
                equipment_id=equip.id,
                assigned_technician_id=tech.id,
                **v_data['profile'],
            )
            db.add(profile)
            created.append(equip)
            print(f"  [OK] Created vehicle: {v_data['name']} (assigned to {tech.full_name})")

        db.flush()

        # Mileage logs
        for vehicle in created[:2]:
            for i in range(5):
                day = date.today() - timedelta(days=i * 3)
                base_odo = (vehicle.vehicle_profile.current_odometer or 40000) - (i * 150)
                tech = random.choice(technicians)
                ml = VehicleMileageLog(
                    vehicle_id=vehicle.id, date=day,
                    start_odometer=base_odo,
                    end_odometer=base_odo + random.randint(20, 90),
                    purpose=random.choice(['job_travel', 'parts_pickup', 'between_jobs']),
                    technician_id=tech.id,
                    start_location='Shop', end_location='Job Site',
                    created_by=admin.id,
                )
                db.add(ml)
        print(f"  [OK] Created 10 mileage log entries")

        # Fuel logs
        for vehicle in created[:2]:
            for i in range(3):
                day = date.today() - timedelta(days=i * 7)
                tech = random.choice(technicians)
                fl = VehicleFuelLog(
                    vehicle_id=vehicle.id, date=day,
                    odometer_reading=(vehicle.vehicle_profile.current_odometer or 40000) - (i * 200),
                    gallons=round(random.uniform(12, 22), 3),
                    price_per_gallon=round(random.uniform(3.20, 4.10), 3),
                    fuel_type='gasoline',
                    station=random.choice(['Shell', 'BP', 'Sunoco', 'Exxon']),
                    is_full_tank=True, payment_method='company_card',
                    technician_id=tech.id, created_by=admin.id,
                )
                db.add(fl)
        print(f"  [OK] Created 6 fuel log entries")

        # Payroll settings (key-value in AppSettings)
        payroll_defaults = [
            ('pay_frequency', 'biweekly', 'string', 'Default pay frequency'),
            ('daily_ot_threshold', '8', 'decimal', 'Hours/day before daily OT'),
            ('daily_dt_threshold', '12', 'decimal', 'Hours/day before double-time'),
            ('weekly_ot_threshold', '40', 'decimal', 'Hours/week before weekly OT'),
            ('ot_multiplier', '1.5', 'decimal', 'Overtime rate multiplier'),
            ('dt_multiplier', '2.0', 'decimal', 'Double-time rate multiplier'),
            ('mileage_reimbursement_rate', '0.670', 'decimal', 'IRS mileage rate $/mile'),
        ]
        for key, value, vtype, desc in payroll_defaults:
            existing = db.query(AppSettings).filter_by(key=key).first()
            if not existing:
                db.add(AppSettings(key=key, value=value, value_type=vtype, description=desc))
                print(f"  [OK] Setting: {key} = {value}")
            else:
                print(f"  [SKIP] Setting: {key} exists ({existing.value})")

        db.commit()

        print(f"\nVehicle & Payroll seed complete.")
        print(f"  {len(created)} vehicles | 10 mileage logs | 6 fuel logs | 7 payroll settings")

    except Exception as e:
        db.rollback()
        print(f"Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == '__main__':
    print("Seeding vehicle & payroll data...\n")
    seed()
