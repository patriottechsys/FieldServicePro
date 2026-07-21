"""
NotificationService — central hub for all notification logic.
Usage: NotificationService.notify('job_completed', job, triggered_by=current_user)
"""
import logging
from datetime import timezone, datetime
from typing import Optional, List, Dict, Any

from models.database import get_session
from models.notification import (
    Notification, NotificationPreference, ClientNotificationTemplate,
    NotificationLog, CATEGORY_ICONS, TYPE_COLORS,
)
from models.user import User

log = logging.getLogger(__name__)

# Event -> (category, type, priority)
EVENT_META = {
    'job_created':        ('job_update', 'info', 'normal'),
    'job_scheduled':      ('schedule_change', 'info', 'normal'),
    'job_status_changed': ('job_update', 'info', 'normal'),
    'job_completed':      ('job_update', 'success', 'normal'),
    'job_on_hold':        ('job_update', 'warning', 'high'),
    'request_new':        ('request_new', 'info', 'normal'),
    'quote_sent':         ('quote_update', 'info', 'normal'),
    'quote_approved':     ('quote_update', 'success', 'normal'),
    'invoice_issued':     ('invoice_update', 'info', 'normal'),
    'invoice_overdue':    ('invoice_update', 'danger', 'high'),
    'payment_received':   ('invoice_update', 'success', 'normal'),
    'approval_needed_expense':    ('approval_needed', 'action_required', 'high'),
    'approval_needed_invoice':    ('approval_needed', 'action_required', 'high'),
    'approval_needed_change_order': ('approval_needed', 'action_required', 'high'),
    'item_approved':      ('approval_needed', 'success', 'normal'),
    'item_rejected':      ('approval_needed', 'danger', 'high'),
    'warranty_expiring':  ('warranty_alert', 'warning', 'high'),
    'callback_created':   ('callback_alert', 'warning', 'high'),
    'contract_expiring':  ('contract_alert', 'warning', 'high'),
    'sla_breached':       ('contract_alert', 'danger', 'urgent'),
    'expense_submitted':  ('expense_update', 'info', 'normal'),
    'follow_up_due':      ('communication_follow_up', 'warning', 'normal'),
    'follow_up_overdue':  ('communication_follow_up', 'danger', 'high'),
    'recurring_job_generated': ('job_update', 'info', 'normal'),
    'schedule_changed':   ('schedule_change', 'warning', 'normal'),
    'contract_expired':   ('contract_alert', 'danger', 'high'),
    'warranty_created':   ('warranty_alert', 'info', 'normal'),
    'system':             ('system', 'info', 'normal'),
}

# Event -> roles that receive the notification
EVENT_ROLES = {
    'job_created': ['admin', 'dispatcher'],
    'job_scheduled': ['__assigned_tech__'],
    'job_status_changed': ['admin', 'dispatcher'],
    'job_completed': ['admin'],
    'request_new': ['admin', 'dispatcher'],
    'quote_approved': ['admin'],
    'invoice_overdue': ['admin'],
    'payment_received': ['admin'],
    'approval_needed_expense': ['admin', 'owner'],
    'approval_needed_invoice': ['admin', 'owner'],
    'approval_needed_change_order': ['admin', 'owner'],
    'item_approved': ['__submitter__'],
    'item_rejected': ['__submitter__'],
    'warranty_expiring': ['admin'],
    'callback_created': ['admin'],
    'contract_expiring': ['admin'],
    'expense_submitted': ['admin', 'owner'],
    'follow_up_due': ['__submitter__'],
    'follow_up_overdue': ['admin', '__submitter__'],
    'schedule_changed': ['__assigned_tech__'],
    'contract_expired': ['admin', 'owner'],
    'warranty_created': ['admin'],
    'quote_sent': ['admin'],
    'system': ['admin', 'owner'],
}

# Event -> (title_template, message_template)
EVENT_TEMPLATES = {
    'job_created': ('New Job Created', 'Job {job_number} created for {client_name}.'),
    'job_scheduled': ('Job Assigned', 'You have been assigned to job {job_number}.'),
    'job_status_changed': ('Job Status Updated', 'Job {job_number} status changed to {status}.'),
    'job_completed': ('Job Completed', 'Job {job_number} has been completed.'),
    'request_new': ('New Service Request', 'New request received from {client_name}.'),
    'quote_approved': ('Quote Approved', 'Quote {quote_number} approved by {client_name}.'),
    'invoice_overdue': ('Invoice Overdue', 'Invoice {invoice_number} is past due.'),
    'payment_received': ('Payment Received', 'Payment received from {client_name}.'),
    'approval_needed_expense': ('Expense Approval Required', 'An expense requires your approval.'),
    'item_approved': ('Item Approved', 'Your submission has been approved.'),
    'item_rejected': ('Item Rejected', 'Your submission has been rejected.'),
    'warranty_expiring': ('Warranty Expiring', 'A warranty is expiring within 30 days.'),
    'callback_created': ('Callback Created', 'A callback has been created.'),
    'expense_submitted': ('Expense Submitted', 'An expense has been submitted for approval.'),
    'follow_up_due': ('Follow-Up Due', 'A follow-up is due today.'),
    'follow_up_overdue': ('Follow-Up Overdue', 'An overdue follow-up requires attention.'),
    'schedule_changed': ('Schedule Changed', 'Job {job_number} has been rescheduled to {scheduled_date}.'),
    'contract_expired': ('Contract Expired', 'A contract has expired.'),
    'warranty_created': ('Warranty Created', 'Warranty {warranty_number} has been created.'),
    'quote_sent': ('Quote Sent', 'Quote {quote_number} has been sent to {client_name}.'),
    'recurring_job_generated': ('Recurring Job Created', 'A recurring job has been generated.'),
    'system': ('System Notification', 'A system event occurred.'),
}


