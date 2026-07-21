#!/usr/bin/env python3
"""
Seed: Notification System
Creates:
  - 18 sample notifications (mix of read/unread, categories, priorities)
  - 12 default client notification templates
  - 12 notification log entries
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
from models.database import get_session
from models.notification import (
    Notification, NotificationPreference, ClientNotificationTemplate,
    NotificationLog, NOTIFICATION_CATEGORIES,
)


def seed_notifications():
    db = get_session()
    try:
        from models.user import User
        user = db.query(User).first()
        if not user:
            print("No users found. Run seed data first.")
            return

        now = datetime.utcnow()

        # ── 1. Client Notification Templates ─────────────────────────────
        existing_templates = db.query(ClientNotificationTemplate).count()
        if existing_templates == 0:
            templates = [
                dict(
                    name='Technician En Route',
                    trigger_event='tech_en_route', channel='both',
                    subject_template='Your {company_name} technician is on the way!',
                    body_template='<p>Hi {client_first_name},</p><p>Your technician <strong>{technician_name}</strong> is on the way for your <strong>{job_type}</strong> service.</p><p><strong>Job:</strong> {job_number}<br><strong>Address:</strong> {property_address}</p>',
                    sms_template='{company_name}: Your tech {technician_name} is on the way. Questions? Call us.',
                    is_active=True, send_delay_minutes=0,
                ),
                dict(
                    name='Job Scheduled Confirmation',
                    trigger_event='job_scheduled', channel='both',
                    subject_template='Your {job_type} appointment is confirmed - {scheduled_date}',
                    body_template='<p>Hi {client_first_name},</p><p>Your <strong>{job_type}</strong> appointment is confirmed.</p><p><strong>Date:</strong> {scheduled_date}<br><strong>Time:</strong> {scheduled_time}<br><strong>Address:</strong> {property_address}<br><strong>Technician:</strong> {technician_name}<br><strong>Job:</strong> {job_number}</p>',
                    sms_template='{company_name}: Appt confirmed {scheduled_date} at {scheduled_time}. Tech: {technician_name}. Ref: {job_number}',
                    is_active=True, send_delay_minutes=0,
                ),
                dict(
                    name='Job Completed - Thank You',
                    trigger_event='job_completed', channel='email',
                    subject_template='Your {job_type} service is complete - Thank you!',
                    body_template='<p>Hi {client_first_name},</p><p>Your <strong>{job_type}</strong> service has been completed by <strong>{technician_name}</strong>.</p><p><strong>Job:</strong> {job_number}</p><p>Your invoice will be sent shortly. Thank you for choosing {company_name}!</p>',
                    sms_template='{company_name}: Your {job_type} service (#{job_number}) is complete. Thank you!',
                    is_active=True, send_delay_minutes=5,
                ),
                dict(
                    name='Quote Ready for Review',
                    trigger_event='quote_sent', channel='email',
                    subject_template='Your {company_name} quote is ready - {quote_number}',
                    body_template='<p>Hi {client_first_name},</p><p>Your quote for <strong>{quote_number}</strong> totaling <strong>{quote_total}</strong> is ready for review.</p><p>This quote is valid for 30 days. Questions? Contact us.</p>',
                    sms_template='{company_name}: Quote {quote_number} ({quote_total}) is ready for review.',
                    is_active=True, send_delay_minutes=0,
                ),
                dict(
                    name='Invoice Issued',
                    trigger_event='invoice_issued', channel='email',
                    subject_template='Invoice {invoice_number} from {company_name}',
                    body_template='<p>Hi {client_first_name},</p><p>Your invoice is ready.</p><p><strong>Invoice:</strong> {invoice_number}<br><strong>Amount:</strong> {invoice_total}<br><strong>Due:</strong> {invoice_due_date}</p>',
                    sms_template='{company_name}: Invoice {invoice_number} for {invoice_total} due {invoice_due_date}.',
                    is_active=True, send_delay_minutes=0,
                ),
                dict(
                    name='Invoice Payment Reminder',
                    trigger_event='invoice_reminder', channel='email',
                    subject_template='Payment Reminder - Invoice {invoice_number}',
                    body_template='<p>Hi {client_first_name},</p><p>Friendly reminder that invoice <strong>{invoice_number}</strong> for <strong>{invoice_total}</strong> is due on <strong>{invoice_due_date}</strong>.</p><p>If you have already paid, please disregard.</p>',
                    sms_template='{company_name}: Reminder - Invoice {invoice_number} ({invoice_total}) due {invoice_due_date}.',
                    is_active=True, send_delay_minutes=0,
                ),
                dict(
                    name='Payment Received - Thank You',
                    trigger_event='payment_received', channel='email',
                    subject_template='Payment received - Thank you, {client_first_name}!',
                    body_template='<p>Hi {client_first_name},</p><p>We have received your payment. Thank you!</p>',
                    sms_template='{company_name}: Payment received. Thank you, {client_first_name}!',
                    is_active=True, send_delay_minutes=0,
                ),
                dict(
                    name='Appointment Reminder (24h)',
                    trigger_event='appointment_reminder', channel='both',
                    subject_template='Reminder: Your {job_type} appointment is tomorrow',
                    body_template='<p>Hi {client_first_name},</p><p>Reminder: your <strong>{job_type}</strong> appointment is tomorrow.</p><p><strong>Date:</strong> {scheduled_date}<br><strong>Time:</strong> {scheduled_time}<br><strong>Address:</strong> {property_address}<br><strong>Technician:</strong> {technician_name}</p><p>Need to reschedule? Contact us.</p>',
                    sms_template='{company_name}: Reminder - {job_type} appt tomorrow {scheduled_time}. Q? Call us.',
                    is_active=True, send_delay_minutes=0,
                ),
                dict(
                    name='Warranty Created',
                    trigger_event='warranty_created', channel='email',
                    subject_template='Your {company_name} warranty documentation - {job_number}',
                    body_template='<p>Hi {client_first_name},</p><p>Your warranty documentation for job <strong>{job_number}</strong> is now available.</p><p>If you experience any issues covered under warranty, contact us immediately.</p>',
                    sms_template=None,
                    is_active=True, send_delay_minutes=0,
                ),
                dict(
                    name='Warranty Expiring Notice',
                    trigger_event='warranty_expiring', channel='email',
                    subject_template='Your warranty is expiring soon - {company_name}',
                    body_template='<p>Hi {client_first_name},</p><p>Your warranty for job <strong>{job_number}</strong> is expiring soon. Contact us to discuss extended coverage options.</p>',
                    sms_template=None,
                    is_active=True, send_delay_minutes=0,
                ),
            ]

            for t_data in templates:
                t = ClientNotificationTemplate(created_by=user.id, **t_data)
                db.add(t)
            db.flush()
            print(f"  [OK] Created {len(templates)} client notification templates")
        else:
            print(f"  [SKIP] Templates exist ({existing_templates})")

        # ── 2. Sample Internal Notifications ─────────────────────────────
        existing_notifs = db.query(Notification).filter_by(recipient_id=user.id).count()
        if existing_notifs < 5:
            sample = [
                # UNREAD - urgent
                dict(recipient_id=user.id, title='New Service Request - KW Property Mgmt',
                     message='A new HVAC maintenance service request has been received from KW Property Management for their Downtown Office property.',
                     notification_type='action_required', category='request_new', priority='urgent',
                     entity_type='servicerequest', entity_id=1, action_url='/requests/1',
                     is_read=False, is_actionable=True, created_at=now - timedelta(minutes=15)),
                # UNREAD - approval
                dict(recipient_id=user.id, title='Invoice INV-00042 Needs Approval',
                     message='Invoice INV-00042 for $8,450.00 (Commercial Rooftop Unit Replacement) is awaiting your approval.',
                     notification_type='action_required', category='approval_needed', priority='high',
                     entity_type='invoice', entity_id=42, action_url='/invoices/42',
                     is_read=False, is_actionable=True, created_at=now - timedelta(minutes=42)),
                # UNREAD - SLA danger
                dict(recipient_id=user.id, title='SLA At Risk - JOB-00089',
                     message='Job JOB-00089 (Emergency Boiler Repair) has a response deadline in 2 hours. SLA requires 4-hour response.',
                     notification_type='danger', category='contract_alert', priority='urgent',
                     entity_type='job', entity_id=89, action_url='/jobs/89',
                     is_read=False, is_actionable=True, created_at=now - timedelta(hours=1)),
                # UNREAD - job completed
                dict(recipient_id=user.id, title='Job JOB-00091 Completed',
                     message='Technician Mike Johnson completed JOB-00091 (Electrical Panel Upgrade). Ready for invoicing.',
                     notification_type='success', category='job_update', priority='normal',
                     entity_type='job', entity_id=91, action_url='/jobs/91',
                     is_read=False, created_at=now - timedelta(hours=2)),
                # UNREAD - change order
                dict(recipient_id=user.id, title='Change Order CO-00015 Requires Approval',
                     message='Change Order CO-00015 ($2,200.00 additional) for JOB-00087 has been submitted.',
                     notification_type='action_required', category='approval_needed', priority='high',
                     entity_type='changeorder', entity_id=15, action_url='/change-orders',
                     is_read=False, is_actionable=True, created_at=now - timedelta(hours=3)),
                # READ - payment
                dict(recipient_id=user.id, title='Payment Received - $3,200.00',
                     message='Payment of $3,200.00 received from Riverside Properties for Invoice INV-00038.',
                     notification_type='success', category='invoice_update', priority='normal',
                     entity_type='invoice', entity_id=38, action_url='/invoices/38',
                     is_read=True, read_at=now - timedelta(hours=1), created_at=now - timedelta(hours=4)),
                # READ - tech en route
                dict(recipient_id=user.id, title='Technician Dave Chen En Route',
                     message='Dave Chen is en route to JOB-00090 (HVAC Seasonal Maintenance). ETA 25 minutes.',
                     notification_type='info', category='schedule_change', priority='normal',
                     entity_type='job', entity_id=90, action_url='/jobs/90',
                     is_read=True, read_at=now - timedelta(minutes=30), created_at=now - timedelta(hours=5)),
                # UNREAD - insurance expiring
                dict(recipient_id=user.id, title='Insurance Policy Expiring in 15 Days',
                     message='General Liability Insurance expires in 15 days. Renew immediately to maintain compliance.',
                     notification_type='danger', category='compliance_alert', priority='urgent',
                     entity_type='insurance', entity_id=1, action_url='/insurance/1',
                     is_read=False, is_actionable=True, created_at=now - timedelta(days=1, hours=2)),
                # READ - expense submitted
                dict(recipient_id=user.id, title='Expense EXP-00023 Submitted',
                     message='Technician Sarah Williams submitted expense EXP-00023 for $385.50. Awaiting approval.',
                     notification_type='info', category='expense_update', priority='normal',
                     entity_type='expense', entity_id=23, action_url='/expenses/23',
                     is_read=True, read_at=now - timedelta(days=1), created_at=now - timedelta(days=1, hours=5)),
                # UNREAD - overdue follow-up
                dict(recipient_id=user.id, title='Overdue Follow-Up: Riverside Renovation Quote',
                     message='Follow-up for Riverside Renovation quote discussion was due yesterday.',
                     notification_type='warning', category='communication_follow_up', priority='high',
                     entity_type='communicationlog', entity_id=5, action_url='/communications',
                     is_read=False, created_at=now - timedelta(days=1, hours=8)),
                # READ - quote approved
                dict(recipient_id=user.id, title='Quote QTE-00031 Approved by Client',
                     message='Quote QTE-00031 ($15,800.00 - HVAC System Overhaul) approved. Ready to schedule job.',
                     notification_type='success', category='quote_update', priority='normal',
                     entity_type='quote', entity_id=31, action_url='/quotes/31',
                     is_read=True, read_at=now - timedelta(days=1, hours=3), created_at=now - timedelta(days=1, hours=10)),
                # READ - warranty expiring
                dict(recipient_id=user.id, title='Warranty WTY-00008 Expiring in 25 Days',
                     message='Warranty for JOB-00075 (HVAC Installation) expires in 25 days.',
                     notification_type='warning', category='warranty_alert', priority='normal',
                     entity_type='warranty', entity_id=8, action_url='/warranties/8',
                     is_read=True, read_at=now - timedelta(days=2), created_at=now - timedelta(days=3, hours=1)),
                # READ - callback
                dict(recipient_id=user.id, title='Callback Created - JOB-00072',
                     message='Callback for JOB-00072 (Plumbing Repair). Client reports drain still slow after repair.',
                     notification_type='warning', category='callback_alert', priority='high',
                     entity_type='callback', entity_id=3, action_url='/callbacks/3',
                     is_read=True, read_at=now - timedelta(days=2, hours=6), created_at=now - timedelta(days=3, hours=4)),
                # UNREAD - recurring overdue
                dict(recipient_id=user.id, title='Recurring PM Overdue - HVAC Quarterly Filter',
                     message='Recurring schedule for HVAC Quarterly Filter Replacement is 5 days overdue.',
                     notification_type='danger', category='job_update', priority='high',
                     entity_type='recurring', entity_id=2, action_url='/recurring/2',
                     is_read=False, created_at=now - timedelta(days=3, hours=8)),
                # READ - contract expiring
                dict(recipient_id=user.id, title='Contract CTR-00005 Expiring in 28 Days',
                     message='Maintenance contract with Lakeside Business Park expires in 28 days. Annual revenue: $24,000.',
                     notification_type='warning', category='contract_alert', priority='high',
                     entity_type='contract', entity_id=5, action_url='/contracts/5',
                     is_read=True, read_at=now - timedelta(days=5), created_at=now - timedelta(days=7)),
                # READ - overtime
                dict(recipient_id=user.id, title='Mike Johnson - Overtime Alert',
                     message='Technician Mike Johnson worked 9.5 hours today, exceeding 8-hour overtime threshold.',
                     notification_type='warning', category='time_tracking', priority='normal',
                     entity_type=None, entity_id=None, action_url='/time-tracking',
                     is_read=True, read_at=now - timedelta(days=6), created_at=now - timedelta(days=7, hours=2)),
                # READ - cert expiring
                dict(recipient_id=user.id, title='Certification Expiring - Dave Chen (NATE)',
                     message="Dave Chen's NATE Certification expires in 22 days. Renewal required for compliance.",
                     notification_type='warning', category='compliance_alert', priority='high',
                     entity_type='certification', entity_id=4, action_url='/certifications',
                     is_read=True, read_at=now - timedelta(days=6, hours=3), created_at=now - timedelta(days=7, hours=5)),
                # READ - system
                dict(recipient_id=user.id, title='System: Notification Center Activated',
                     message='The FieldServicePro Automated Notification System has been activated. Configure preferences in Settings.',
                     notification_type='info', category='system', priority='normal',
                     entity_type=None, entity_id=None, action_url='/settings/notifications',
                     is_read=True, read_at=now - timedelta(days=7), created_at=now - timedelta(days=7, hours=12)),
            ]

            for n_data in sample:
                db.add(Notification(**n_data))
            db.flush()
            print(f"  [OK] Created {len(sample)} sample notifications")
        else:
            print(f"  [SKIP] Notifications exist ({existing_notifs})")

        # ── 3. Notification Log Entries ───────────────────────────────────
        existing_logs = db.query(NotificationLog).count()
        if existing_logs == 0:
            logs = [
                dict(channel='email', recipient_type='client',
                     recipient_email='john.martinez@riversideprops.com',
                     subject='Invoice INV-00038 from FieldServicePro - $3,200.00',
                     body='Your invoice INV-00038 for $3,200.00 is ready.',
                     status='sent', sent_at=now - timedelta(days=2),
                     entity_type='invoice', entity_id=38, created_at=now - timedelta(days=2)),
                dict(channel='email', recipient_type='client',
                     recipient_email='sarah.chen@mountainviewmed.com',
                     subject='Your HVAC appointment is confirmed - January 16',
                     body='Your HVAC service appointment is confirmed.',
                     status='sent', sent_at=now - timedelta(days=1, hours=6),
                     entity_type='job', entity_id=89, created_at=now - timedelta(days=1, hours=6)),
                dict(channel='sms', recipient_type='client',
                     recipient_phone='+15551234567',
                     body='FieldServicePro: Your tech Mike Johnson is on the way.',
                     status='logged_not_sent', error_message='SMS provider not configured',
                     entity_type='job', entity_id=90, created_at=now - timedelta(hours=5)),
                dict(channel='email', recipient_type='client',
                     recipient_email='facilities@lakesidebiz.com',
                     subject='Your FieldServicePro quote is ready - QTE-00031',
                     body='Your quote for HVAC System Overhaul ($15,800.00) is ready.',
                     status='sent', sent_at=now - timedelta(days=3, hours=2),
                     entity_type='quote', entity_id=31, created_at=now - timedelta(days=3, hours=2)),
                dict(channel='email', recipient_type='client',
                     recipient_email='mgmt@sunsetapartments.com',
                     subject='Payment received - Thank you!',
                     body='We received your payment of $1,850.00. Thank you!',
                     status='sent', sent_at=now - timedelta(days=4),
                     entity_type='invoice', entity_id=35, created_at=now - timedelta(days=4)),
                dict(channel='email', recipient_type='client',
                     recipient_email='badaddress@notreal',
                     subject='Invoice INV-00040 from FieldServicePro',
                     body='Your invoice is ready.',
                     status='failed', error_message='SMTP Error: 550 Invalid recipient',
                     entity_type='invoice', entity_id=40, created_at=now - timedelta(hours=8)),
                dict(channel='email', recipient_type='internal_user',
                     recipient_id=user.id, recipient_email=user.email or 'admin@fieldservicepro.com',
                     subject='[FieldServicePro] SLA At Risk - JOB-00089',
                     body='Job JOB-00089 has a response deadline in 2 hours.',
                     status='sent', sent_at=now - timedelta(hours=1),
                     entity_type='job', entity_id=89, created_at=now - timedelta(hours=1)),
                dict(channel='sms', recipient_type='client',
                     recipient_phone='+15559876543',
                     body='FieldServicePro: Appt confirmed Jan 16 at 9:00 AM. Tech: Mike Johnson.',
                     status='logged_not_sent', error_message='SMS provider not configured',
                     entity_type='job', entity_id=91, created_at=now - timedelta(days=1)),
                dict(channel='email', recipient_type='client',
                     recipient_email='owner@centralplaza.com',
                     subject='Reminder: Your HVAC appointment is tomorrow',
                     body='Reminder your HVAC appointment is tomorrow at 8:00 AM.',
                     status='sent', sent_at=now - timedelta(days=1, hours=14),
                     entity_type='job', entity_id=88, created_at=now - timedelta(days=1, hours=14)),
                dict(channel='email', recipient_type='client',
                     recipient_email='info@harborviewresidences.com',
                     subject='Your Electrical service is complete - Thank you!',
                     body='Your electrical panel upgrade has been completed.',
                     status='sent', sent_at=now - timedelta(days=2, hours=3),
                     entity_type='job', entity_id=87, created_at=now - timedelta(days=2, hours=3)),
                dict(channel='email', recipient_type='client',
                     recipient_email='facilities@lakesidebiz.com',
                     subject='Payment Reminder - Invoice INV-00033',
                     body='Invoice INV-00033 for $4,200.00 is due.',
                     status='sent', sent_at=now - timedelta(days=5),
                     entity_type='invoice', entity_id=33, created_at=now - timedelta(days=5)),
                dict(channel='email', recipient_type='client',
                     recipient_email='contact@kwproperty.com',
                     subject='We received your service request - FieldServicePro',
                     body='We received your HVAC maintenance request.',
                     status='sent', sent_at=now - timedelta(minutes=10),
                     entity_type='request', entity_id=1, created_at=now - timedelta(minutes=10)),
            ]

            for log_data in logs:
                db.add(NotificationLog(**log_data))
            db.flush()
            print(f"  [OK] Created {len(logs)} notification log entries")
        else:
            print(f"  [SKIP] Log entries exist ({existing_logs})")

        db.commit()

        # Count results
        unread = db.query(Notification).filter_by(
            recipient_id=user.id, is_read=False, is_dismissed=False
        ).count()
        templates_count = db.query(ClientNotificationTemplate).count()
        logs_count = db.query(NotificationLog).count()

        print(f"\nNotification seed complete.")
        print(f"  Unread notifications: {unread}")
        print(f"  Client templates:     {templates_count}")
        print(f"  Log entries:          {logs_count}")

    except Exception as e:
        db.rollback()
        print(f"Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == '__main__':
    print("Seeding notification data...\n")
    seed_notifications()
