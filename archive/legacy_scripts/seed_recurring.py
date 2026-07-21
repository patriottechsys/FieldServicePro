#!/usr/bin/env python3
"""Seed data: Recurring schedules for preventive maintenance."""
import sys, os, random, json
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import get_session, Base, engine
from models.recurring_schedule import RecurringSchedule, RecurringJobLog
from models.client import Client
from models.division import Division
from models.technician import Technician
from models.user import User
from web.utils.recurring_engine import generate_schedule_number


def seed():
    Base.metadata.create_all(engine)
    db = get_session()
    try:
        admin = db.query(User).first()
        if not admin:
            print("No users found.")
            return
        org_id = admin.organization_id

        clients = db.query(Client).filter_by(organization_id=org_id).limit(6).all()
        techs = db.query(Technician).filter_by(is_active=True).limit(4).all()
        divisions = db.query(Division).filter_by(organization_id=org_id, is_active=True).all()

        if not clients:
            print("No clients found. Run main seed first.")
            return

        # Check if already seeded
        existing = db.query(RecurringSchedule).filter_by(organization_id=org_id).count()
        if existing > 0:
            print(f"Already have {existing} recurring schedules. Skipping.")
            return

        today = date.today()
        schedules_data = [
            {
                'title': 'Quarterly HVAC Filter Replacement',
                'job_type': 'maintenance', 'trade': 'hvac',
                'frequency': 'quarterly', 'default_priority': 'normal',
                'estimated_duration_hours': 1.5, 'estimated_amount': 195.00,
                'default_description': 'Replace HVAC air filters.\n- Check filter size\n- Replace filters\n- Inspect ductwork for leaks\n- Test system operation',
                'preferred_day_of_week': 'tuesday',
                'start_offset': -90, 'next_due_offset': 15,
            },
            {
                'title': 'Annual Backflow Preventer Test',
                'job_type': 'inspection', 'trade': 'plumbing',
                'frequency': 'annual', 'default_priority': 'high',
                'estimated_duration_hours': 1.0, 'estimated_amount': 150.00,
                'default_description': 'Annual backflow preventer inspection and certification.\n- Test double check valve\n- Document readings\n- Submit to water authority if required',
                'seasonal_months': json.dumps([3, 4, 5]),
                'start_offset': -365, 'next_due_offset': 30,
            },
            {
                'title': 'Monthly HVAC Preventive Maintenance',
                'job_type': 'maintenance', 'trade': 'hvac',
                'frequency': 'monthly', 'default_priority': 'normal',
                'estimated_duration_hours': 2.0, 'estimated_amount': 275.00,
                'default_description': 'Monthly HVAC system check:\n- Inspect refrigerant levels\n- Clean condenser coils\n- Check electrical connections\n- Lubricate motors\n- Test thermostat calibration',
                'preferred_day_of_week': 'wednesday',
                'start_offset': -60, 'next_due_offset': 5,
            },
            {
                'title': 'Semi-Annual Electrical Panel Inspection',
                'job_type': 'inspection', 'trade': 'electrical',
                'frequency': 'semi_annual', 'default_priority': 'high',
                'estimated_duration_hours': 2.5, 'estimated_amount': 350.00,
                'default_description': 'Bi-annual electrical panel inspection:\n- Thermal imaging scan\n- Check breaker torque\n- Test GFCI/AFCI outlets\n- Verify grounding\n- Inspect for code violations',
                'seasonal_months': json.dumps([4, 10]),
                'start_offset': -180, 'next_due_offset': 20,
            },
            {
                'title': 'Weekly Grease Trap Pumping',
                'job_type': 'maintenance', 'trade': 'plumbing',
                'frequency': 'weekly', 'default_priority': 'normal',
                'estimated_duration_hours': 1.0, 'estimated_amount': 125.00,
                'default_description': 'Weekly grease trap pumping and cleaning.\n- Pump out accumulated grease\n- Clean baffles\n- Inspect for damage\n- Log volume pumped',
                'preferred_day_of_week': 'friday',
                'start_offset': -30, 'next_due_offset': 3,
            },
            {
                'title': 'Biweekly Cooling Tower Treatment',
                'job_type': 'maintenance', 'trade': 'hvac',
                'frequency': 'biweekly', 'default_priority': 'normal',
                'estimated_duration_hours': 1.5, 'estimated_amount': 200.00,
                'default_description': 'Cooling tower water treatment:\n- Test water chemistry\n- Add treatment chemicals\n- Clean strainer\n- Check blowdown valve\n- Log readings',
                'start_offset': -45, 'next_due_offset': 7,
            },
            {
                'title': 'Annual Fire Sprinkler Inspection',
                'job_type': 'inspection', 'trade': 'plumbing',
                'frequency': 'annual', 'default_priority': 'urgent',
                'estimated_duration_hours': 4.0, 'estimated_amount': 650.00,
                'default_description': 'Annual fire sprinkler system inspection per NFPA 25.\n- Visual inspection of all heads\n- Flow test\n- Alarm test\n- Valve inspection\n- Generate compliance report',
                'seasonal_months': json.dumps([1, 2]),
                'start_offset': -365, 'next_due_offset': 45,
            },
            {
                'title': 'Quarterly Water Heater Flush',
                'job_type': 'maintenance', 'trade': 'plumbing',
                'frequency': 'quarterly', 'default_priority': 'low',
                'estimated_duration_hours': 1.0, 'estimated_amount': 125.00,
                'default_description': 'Quarterly water heater maintenance:\n- Drain and flush sediment\n- Check anode rod\n- Test T&P valve\n- Inspect gas connections\n- Check temperature setting',
                'start_offset': -90, 'next_due_offset': 10,
            },
        ]

        random.seed(42)
        count = 0
        for i, data in enumerate(schedules_data):
            client = clients[i % len(clients)]
            tech = techs[i % len(techs)] if techs else None
            division = divisions[i % len(divisions)] if divisions else None

            start = today + timedelta(days=data['start_offset'])
            next_due = today + timedelta(days=data['next_due_offset'])

            schedule = RecurringSchedule(
                organization_id=org_id,
                schedule_number=generate_schedule_number(db),
                title=data['title'],
                description=None,
                client_id=client.id,
                division_id=division.id if division else None,
                job_type=data['job_type'],
                trade=data.get('trade'),
                default_description=data['default_description'],
                default_priority=data['default_priority'],
                estimated_duration_hours=data.get('estimated_duration_hours'),
                estimated_amount=data.get('estimated_amount'),
                default_technician_id=tech.id if tech else None,
                frequency=data['frequency'],
                preferred_day_of_week=data.get('preferred_day_of_week'),
                seasonal_months=data.get('seasonal_months'),
                start_date=start,
                next_due_date=next_due,
                auto_generate=True,
                auto_assign=True if tech else False,
                auto_schedule=random.choice([True, False]),
                advance_generation_days=14,
                status='active',
                total_jobs_generated=random.randint(2, 12),
                total_value_generated=round(random.uniform(500, 5000), 2),
                created_by=admin.id,
            )
            db.add(schedule)
            db.flush()

            # Add some history logs
            for j in range(min(schedule.total_jobs_generated, 3)):
                db.add(RecurringJobLog(
                    schedule_id=schedule.id,
                    due_date=start + timedelta(days=30 * (j + 1)),
                    generation_method=random.choice(['auto', 'manual']),
                    generated_by=admin.id,
                    success=True,
                    notes=f'Historical generation #{j + 1}',
                    generated_at=datetime.utcnow() - timedelta(days=30 * (3 - j)),
                ))

            count += 1

        # Add one paused schedule
        if clients:
            paused = RecurringSchedule(
                organization_id=org_id,
                schedule_number=generate_schedule_number(db),
                title='Seasonal Irrigation Winterization',
                client_id=clients[0].id,
                division_id=divisions[0].id if divisions else None,
                job_type='maintenance', trade='plumbing',
                default_description='Winterize irrigation system:\n- Blow out lines\n- Drain backflow preventer\n- Insulate exposed pipes',
                default_priority='normal',
                estimated_amount=225.00,
                frequency='annual',
                seasonal_months=json.dumps([10, 11]),
                start_date=today - timedelta(days=365),
                next_due_date=today + timedelta(days=180),
                auto_generate=True,
                status='paused',
                pause_reason='Paused for summer — will resume in October',
                pause_until=today + timedelta(days=120),
                total_jobs_generated=1,
                created_by=admin.id,
            )
            db.add(paused)
            count += 1

        db.commit()
        print(f"Created {count} recurring schedules ({count - 1} active, 1 paused)")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    seed()