class NotificationService:

    @staticmethod
    def notify(event, entity=None, triggered_by=None, extra_context=None,
               override_recipients=None, title=None, message=None):
        """Main entry point. Create in-app notifications for an event."""
        db = get_session()
        created = []
        try:
            context = NotificationService._build_context(entity, extra_context)
            cat, ntype, priority = EVENT_META.get(event, ('other', 'info', 'normal'))

            # Build title/message
            t_tmpl, m_tmpl = EVENT_TEMPLATES.get(event, ('Notification', 'An event occurred.'))
            final_title = title or NotificationService._render(t_tmpl, context)
            final_message = message or NotificationService._render(m_tmpl, context)

            # Entity info
            entity_type = type(entity).__name__.lower() if entity else None
            entity_id = getattr(entity, 'id', None)
            action_url = NotificationService._build_url(entity_type, entity_id)

            # Get recipients
            if override_recipients:
                recipients = override_recipients
            else:
                recipients = NotificationService._resolve_recipients(event, entity, triggered_by, db)

            triggered_id = triggered_by.id if triggered_by else None

            for user in recipients:
                notif = Notification(
                    recipient_id=user.id, title=final_title, message=final_message,
                    notification_type=ntype, category=cat, priority=priority,
                    entity_type=entity_type, entity_id=entity_id, action_url=action_url,
                    is_actionable=(ntype == 'action_required'),
                    triggered_by=triggered_id,
                )
                db.add(notif)
                created.append(notif)

            db.commit()
        except Exception as e:
            db.rollback()
            log.exception("NotificationService.notify failed: %s", e)
        finally:
            db.close()
        return created

    @staticmethod
    def get_unread_count(user_id):
        db = get_session()
        try:
            return db.query(Notification).filter(
                Notification.recipient_id == user_id,
                Notification.is_read == False,
                Notification.is_dismissed == False,
            ).count()
        finally:
            db.close()

    @staticmethod
    def mark_all_read(user_id):
        db = get_session()
        try:
            now = datetime.now(timezone.utc)
            notifs = db.query(Notification).filter(
                Notification.recipient_id == user_id,
                Notification.is_read == False, Notification.is_dismissed == False,
            ).all()
            for n in notifs:
                n.is_read = True
                n.read_at = now
            db.commit()
            return len(notifs)
        finally:
            db.close()

    @staticmethod
    def _resolve_recipients(event, entity, triggered_by, db):
        roles = EVENT_ROLES.get(event, [])
        users = []
        seen = set()

        for role in roles:
            if role == '__assigned_tech__':
                tu = NotificationService._get_tech_user(entity, db)
                if tu and tu.id not in seen:
                    seen.add(tu.id); users.append(tu)
            elif role == '__submitter__':
                su = NotificationService._get_submitter(entity, db)
                if su and su.id not in seen:
                    seen.add(su.id); users.append(su)
            else:
                for u in db.query(User).filter(User.role == role, User.is_active == True).all():
                    if u.id not in seen:
                        seen.add(u.id); users.append(u)

        if triggered_by:
            users = [u for u in users if u.id != triggered_by.id]
        return users

    @staticmethod
    def _get_tech_user(entity, db):
        if hasattr(entity, 'technician') and entity.technician and entity.technician.user_id:
            return db.query(User).filter_by(id=entity.technician.user_id).first()
        return None

    @staticmethod
    def _get_submitter(entity, db):
        for attr in ('created_by', 'created_by_id'):
            uid = getattr(entity, attr, None)
            if uid:
                return db.query(User).filter_by(id=uid).first()
        return None

    @staticmethod
    def _build_context(entity, extra=None):
        ctx = {}
        if entity:
            for attr in ('job_number', 'quote_number', 'invoice_number', 'request_number',
                         'expense_number', 'warranty_number', 'status', 'title'):
                val = getattr(entity, attr, None)
                if val:
                    ctx[attr] = str(val)
            if hasattr(entity, 'client') and entity.client:
                ctx['client_name'] = entity.client.display_name
        if extra:
            ctx.update(extra)
        return ctx

    @staticmethod
    def _render(template, context):
        class SafeDict(dict):
            def __missing__(self, key): return f'{{{key}}}'
        try:
            return template.format_map(SafeDict(context))
        except Exception:
            return template

    @staticmethod
    def _build_url(entity_type, entity_id):
        if not entity_type or not entity_id:
            return '/notifications'
        url_map = {
            'job': f'/jobs/{entity_id}', 'quote': f'/quotes/{entity_id}',
            'invoice': f'/invoices/{entity_id}', 'expense': f'/expenses/{entity_id}',
            'warranty': f'/warranties/{entity_id}', 'callback': f'/callbacks/{entity_id}',
            'contract': f'/contracts/{entity_id}',
            'servicerequest': f'/requests/{entity_id}',
            'changeorder': f'/change-orders',
            'communicationlog': f'/communications',
        }
        return url_map.get(entity_type, '/notifications')
