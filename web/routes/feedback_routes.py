"""Customer Feedback Blueprint — /feedback
Public survey form + admin dashboard, list, detail, templates.
"""
from datetime import datetime, timedelta
from flask import (Blueprint, render_template, request, redirect,
                   url_for, jsonify, flash, abort, current_app)
from flask_login import login_required, current_user
from sqlalchemy import func, desc

from models.database import get_session
from models.feedback_survey import FeedbackSurvey, SurveyTemplate
from models.job import Job
from models.client import Client
from models.technician import Technician
from web.auth import role_required
from web.utils.booking_utils import get_org_context, get_booking_settings
from web.utils.feedback_utils import (
    get_feedback_stats, send_survey_email, send_reminder_email,
    notify_on_survey_completion,
)

feedback_bp = Blueprint('feedback', __name__, url_prefix='/feedback')


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC — Survey Form (token-based, no auth)
# ═══════════════════════════════════════════════════════════════════════

@feedback_bp.route('/<token>')
def survey(token):
    """Display the survey form (public)."""
    db = get_session()
    try:
        org = get_org_context()
        sv = db.query(FeedbackSurvey).filter_by(token=token).first()
        if not sv:
            abort(404)

        if sv.status == 'completed':
            return render_template('feedback/already_completed.html', org=org, now=datetime.now())

        if sv.is_expired or sv.status == 'expired':
            sv.status = 'expired'
            db.commit()
            return render_template('feedback/expired.html', org=org, now=datetime.now())

        if sv.status == 'sent':
            sv.status = 'opened'
            sv.opened_at = datetime.now()
            db.commit()

        return render_template('feedback/survey.html',
            org=org, survey=sv, job=sv.job, client=sv.client,
            tech=sv.technician, tmpl=sv.template, token=token, now=datetime.now(),
        )
    finally:
        db.close()


