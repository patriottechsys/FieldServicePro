"""Feedback utilities: survey delivery, stats, NPS, notifications."""
import os
import logging
from datetime import timezone, datetime, timedelta
from sqlalchemy import func

logger = logging.getLogger(__name__)


def _get_base_url():
    """Get base URL for survey links."""
    try:
        from flask import current_app, request as _req
        return current_app.config.get('BASE_URL',
               os.environ.get('BASE_URL', _req.host_url.rstrip('/')))
    except RuntimeError:
        return os.environ.get('BASE_URL', 'http://localhost:5000')


def get_default_template(db):
    """Get the default active survey template."""
    from models.feedback_survey import SurveyTemplate
    t = db.query(SurveyTemplate).filter_by(is_default=True, is_active=True).first()
    if not t:
        t = db.query(SurveyTemplate).filter_by(is_active=True).first()
    return t


def auto_send_survey(db, job, settings=None):
    """Called after job completion. Creates FeedbackSurvey and sends email.
    Returns the FeedbackSurvey or None.
    """
    from models.feedback_survey import FeedbackSurvey
    from models.client import Client
    from models.app_settings import AppSettings
    from web.utils.booking_utils import get_booking_settings, get_org_context

    if settings is None:
        settings = get_booking_settings()

    if not settings.auto_send_survey:
        return None

    client = db.query(Client).filter_by(id=job.client_id).first() if job.client_id else None
    if not client or not client.email:
        return None

    # Don't send duplicate
    existing = db.query(FeedbackSurvey).filter_by(job_id=job.id).filter(
        FeedbackSurvey.status.in_(['sent', 'opened', 'completed']),
    ).first()
    if existing:
        return None

    template = get_default_template(db)
    expiry_days = settings.survey_expiry_days
    tech_id = job.assigned_technician_id if hasattr(job, 'assigned_technician_id') else None

    survey = FeedbackSurvey(
        survey_number=FeedbackSurvey.generate_number(db),
        job_id=job.id,
        client_id=client.id,
        technician_id=tech_id,
        template_id=template.id if template else None,
        status='sent',
        sent_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=expiry_days),
    )
    db.add(survey)
    db.flush()

    # Send email
    try:
        org = get_org_context()
        send_survey_email(db, survey, client, job, org, settings)
    except Exception as e:
        logger.warning(f'Survey email failed: {e}')

    return survey


def send_survey_email(db, survey, client, job, org, settings=None):
    """Send the initial survey request email."""
    from web.utils.email_service import EmailService

    client_name = client.display_name if hasattr(client, 'display_name') else (client.company_name or 'there')
    job_desc = job.title or job.job_type or 'recent service'
    org_name = org.get('name', 'FieldServicePro') if isinstance(org, dict) else 'FieldServicePro'
    survey_url = f"{_get_base_url()}/feedback/{survey.token}"
    expiry = settings.survey_expiry_days if settings else 30

    subject = f'How was your {job_desc} service? — {org_name}'
    html = f"""
    <div style="font-family:sans-serif;max-width:540px;margin:0 auto;">
      <div style="background:#1a56db;padding:18px 24px;border-radius:8px 8px 0 0;">
        <h2 style="color:#fff;margin:0;">{org_name}</h2>
      </div>
      <div style="background:#fff;padding:24px;border:1px solid #e2e8f0;border-radius:0 0 8px 8px;">
        <p>Hi {client_name},</p>
        <p>We recently completed <strong>{job_desc}</strong> for you.
           We'd love to hear how it went — it takes less than 2 minutes!</p>
        <div style="text-align:center;margin:24px 0;">
          <a href="{survey_url}"
             style="background:#1a56db;color:#fff;padding:12px 28px;border-radius:8px;
                    text-decoration:none;font-weight:700;font-size:1rem;display:inline-block;">
            &#9733; Share Your Feedback
          </a>
        </div>
        <p style="color:#64748b;font-size:.85rem;">
          Your feedback helps us improve. This link expires in {expiry} days.
        </p>
      </div>
    </div>
    """
    try:
        EmailService.send_client_email(to_email=client.email, subject=subject, body_html=html)
    except Exception as e:
        logger.warning(f'Survey email send failed: {e}')


def send_reminder_email(survey, org):
    """Send a reminder for an incomplete survey."""
    from web.utils.email_service import EmailService

    client = survey.client
    if not client or not client.email:
        raise ValueError('No client email for reminder')

    org_name = org.get('name', 'FieldServicePro') if isinstance(org, dict) else 'FieldServicePro'
    job_desc = survey.job.title if survey.job else 'recent service'
    survey_url = f"{_get_base_url()}/feedback/{survey.token}"

    subject = f'Reminder: We\'d love your feedback — {org_name}'
    html = f"""
    <div style="font-family:sans-serif;max-width:540px;margin:0 auto;padding:24px;">
      <h3>Quick Reminder</h3>
      <p>Hi {client.display_name if hasattr(client, 'display_name') else 'there'},</p>
      <p>We sent you a short survey about your <strong>{job_desc}</strong>
         but haven't heard back. It only takes a minute!</p>
      <div style="text-align:center;margin:20px 0;">
        <a href="{survey_url}"
           style="background:#1a56db;color:#fff;padding:12px 24px;border-radius:8px;
                  text-decoration:none;font-weight:700;">Share Feedback Now</a>
      </div>
      <p style="font-size:.8rem;color:#94a3b8;">This is the only reminder we'll send.</p>
    </div>
    """
    EmailService.send_client_email(to_email=client.email, subject=subject, body_html=html)


