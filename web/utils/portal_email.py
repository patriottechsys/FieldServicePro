"""Email notification utilities for the client portal.

All functions are safe to call even if Flask-Mail is not configured —
they wrap in try/except to never break the calling flow.
"""
import logging
from flask import current_app, render_template, url_for

logger = logging.getLogger(__name__)

# Flask-Mail instance (initialized lazily)
_mail = None


def _get_mail():
    """Get Flask-Mail instance, creating if needed."""
    global _mail
    if _mail is None:
        try:
            from flask_mail import Mail
            _mail = Mail(current_app)
        except ImportError:
            logger.warning("flask-mail not installed — email notifications disabled")
            return None
        except Exception as e:
            logger.warning(f"Flask-Mail init failed: {e}")
            return None
    return _mail


def send_email(subject, recipients, html_body, text_body=None):
    """Send an email. Returns True on success, False on failure."""
    try:
        mail = _get_mail()
        if not mail:
            logger.info(f"Email skipped (no mail config): {subject} -> {recipients}")
            return False

        from flask_mail import Message
        msg = Message(
            subject=subject,
            recipients=recipients if isinstance(recipients, list) else [recipients],
            html=html_body,
            body=text_body or '',
        )
        mail.send(msg)
        return True
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False


def _get_internal_recipients(roles=('owner', 'admin', 'dispatcher')):
    """Get email addresses of internal users with given roles."""
    from models.database import get_session
    from models.user import User
    db = get_session()
    try:
        users = db.query(User).filter(
            User.role.in_(roles), User.is_active == True
        ).all()
        return [u.email for u in users if u.email]
    finally:
        db.close()


# ── Portal User Emails ────────────────────────────────────────────────────

def send_welcome_email(portal_user, invitation_token):
    """Send welcome/invitation email to new portal user."""
    setup_url = url_for('portal_auth.portal_setup_account', token=invitation_token, _external=True)
    client_name = portal_user.client.display_name if portal_user.client else 'your service provider'
    html = render_template('portal/email/welcome.html',
        user=portal_user, setup_url=setup_url, client_name=client_name)
    send_email(
        subject=f"Welcome to Your Client Portal — {client_name}",
        recipients=portal_user.email,
        html_body=html,
    )


def send_password_reset_email(portal_user, token):
    """Send password reset email."""
    reset_url = url_for('portal_auth.portal_reset_password', token=token, _external=True)
    html = render_template('portal/email/password_reset.html',
        user=portal_user, reset_url=reset_url)
    send_email(
        subject="Password Reset — Client Portal",
        recipients=portal_user.email,
        html_body=html,
    )


# ── Internal Notification Emails ──────────────────────────────────────────

def send_service_request_notification(job, portal_user):
    """Notify internal staff of new service request."""
    recipients = _get_internal_recipients(('owner', 'admin', 'dispatcher'))
    if not recipients:
        return

    prop_name = job.property.display_address if job.property else 'N/A'
    html = render_template('portal/email/generic_notification.html',
        title='New Service Request',
        message=f'{portal_user.full_name} from {portal_user.client.display_name if portal_user.client else "client"} submitted a service request.',
        details=[
            ('Request #', str(job.job_number or job.id)),
            ('Property', prop_name),
            ('Priority', (job.priority or 'normal').title()),
            ('Description', (job.title or job.description or '')[:200]),
        ],
        action_url=url_for('jobs_bp.job_detail', job_id=job.id, _external=True),
        action_text='View Request',
    )
    send_email(
        subject=f"New Portal Service Request #{job.job_number or job.id}",
        recipients=recipients, html_body=html,
    )


def send_quote_approval_notification(quote, portal_user, approved=True, feedback=None):
    """Notify internal staff of quote approval or change request."""
    recipients = _get_internal_recipients(('owner', 'admin'))
    if not recipients:
        return

    client_name = portal_user.client.display_name if portal_user.client else 'client'
    if approved:
        title = f'Quote #{quote.quote_number or quote.id} Approved'
        message = f'{portal_user.full_name} from {client_name} approved quote #{quote.quote_number or quote.id} for ${float(quote.total or 0):,.2f}.'
    else:
        title = f'Quote #{quote.quote_number or quote.id} — Changes Requested'
        message = f'{portal_user.full_name} from {client_name} requested changes to quote #{quote.quote_number or quote.id}.'
        if feedback:
            message += f'\n\nFeedback: {feedback}'

    html = render_template('portal/email/generic_notification.html',
        title=title, message=message, details=[], action_url='#', action_text='View Quote')
    send_email(subject=title, recipients=recipients, html_body=html)


def send_co_approval_notification(co, job, portal_user, approved=True, reason=None):
    """Notify internal staff of change order approval or rejection."""
    recipients = _get_internal_recipients(('owner', 'admin'))
    if not recipients:
        return

    if approved:
        title = f'Change Order {co.change_order_number} Approved'
        message = f'{portal_user.full_name} approved change order {co.change_order_number} for job #{job.job_number or job.id}.'
    else:
        title = f'Change Order {co.change_order_number} Rejected'
        message = f'{portal_user.full_name} rejected change order {co.change_order_number} for job #{job.job_number or job.id}.'
        if reason:
            message += f'\n\nReason: {reason}'

    html = render_template('portal/email/generic_notification.html',
        title=title, message=message, details=[], action_url='#', action_text='View Change Order')
    send_email(subject=title, recipients=recipients, html_body=html)


def send_portal_message_notification(msg, job, portal_user):
    """Notify internal staff of new portal message."""
    recipients = _get_internal_recipients(('owner', 'admin', 'dispatcher'))
    if not recipients:
        return

    client_name = portal_user.client.display_name if portal_user.client else 'client'
    html = render_template('portal/email/generic_notification.html',
        title=f'New Message on Job #{job.job_number or job.id}',
        message=f'{portal_user.full_name} from {client_name} sent a message:\n\n"{msg.message[:300]}"',
        details=[], action_url='#', action_text='View Job')
    send_email(
        subject=f"Portal Message on Job #{job.job_number or job.id} from {portal_user.full_name}",
        recipients=recipients, html_body=html,
    )


def send_portal_user_job_status_email(portal_user, job, new_status):
    """Notify portal user of job status change."""
    status_labels = {
        'scheduled': 'Your service has been scheduled',
        'in_progress': 'Work has started on your service',
        'completed': 'Your service has been completed',
    }
    title = status_labels.get(new_status, f'Job #{job.job_number or job.id} status updated')

    prop_name = job.property.display_address if job.property else 'N/A'
    html = render_template('portal/email/generic_notification.html',
        title=title,
        message=f'Job #{job.job_number or job.id} has been updated to: {new_status.replace("_", " ").title()}',
        details=[
            ('Job', f'#{job.job_number or job.id}'),
            ('Property', prop_name),
            ('Status', new_status.replace('_', ' ').title()),
        ],
        action_url=url_for('portal.portal_job_detail', job_id=job.id, _external=True),
        action_text='View Job Details',
    )
    send_email(subject=title, recipients=portal_user.email, html_body=html)
