#!/usr/bin/env python3
"""Seed: Mobile demo technician and today's test data.
Run: python seed_mobile_demo.py
Login: tech_demo / demo123
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, datetime, timedelta
from models.database import get_session
from models.user import User
from models.technician import Technician
from models.client import Client
from models.job import Job
from models.time_entry import TimeEntry
from models.notification import Notification


def seed():
    db = get_session()
    try:
        today = date.today()

        # ── Demo Tech User ──
        user = db.query(User).filter_by(username='tech_demo').first()
        if not user:
            from werkzeug.security import generate_password_hash
            user = User(
                username='tech_demo',
                email='tech@demo.fieldservicepro.com',
                password_hash=generate_password_hash('demo123'),
                first_name='Alex',
                last_name='Demo',
                role='technician',
                is_active=True,
            )
            db.add(user)
            db.flush()
            print(f'  Created user: tech_demo / demo123 (id={user.id})')
        else:
            print(f'  tech_demo already exists (id={user.id})')

        # ── Link Technician profile ──
        tech = db.query(Technician).filter_by(user_id=user.id).first()
        if not tech:
            tech = Technician(
                first_name='Alex', last_name='Demo',
                user_id=user.id, status='active',
                phone='555-000-1234', email='tech@demo.fieldservicepro.com',
            )
            db.add(tech)
            db.flush()
            print(f'  Created technician profile (id={tech.id})')

        # ── Demo Client ──
        client = db.query(Client).filter_by(company_name='Demo Client Corp').first()
        if not client:
            client = Client(
                company_name='Demo Client Corp',
                client_type='commercial',
                phone='555-100-2000',
                email='client@demo.com',
            )
            db.add(client)
            db.flush()

        # ── 4 Jobs Today ──
        job_data = [
            {'title': 'Annual HVAC Tune-Up', 'status': 'completed',
             'hour': 8, 'desc': 'Annual maintenance on 2-ton HVAC unit.'},
            {'title': 'Water Heater Replacement', 'status': 'in_progress',
             'hour': 10, 'desc': 'Replace 40-gallon water heater.'},
            {'title': 'Electrical Panel Inspection', 'status': 'scheduled',
             'hour': 14, 'desc': 'Inspect 200A panel for compliance.'},
            {'title': 'Drain Cleaning — Emergency', 'status': 'scheduled',
             'hour': 16, 'desc': 'Kitchen drain blocked.'},
        ]

        jobs = []
        for jd in job_data:
            existing = db.query(Job).filter_by(title=jd['title']).filter(
                Job.scheduled_date >= datetime.combine(today, datetime.min.time()),
                Job.scheduled_date <= datetime.combine(today, datetime.max.time()),
            ).first()
            if not existing:
                job = Job(
                    title=jd['title'],
                    description=jd['desc'],
                    status=jd['status'],
                    client_id=client.id,
                    assigned_technician_id=tech.id,
                    scheduled_date=datetime.combine(today, datetime.strptime(f"{jd['hour']}:00", '%H:%M').time()),
                    job_type='service',
                    priority='normal' if jd['status'] != 'scheduled' else ('urgent' if 'Emergency' in jd['title'] else 'normal'),
                )
                if jd['status'] == 'completed':
                    job.completed_at = datetime.combine(today, datetime.strptime('09:58', '%H:%M').time())
                elif jd['status'] == 'in_progress':
                    job.started_at = datetime.combine(today, datetime.strptime('10:32', '%H:%M').time())
                db.add(job)
                jobs.append(job)
            else:
                jobs.append(existing)
        db.flush()
        print(f'  {len(jobs)} jobs for today')

        # ── Time Entries ──
        if jobs and not db.query(TimeEntry).filter_by(technician_id=tech.id, job_id=jobs[0].id).first():
            te1 = TimeEntry(
                technician_id=tech.id, job_id=jobs[0].id,
                date=today,
                start_time=datetime.strptime('08:05', '%H:%M').time(),
                end_time=datetime.strptime('09:58', '%H:%M').time(),
                duration_hours=1.88, entry_type='regular', status='draft',
                source='clock_in_out', description='Completed HVAC tune-up',
                created_by=user.id,
            )
            # Active entry on job 2 (no end_time)
            te2 = TimeEntry(
                technician_id=tech.id, job_id=jobs[1].id,
                date=today,
                start_time=datetime.strptime('10:32', '%H:%M').time(),
                end_time=None,
                entry_type='regular', status='draft',
                source='clock_in_out', description='Water heater in progress',
                created_by=user.id,
            )
            db.add_all([te1, te2])
            print('  Created 2 time entries (1 active)')

        # ── Notifications ──
        notif_data = [
            ('New Job Assigned', 'Water Heater Replacement at 789 Elm St assigned to you.'),
            ('Emergency Job Added', 'Drain Cleaning emergency added at 4pm.'),
            ('Parts Low Stock Alert', 'Wire Nuts below minimum on your truck.'),
        ]
        for title, msg in notif_data:
            if not db.query(Notification).filter_by(recipient_id=user.id, title=title).first():
                db.add(Notification(
                    recipient_id=user.id, title=title, message=msg,
                    notification_type='info', is_read=False,
                ))
        print('  Created notifications')

        db.commit()
        print('\nMobile demo data seeded!')
        print('  Login: username=tech_demo  password=demo123')
        print(f'  {len(jobs)} jobs for {today}')

    except Exception as e:
        db.rollback()
        print(f'ERROR: {e}')
        raise
    finally:
        db.close()


if __name__ == '__main__':
    print('Seeding mobile demo data...')
    seed()
    print('Done!')
