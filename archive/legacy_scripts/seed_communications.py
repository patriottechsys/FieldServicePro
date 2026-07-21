#!/usr/bin/env python3
"""Seed data: Communication logs and templates."""
import sys, os, random, json
from datetime import datetime, date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import get_session, Base, engine
from models.communication import CommunicationLog, CommunicationTemplate, DIRECTION_MAP
from models.client import Client
from models.job import Job
from models.user import User


def seed():
    Base.metadata.create_all(engine)
    db = get_session()
    try:
        admin = db.query(User).first()
        if not admin:
            print("No users found.")
            return

        org_id = admin.organization_id
        if db.query(CommunicationLog).count() > 0:
            print(f"Already have {db.query(CommunicationLog).count()} logs. Skipping.")
            return

        clients = db.query(Client).filter_by(organization_id=org_id).limit(6).all()
        jobs = db.query(Job).filter_by(organization_id=org_id).limit(10).all()
        if not clients:
            print("No clients found.")
            return

        today = date.today()
        year = today.year
        random.seed(42)

        # ── Templates ─────────────────────────────────────────────
        print("[1/2] Creating templates...")
        templates = [
            ('Scheduling Confirmation', 'phone_outbound', 'Scheduling confirmation for {client_name}', 'Confirmed appointment details with client.', False, None, 'normal'),
            ('Quote Follow-up', 'phone_outbound', 'Follow-up on Quote {quote_number}', 'Following up on the pending quote.', True, 3, 'normal'),
            ('Invoice Reminder', 'email_outbound', 'Payment reminder — Invoice {invoice_number}', 'Sent payment reminder for outstanding invoice.', True, 7, 'high'),
            ('Complaint Received', 'phone_inbound', 'Customer complaint from {client_name}', 'Customer reported issue. Details below.', True, 1, 'urgent'),
            ('Post-Job Check-in', 'phone_outbound', 'Post-completion check-in — {client_name}', 'Quality check-in after job completion.', False, None, 'normal'),
        ]
        for name, ctype, subj, desc, fu, fu_days, prio in templates:
            db.add(CommunicationTemplate(
                name=name, communication_type=ctype,
                subject_template=subj, description_template=desc,
                follow_up_required=fu, follow_up_days=fu_days,
                default_priority=prio, is_active=True, created_by_id=admin.id,
            ))
        db.flush()
        print(f"  {len(templates)} templates created")

        # ── Communication Logs ────────────────────────────────────
        print("[2/2] Creating communication logs...")
        log_data = [
            # (type, subject, priority, sentiment, days_ago, fu_required, fu_days_offset, escalation, tags)
            ('phone_inbound', 'Called about leaking faucet', 'normal', 'neutral', 1, True, 2, False, ['plumbing', 'inquiry']),
            ('email_outbound', 'Quote sent for HVAC replacement', 'normal', 'positive', 2, True, 5, False, ['hvac', 'quote']),
            ('phone_outbound', 'Scheduling confirmation — water heater', 'normal', 'positive', 3, False, None, False, ['scheduling']),
            ('phone_inbound', 'Complaint about unfinished work', 'urgent', 'negative', 0, True, 1, True, ['complaint', 'escalation']),
            ('email_inbound', 'Approval for electrical panel upgrade', 'high', 'positive', 4, False, None, False, ['electrical', 'approval']),
            ('in_person', 'Site walk-through with property manager', 'normal', 'neutral', 5, True, 3, False, ['site-visit']),
            ('phone_outbound', 'Invoice payment reminder — 30 days past due', 'high', 'neutral', 1, True, 7, False, ['billing', 'overdue']),
            ('text_outbound', 'ETA update for technician arrival', 'low', 'positive', 0, False, None, False, ['scheduling']),
            ('voicemail', 'Voicemail from tenant about heating issue', 'normal', 'neutral', 2, True, 1, False, ['hvac', 'tenant']),
            ('phone_inbound', 'Emergency call — main line backup', 'urgent', 'escalation', 0, True, 0, True, ['emergency', 'plumbing']),
            ('email_outbound', 'Warranty information sent to client', 'normal', 'positive', 6, False, None, False, ['warranty']),
            ('phone_outbound', 'Post-job quality check-in', 'low', 'positive', 8, False, None, False, ['quality']),
            ('site_visit', 'Pre-construction site assessment', 'normal', 'neutral', 10, True, 5, False, ['assessment']),
            ('video_call', 'Remote diagnostic with client', 'normal', 'neutral', 3, False, None, False, ['diagnostic']),
            ('phone_inbound', 'Follow-up call about drain cleaning', 'normal', 'positive', 7, False, None, False, ['plumbing', 'follow-up']),
            # Overdue follow-ups
            ('phone_outbound', 'Called to discuss project timeline', 'high', 'neutral', 12, True, -5, False, ['project', 'timeline']),
            ('email_outbound', 'Sent revised estimate', 'normal', 'neutral', 15, True, -8, False, ['estimate']),
        ]

        seq = 0
        for ctype, subj, prio, sent, days_ago, fu_req, fu_offset, esc, tags in log_data:
            seq += 1
            client = random.choice(clients)
            job = random.choice(jobs) if random.random() > 0.3 else None
            comm_date = datetime.combine(today - timedelta(days=days_ago), datetime.min.time().replace(hour=random.randint(8, 17), minute=random.choice([0, 15, 30, 45])))

            fu_date = None
            fu_completed = False
            if fu_req and fu_offset is not None:
                fu_date = today + timedelta(days=fu_offset) if fu_offset >= 0 else today + timedelta(days=fu_offset)
                if fu_offset < -3:
                    fu_completed = False  # overdue

            db.add(CommunicationLog(
                log_number=f"COM-{year}-{seq:04d}",
                communication_type=ctype,
                direction=DIRECTION_MAP.get(ctype),
                subject=subj,
                description=f"Communication with {client.display_name} regarding {subj.lower()}.",
                outcome='Action items discussed.' if random.random() > 0.5 else None,
                follow_up_required=fu_req,
                follow_up_date=fu_date,
                follow_up_notes='Follow up per discussion.' if fu_req else None,
                follow_up_completed=fu_completed,
                client_id=client.id,
                contact_name=client.display_name,
                job_id=job.id if job else None,
                priority=prio,
                sentiment=sent,
                is_escalation=esc,
                tags=tags,
                logged_by_id=admin.id,
                communication_date=comm_date,
                duration_minutes=random.choice([5, 10, 15, 20, 30, 45]) if 'phone' in ctype else None,
            ))

        db.commit()
        print(f"  {seq} communication logs created")
        print(f"\nCommunication seed complete!")
        print(f"  Templates: {db.query(CommunicationTemplate).count()}")
        print(f"  Logs: {db.query(CommunicationLog).count()}")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    seed()
