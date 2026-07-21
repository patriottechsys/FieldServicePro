#!/usr/bin/env python3
"""Seed realistic time tracking data for the past 2 weeks."""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, date, time, timedelta
from models.database import get_session, Base, engine
from models.time_entry import TimeEntry, ActiveClock
from models.technician import Technician
from models.job import Job
from models.user import User


def seed():
    Base.metadata.create_all(engine)
    db = get_session()
    try:
        techs = db.query(Technician).filter_by(is_active=True).all()
        jobs = db.query(Job).all()
        admin = db.query(User).first()
        admin_id = admin.id if admin else 1

        if not techs or not jobs:
            print("No technicians or jobs found.")
            return

        # Clear existing
        db.query(ActiveClock).delete()
        db.query(TimeEntry).delete()
        db.commit()
        print("Cleared existing time data.")

        # Set rates
        rate_tiers = [45, 55, 65, 75, 85]
        billable_tiers = [85, 95, 110, 125, 150]
        for i, t in enumerate(techs):
            tier = min(i, len(rate_tiers) - 1)
            t.hourly_rate = rate_tiers[tier]
            if hasattr(t, 'billable_rate'):
                t.billable_rate = billable_tiers[tier]
        db.commit()

        today = date.today()
        start_date = today - timedelta(days=13)
        count = 0

        descs = [
            "Installed copper piping", "Replaced HVAC compressor", "Ran electrical circuits",
            "Troubleshot hot water issue", "Installed thermostat", "Repaired leaking faucet",
            "Replaced circuit breaker", "Scheduled maintenance", "Snaked drain line",
            "Installed water heater", "Replaced ductwork", "Wired sub-panel",
        ]

        for day_offset in range(14):
            d = start_date + timedelta(days=day_offset)
            if d.weekday() >= 5:
                continue

            for tech in techs:
                rate = float(tech.hourly_rate or 55)
                b_rate = float(getattr(tech, 'billable_rate', 95) or 95)
                user_id = tech.user_id or admin_id
                hour = random.randint(6, 8)

                for _ in range(random.randint(2, 4)):
                    job = random.choice(jobs)
                    dur = round(random.uniform(1.0, 3.0), 2)
                    st = time(hour=min(hour, 22), minute=random.choice([0, 15, 30, 45]))
                    end_h = min(hour + int(dur), 22)
                    et = time(hour=end_h, minute=random.choice([0, 15, 30, 45]))
                    hour = end_h + 1

                    days_ago = (today - d).days
                    if days_ago > 7:
                        status = 'approved'
                    elif days_ago > 3:
                        status = random.choice(['approved', 'submitted'])
                    else:
                        status = random.choice(['submitted', 'draft'])

                    entry = TimeEntry(
                        technician_id=tech.id, job_id=job.id,
                        project_id=job.project_id if hasattr(job, 'project_id') else None,
                        entry_type='regular', date=d, start_time=st, end_time=et,
                        duration_hours=dur, billable=True,
                        hourly_rate=rate, labor_cost=round(dur * rate, 2),
                        billable_rate=b_rate, billable_amount=round(dur * b_rate, 2),
                        description=random.choice(descs),
                        status=status, source='manual', created_by=user_id,
                        approved_by=admin_id if status == 'approved' else None,
                        approved_at=datetime.combine(d, time(17, 0)) if status == 'approved' else None,
                    )
                    db.add(entry)
                    count += 1

        db.commit()
        print(f"Created {count} time entries.")

        # Create active clocks
        for tech in techs[:3]:
            if not db.query(ActiveClock).filter_by(technician_id=tech.id).first():
                active_jobs = [j for j in jobs if j.status in ('scheduled', 'in_progress')]
                if active_jobs:
                    db.add(ActiveClock(
                        technician_id=tech.id, job_id=random.choice(active_jobs).id,
                        clock_in_time=datetime.utcnow() - timedelta(hours=random.randint(1, 3)),
                        notes='On site working',
                    ))
        db.commit()
        ac = db.query(ActiveClock).count()
        print(f"Created {ac} active clocks.")

        # Update job actual_hours
        from sqlalchemy import func
        job_hours = db.query(
            TimeEntry.job_id, func.sum(TimeEntry.duration_hours), func.sum(TimeEntry.labor_cost),
        ).filter(TimeEntry.status.in_(['approved', 'exported'])).group_by(TimeEntry.job_id).all()

        for jid, hours, cost in job_hours:
            job = db.query(Job).filter_by(id=jid).first()
            if job:
                if hasattr(job, 'actual_hours'):
                    job.actual_hours = float(hours or 0)
                if hasattr(job, 'actual_labor_cost'):
                    job.actual_labor_cost = float(cost or 0)
        db.commit()
        print(f"Updated actual_hours on {len(job_hours)} jobs.")
        print("\nTime tracking seed complete.")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    seed()