def get_feedback_stats(db):
    """Return aggregate feedback statistics."""
    from models.feedback_survey import FeedbackSurvey

    total = db.query(FeedbackSurvey).filter_by(status='completed').count()
    avg_rating = db.query(func.avg(FeedbackSurvey.overall_rating)).filter(
        FeedbackSurvey.status == 'completed',
        FeedbackSurvey.overall_rating.isnot(None),
    ).scalar()

    recommend_yes = db.query(FeedbackSurvey).filter(
        FeedbackSurvey.status == 'completed',
        FeedbackSurvey.would_recommend == True,
    ).count()

    pending = db.query(FeedbackSurvey).filter(
        FeedbackSurvey.status.in_(['sent', 'opened']),
    ).count()

    follow_up_needed = db.query(FeedbackSurvey).filter(
        FeedbackSurvey.follow_up_required == True,
        FeedbackSurvey.follow_up_completed == False,
    ).count()

    # NPS
    nps_surveys = db.query(FeedbackSurvey).filter(
        FeedbackSurvey.status == 'completed',
        FeedbackSurvey.nps_score.isnot(None),
    ).all()
    nps_score = None
    if nps_surveys:
        promoters = sum(1 for s in nps_surveys if s.nps_score >= 9)
        detractors = sum(1 for s in nps_surveys if s.nps_score <= 6)
        nps_score = round(((promoters - detractors) / len(nps_surveys)) * 100)

    # Response rate
    total_sent = db.query(FeedbackSurvey).count()
    response_rate = round((total / total_sent) * 100, 1) if total_sent else 0

    # Negative last 30d
    thirty_ago = datetime.now(timezone.utc) - timedelta(days=30)
    negative_30d = db.query(FeedbackSurvey).filter(
        FeedbackSurvey.status == 'completed',
        FeedbackSurvey.overall_rating <= 2,
        FeedbackSurvey.completed_at >= thirty_ago,
    ).count()

    return {
        'avg_overall': round(float(avg_rating), 1) if avg_rating else None,
        'nps_score': nps_score,
        'total_reviews': total,
        'response_rate': response_rate,
        'would_recommend_pct': round((recommend_yes / total) * 100) if total else None,
        'pending_count': pending,
        'follow_up_needed': follow_up_needed,
        'negative_30d': negative_30d,
    }


def compute_nps(db, tech_id=None, since=None):
    """Compute NPS for a technician or overall."""
    from models.feedback_survey import FeedbackSurvey
    q = db.query(FeedbackSurvey).filter(
        FeedbackSurvey.status == 'completed',
        FeedbackSurvey.nps_score.isnot(None),
    )
    if tech_id:
        q = q.filter(FeedbackSurvey.technician_id == tech_id)
    if since:
        q = q.filter(FeedbackSurvey.completed_at >= since)
    surveys = q.all()
    if not surveys:
        return None
    promoters = sum(1 for s in surveys if s.nps_score >= 9)
    detractors = sum(1 for s in surveys if s.nps_score <= 6)
    return round(((promoters - detractors) / len(surveys)) * 100)


def notify_on_survey_completion(db, survey, settings):
    """Notify admins/techs based on survey rating."""
    from models.notification import Notification
    from models.user import User

    threshold = settings.feedback_notification_threshold if settings else 2
    rating = survey.overall_rating or 0
    client_name = survey.client.display_name if survey.client else 'A customer'

    if rating <= threshold:
        title = f'Low Rating Alert: {survey.star_display}'
        message = f'{client_name} rated {rating}/5 — follow-up needed'
        priority = 'high'
    elif rating == 3:
        title = f'Survey Completed — {rating}/5'
        message = f'{client_name} gave a neutral rating.'
        priority = 'normal'
    else:
        title = f'Positive Feedback — {rating}/5'
        message = f'{client_name} rated {rating}/5!'
        priority = 'low'

    # Notify admins/dispatchers
    targets = db.query(User).filter(
        User.role.in_(['admin', 'owner', 'dispatcher']),
        User.is_active == True,
    ).all()

    for user in targets:
        notif = Notification(
            recipient_id=user.id,
            title=title,
            message=message,
            notification_type='feedback',
            priority=priority,
            action_url=f'/feedback/detail/{survey.id}',
        )
        db.add(notif)

    # Also notify the technician if low rating
    if rating <= threshold and survey.technician_id:
        from models.technician import Technician
        tech = db.query(Technician).filter_by(id=survey.technician_id).first()
        if tech and tech.user_id:
            notif = Notification(
                recipient_id=tech.user_id,
                title=f'Feedback received — {rating}/5',
                message=f'A customer rated your service {rating}/5. Please review.',
                notification_type='feedback',
                priority='high',
                action_url=f'/feedback/detail/{survey.id}',
            )
            db.add(notif)