@feedback_bp.route('/<token>/submit', methods=['POST'])
def survey_submit(token):
    """Process survey submission (public)."""
    db = get_session()
    try:
        org = get_org_context()
        sv = db.query(FeedbackSurvey).filter_by(token=token).first()
        if not sv:
            abort(404)
        if sv.status == 'completed':
            return render_template('feedback/already_completed.html', org=org, now=datetime.now())

        def safe_int(key, lo=1, hi=5):
            try:
                v = int(request.form.get(key, ''))
                return v if lo <= v <= hi else None
            except (TypeError, ValueError):
                return None

        sv.overall_rating = safe_int('overall_rating')
        sv.quality_rating = safe_int('quality_rating')
        sv.punctuality_rating = safe_int('punctuality_rating')
        sv.communication_rating = safe_int('communication_rating')
        sv.professionalism_rating = safe_int('professionalism_rating')
        sv.value_rating = safe_int('value_rating')
        sv.nps_score = safe_int('nps_score', 0, 10)
        sv.would_recommend = request.form.get('would_recommend') == 'yes'
        sv.comments = (request.form.get('comments', '')[:2000]).strip() or None
        sv.what_went_well = (request.form.get('what_went_well', '')[:2000]).strip() or None
        sv.what_could_improve = (request.form.get('what_could_improve', '')[:2000]).strip() or None

        sv.status = 'completed'
        sv.completed_at = datetime.now()
        sv.ip_address = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()[:45]
        sv.user_agent = (request.user_agent.string[:500]) if request.user_agent else None

        # Auto flag low ratings
        settings = get_booking_settings()
        threshold = settings.feedback_notification_threshold
        if sv.overall_rating and sv.overall_rating <= threshold:
            sv.follow_up_required = True

        db.commit()

        # Notifications
        try:
            notify_on_survey_completion(db, sv, settings)
        except Exception as e:
            current_app.logger.warning(f'Survey notification error: {e}')

        # Google review prompt
        show_google = False
        google_url = None
        if sv.overall_rating and sv.overall_rating >= settings.google_review_prompt_threshold:
            google_url = settings.google_review_url
            if google_url:
                show_google = True

        return render_template('feedback/thank_you.html',
            org=org, survey=sv, show_google_prompt=show_google,
            google_url=google_url, now=datetime.now(),
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# ADMIN — Dashboard, List, Detail
# ═══════════════════════════════════════════════════════════════════════

@feedback_bp.route('/dashboard')
@login_required
def dashboard():
    """Feedback analytics dashboard."""
    db = get_session()
    try:
        stats = get_feedback_stats(db)

        # Recent feedback
        recent = db.query(FeedbackSurvey).filter_by(
            status='completed',
        ).order_by(desc(FeedbackSurvey.completed_at)).limit(10).all()

        # Rating distribution
        dist_raw = db.query(
            FeedbackSurvey.overall_rating,
            func.count(FeedbackSurvey.id),
        ).filter(
            FeedbackSurvey.status == 'completed',
            FeedbackSurvey.overall_rating.isnot(None),
        ).group_by(FeedbackSurvey.overall_rating).all()
        dist_dict = {r: c for r, c in dist_raw}

        return render_template('feedback/dashboard.html',
            active_page='feedback', user=current_user,
            stats=stats, recent=recent, dist_dict=dist_dict, now=datetime.now(),
        )
    finally:
        db.close()


@feedback_bp.route('/list')
@login_required
def list_feedback():
    """List all completed feedback."""
    db = get_session()
    try:
        q = db.query(FeedbackSurvey).filter_by(status='completed')

        tech_id = request.args.get('tech_id', type=int)
        rating_min = request.args.get('rating_min', type=int)
        follow_up = request.args.get('follow_up') == '1'

        if tech_id:
            q = q.filter(FeedbackSurvey.technician_id == tech_id)
        if rating_min:
            q = q.filter(FeedbackSurvey.overall_rating >= rating_min)
        if follow_up:
            q = q.filter(FeedbackSurvey.follow_up_required == True)

        surveys = q.order_by(desc(FeedbackSurvey.completed_at)).all()
        technicians = db.query(Technician).filter_by(is_active=True).all()

        return render_template('feedback/list.html',
            active_page='feedback', user=current_user,
            surveys=surveys, technicians=technicians,
            filters=request.args, now=datetime.now(),
        )
    finally:
        db.close()


@feedback_bp.route('/detail/<int:survey_id>')
@login_required
def detail(survey_id):
    """Survey detail view."""
    db = get_session()
    try:
        sv = db.query(FeedbackSurvey).filter_by(id=survey_id).first()
        if not sv:
            abort(404)
        return render_template('feedback/detail.html',
            active_page='feedback', user=current_user,
            survey=sv, now=datetime.now(),
        )
    finally:
        db.close()


@feedback_bp.route('/detail/<int:survey_id>/update', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def update_survey(survey_id):
    """Update admin fields on a survey."""
    db = get_session()
    try:
        sv = db.query(FeedbackSurvey).filter_by(id=survey_id).first()
        if not sv:
            abort(404)
        sv.is_public = 'is_public' in request.form
        sv.follow_up_required = 'follow_up_required' in request.form
        sv.follow_up_completed = 'follow_up_completed' in request.form
        sv.follow_up_notes = request.form.get('follow_up_notes', '').strip()[:1000]
        sv.internal_notes = request.form.get('internal_notes', '').strip()[:2000]
        db.commit()
        flash('Survey updated.', 'success')
    finally:
        db.close()
    return redirect(url_for('feedback.detail', survey_id=survey_id))


@feedback_bp.route('/pending')
@login_required
def pending():
    """Pending/open surveys."""
    db = get_session()
    try:
        surveys = db.query(FeedbackSurvey).filter(
            FeedbackSurvey.status.in_(['sent', 'opened']),
        ).order_by(FeedbackSurvey.sent_at).all()
        return render_template('feedback/pending.html',
            active_page='feedback', user=current_user,
            surveys=surveys, now=datetime.now(),
        )
    finally:
        db.close()


@feedback_bp.route('/<int:survey_id>/send-reminder', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def send_reminder(survey_id):
    """Send reminder email for an open survey."""
    db = get_session()
    try:
        sv = db.query(FeedbackSurvey).filter_by(id=survey_id).first()
        if not sv or sv.status not in ('sent', 'opened'):
            flash('Cannot send reminder.', 'error')
            return redirect(url_for('feedback.pending'))
        if sv.reminder_sent:
            flash('Reminder already sent.', 'warning')
            return redirect(url_for('feedback.pending'))

        org = get_org_context()
        send_reminder_email(sv, org)
        sv.reminder_sent = True
        sv.reminder_sent_at = datetime.now()
        db.commit()
        flash('Reminder sent.', 'success')
    except Exception as e:
        flash(f'Failed: {e}', 'error')
    finally:
        db.close()
    return redirect(url_for('feedback.pending'))


@feedback_bp.route('/<int:survey_id>/cancel', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def cancel_survey(survey_id):
    """Cancel a pending survey."""
    db = get_session()
    try:
        sv = db.query(FeedbackSurvey).filter_by(id=survey_id).first()
        if sv:
            sv.status = 'expired'
            db.commit()
            flash('Survey cancelled.', 'success')
    finally:
        db.close()
    return redirect(url_for('feedback.pending'))


@feedback_bp.route('/follow-ups')
@login_required
@role_required('admin', 'owner', 'dispatcher')
def follow_ups():
    """Open and recently completed follow-ups."""
    db = get_session()
    try:
        from sqlalchemy import desc
        open_fups = db.query(FeedbackSurvey).filter(
            FeedbackSurvey.follow_up_required == True,
            FeedbackSurvey.follow_up_completed == False,
            FeedbackSurvey.status == 'completed',
        ).order_by(FeedbackSurvey.completed_at).all()

        recent_completed = db.query(FeedbackSurvey).filter(
            FeedbackSurvey.follow_up_required == True,
            FeedbackSurvey.follow_up_completed == True,
        ).order_by(desc(FeedbackSurvey.updated_at)).limit(20).all()

        return render_template('feedback/follow_ups.html',
            active_page='feedback', user=current_user,
            open_fups=open_fups, recent_completed=recent_completed,
            now=datetime.now(),
        )
    finally:
        db.close()


@feedback_bp.route('/send-manual', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def send_survey_manual():
    """Manually send a feedback survey for a completed job."""
    job_id = request.form.get('job_id', type=int)
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id).first()
        if not job:
            flash('Job not found.', 'error')
            return redirect(request.referrer or url_for('feedback.dashboard'))

        from web.utils.feedback_utils import auto_send_survey
        from web.utils.booking_utils import get_booking_settings
        settings = get_booking_settings()
        survey = auto_send_survey(db, job, settings)
        db.commit()

        if survey:
            flash('Feedback request sent.', 'success')
        else:
            flash('Could not send — check client email or existing survey.', 'warning')
    finally:
        db.close()
    return redirect(url_for('jobs_bp.job_detail', job_id=job_id))


@feedback_bp.route('/technician/<int:tech_id>')
@login_required
def technician_feedback(tech_id):
    """Technician-specific feedback stats and history."""
    db = get_session()
    try:
        tech = db.query(Technician).filter_by(id=tech_id).first()
        if not tech:
            abort(404)

        # Permission: techs can only see their own
        if current_user.role == 'technician':
            from models.technician import Technician as T
            own_tech = db.query(T).filter_by(user_id=current_user.id).first()
            if not own_tech or own_tech.id != tech_id:
                abort(403)

        surveys = db.query(FeedbackSurvey).filter(
            FeedbackSurvey.technician_id == tech_id,
            FeedbackSurvey.status == 'completed',
        ).order_by(desc(FeedbackSurvey.completed_at)).all()

        def avg_field(field):
            vals = [getattr(s, field) for s in surveys if getattr(s, field) is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        from web.utils.feedback_utils import compute_nps
        stats = {
            'total': len(surveys),
            'avg_overall': avg_field('overall_rating'),
            'avg_quality': avg_field('quality_rating'),
            'avg_punctuality': avg_field('punctuality_rating'),
            'avg_communication': avg_field('communication_rating'),
            'avg_professionalism': avg_field('professionalism_rating'),
            'nps': compute_nps(db, tech_id=tech_id),
            'recommend_pct': (
                round(sum(1 for s in surveys if s.would_recommend) /
                      len([s for s in surveys if s.would_recommend is not None]) * 100)
                if any(s.would_recommend is not None for s in surveys) else None
            ),
        }

        is_own = current_user.role == 'technician'

        return render_template('feedback/technician_feedback.html',
            active_page='feedback', user=current_user,
            tech=tech, surveys=surveys, stats=stats,
            is_own_profile=is_own, now=datetime.now(),
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# Survey Templates CRUD
# ═══════════════════════════════════════════════════════════════════════

@feedback_bp.route('/templates')
@login_required
@role_required('admin', 'owner')
def templates():
    """List survey templates."""
    db = get_session()
    try:
        tmpl_list = db.query(SurveyTemplate).filter_by(is_active=True).all()
        return render_template('feedback/templates.html',
            active_page='feedback', user=current_user,
            templates=tmpl_list, now=datetime.now(),
        )
    finally:
        db.close()


@feedback_bp.route('/templates/new', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'owner')
def template_new():
    """Create a new survey template."""
    db = get_session()
    try:
        if request.method == 'POST':
            t = SurveyTemplate(
                name=request.form.get('name', '').strip(),
                description=request.form.get('description', '').strip(),
                include_quality='include_quality' in request.form,
                include_punctuality='include_punctuality' in request.form,
                include_communication='include_communication' in request.form,
                include_professionalism='include_professionalism' in request.form,
                include_value='include_value' in request.form,
                include_nps='include_nps' in request.form,
                include_recommend='include_recommend' in request.form,
                include_comments='include_comments' in request.form,
                include_what_went_well='include_what_went_well' in request.form,
                include_what_could_improve='include_what_could_improve' in request.form,
                is_default='is_default' in request.form,
                is_active=True,
                created_by=current_user.id,
            )
            if t.is_default:
                db.query(SurveyTemplate).update({'is_default': False})
            db.add(t)
            db.commit()
            flash('Template created.', 'success')
            return redirect(url_for('feedback.templates'))

        return render_template('feedback/template_form.html',
            active_page='feedback', user=current_user,
            tmpl=None, action='new', now=datetime.now(),
        )
    finally:
        db.close()


@feedback_bp.route('/templates/<int:tmpl_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'owner')
def template_edit(tmpl_id):
    """Edit a survey template."""
    db = get_session()
    try:
        t = db.query(SurveyTemplate).filter_by(id=tmpl_id).first()
        if not t:
            abort(404)

        if request.method == 'POST':
            t.name = request.form.get('name', '').strip()
            t.description = request.form.get('description', '').strip()
            t.include_quality = 'include_quality' in request.form
            t.include_punctuality = 'include_punctuality' in request.form
            t.include_communication = 'include_communication' in request.form
            t.include_professionalism = 'include_professionalism' in request.form
            t.include_value = 'include_value' in request.form
            t.include_nps = 'include_nps' in request.form
            t.include_recommend = 'include_recommend' in request.form
            t.include_comments = 'include_comments' in request.form
            t.include_what_went_well = 'include_what_went_well' in request.form
            t.include_what_could_improve = 'include_what_could_improve' in request.form
            if 'is_default' in request.form:
                db.query(SurveyTemplate).update({'is_default': False})
                t.is_default = True
            db.commit()
            flash('Template updated.', 'success')
            return redirect(url_for('feedback.templates'))

        return render_template('feedback/template_form.html',
            active_page='feedback', user=current_user,
            tmpl=t, action='edit', now=datetime.now(),
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# JSON API
# ═══════════════════════════════════════════════════════════════════════

@feedback_bp.route('/api/stats')
@login_required
def api_stats():
    """JSON feedback stats for dashboard widgets."""
    db = get_session()
    try:
        stats = get_feedback_stats(db)
        return jsonify(stats)
    finally:
        db.close()
