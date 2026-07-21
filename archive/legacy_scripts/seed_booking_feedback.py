#!/usr/bin/env python3
"""Seed: Survey template + feedback surveys + online booking requests.
Run: python seed_booking_feedback.py
"""
import sys, os, json, secrets
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
from models.database import get_session
from models.feedback_survey import FeedbackSurvey, SurveyTemplate
from models.service_request import ServiceRequest
from models.job import Job
from models.client import Client


def seed():
    db = get_session()
    try:
        now = datetime.utcnow()
        year = now.year

        # ── 1. Survey Template ──
        existing = db.query(SurveyTemplate).filter_by(name='Standard Post-Job Survey').first()
        if not existing:
            tmpl = SurveyTemplate(
                name='Standard Post-Job Survey',
                description='Default customer satisfaction survey sent after job completion.',
                is_default=True, is_active=True,
            )
            db.add(tmpl)
            db.flush()
            print(f'  Created survey template (id={tmpl.id})')
        else:
            tmpl = existing
            print('  Template already exists')

        # ── 2. Feedback Surveys ──
        jobs = db.query(Job).filter_by(status='completed').limit(10).all()
        clients = db.query(Client).limit(10).all()

        if not jobs:
            print('  No completed jobs — skipping feedback seed')
        else:
            survey_data = [
                (5, 5, 5, 5, 5, 5, 10, True, 'Fantastic service, arrived on time.', 'Punctual and clean.', None, False),
                (5, 5, 5, 5, 5, 4, 9, True, 'Quick and professional.', 'Fast response.', None, False),
                (4, 5, 4, 5, 4, 4, 8, True, 'Good work, bit late but called ahead.', 'Quality was excellent.', 'Arrive on time.', False),
                (4, 4, 4, 4, 5, 3, 7, True, 'Great work, clean site. A bit pricey.', 'Clean installation.', 'Pricing transparency.', False),
                (3, 4, 2, 2, 4, 3, 6, None, 'Took longer than quoted.', 'Final result is good.', 'Better time estimates.', False),
                (2, 3, 1, 3, 3, 3, 3, False, 'Late, wrong parts, had to come back.', None, 'Come prepared.', True),
                (5, 5, 5, 5, 5, 5, 10, True, 'Emergency response in under an hour!', 'Lightning fast.', None, False),
                (4, 4, 5, 4, 4, 4, 8, True, 'Good response, professional crew.', 'Efficient.', None, False),
            ]

            count = 0
            for i, data in enumerate(survey_data):
                if i >= len(jobs):
                    break
                job = jobs[i]
                client = clients[i] if i < len(clients) else clients[-1]

                if db.query(FeedbackSurvey).filter_by(job_id=job.id).first():
                    continue

                (overall, qual, punct, comm, prof, val, nps, rec, comments, well, improve, followup) = data
                survey = FeedbackSurvey(
                    survey_number=f'FB-{year}-{i+1:04d}',
                    job_id=job.id, client_id=client.id,
                    technician_id=job.assigned_technician_id if hasattr(job, 'assigned_technician_id') else None,
                    template_id=tmpl.id,
                    overall_rating=overall, quality_rating=qual,
                    punctuality_rating=punct, communication_rating=comm,
                    professionalism_rating=prof, value_rating=val,
                    nps_score=nps, would_recommend=rec,
                    comments=comments, what_went_well=well, what_could_improve=improve,
                    status='completed',
                    sent_at=now - timedelta(days=i+1, hours=3),
                    completed_at=now - timedelta(days=i+1),
                    expires_at=now + timedelta(days=30),
                    follow_up_required=followup,
                    token=secrets.token_urlsafe(32),
                )
                db.add(survey)
                count += 1
            print(f'  Created {count} feedback surveys')

        # ── 3. Online Booking Requests ──
        existing_bookings = db.query(ServiceRequest).filter_by(source='online_booking').count()
        if existing_bookings == 0:
            from models.user import Organization
            org = db.query(Organization).first()
            org_id = org.id if org else 1

            bookings = [
                dict(request_number=f'REQ-{year}-9001', contact_name='Sarah Mitchell',
                     contact_phone='(555) 201-3344', contact_email='sarah@example.com',
                     description='Kitchen sink completely backed up.',
                     request_type='plumbing', priority='medium', status='new',
                     street_address='45 Maple Ave', city='Kitchener',
                     state_province='ON', postal_code='N2G 1A1',
                     referral_source='google', preferred_time_slot='morning'),
                dict(request_number=f'REQ-{year}-9002', contact_name='James Park',
                     contact_phone='(555) 374-8822', contact_email='james@example.com',
                     description='Annual furnace maintenance before winter.',
                     request_type='hvac', priority='low', status='converted',
                     street_address='112 Cedar Cr', city='Cambridge',
                     state_province='ON', postal_code='N1R 2T5',
                     referral_source='repeat_customer', preferred_time_slot='anytime'),
                dict(request_number=f'REQ-{year}-9003', contact_name='Maria Gonzalez',
                     contact_phone='(555) 488-1927', contact_email='maria@example.com',
                     description='Outdoor lights not working after storm.',
                     request_type='electrical', priority='high', status='converted',
                     street_address='78 Birchwood Dr', city='Waterloo',
                     state_province='ON', postal_code='N2J 3K8',
                     referral_source='referral', preferred_time_slot='anytime'),
            ]
            for b in bookings:
                addr = f"{b['street_address']}, {b['city']}, {b['state_province']}, {b['postal_code']}"
                sr = ServiceRequest(
                    organization_id=org_id, source='online_booking',
                    customer_address=addr, booking_token=secrets.token_urlsafe(16),
                    honeypot_check=True, submitter_ip='127.0.0.1',
                    confirmation_sent=True, confirmation_sent_at=now,
                    **b,
                )
                db.add(sr)
            print(f'  Created {len(bookings)} online booking requests')
        else:
            print('  Booking requests already seeded')

        db.commit()
        print('\nBooking & Feedback seed complete!')
    except Exception as e:
        db.rollback()
        print(f'ERROR: {e}')
        raise
    finally:
        db.close()


if __name__ == '__main__':
    print('Seeding booking & feedback data...')
    seed()
    print('Done!')
