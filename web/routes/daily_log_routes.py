"""Daily Log routes — list, create, edit, detail, review, print, calendar."""
import json
from datetime import timezone, date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from models.database import get_session
from models.daily_log import DailyLog, WEATHER_IMPACTS, DAILY_LOG_STATUSES
from models.project import Project
from models.job import Job
from models.user import User
from models.division import Division
from web.auth import role_required

daily_log_bp = Blueprint('daily_logs', __name__)


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(val, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _parse_crew(form):
    crew = []
    trades = form.getlist('crew_trade[]')
    counts = form.getlist('crew_count[]')
    names = form.getlist('crew_names[]')
    for i, trade in enumerate(trades):
        if trade:
            crew.append({
                'trade': trade,
                'count': int(counts[i]) if i < len(counts) and counts[i] else 0,
                'names': names[i] if i < len(names) else '',
            })
    return json.dumps(crew) if crew else None


# ── List ──────────────────────────────────────────────────────────────────────

@daily_log_bp.route('/daily-logs')
@login_required
def daily_log_list():
    db = get_session()
    try:
        org_id = current_user.organization_id
        project_id = request.args.get('project_id', type=int)
        status_filter = request.args.get('status', '')
        date_from = _parse_date(request.args.get('date_from'))
        date_to = _parse_date(request.args.get('date_to'))

        q = db.query(DailyLog).join(Project).filter(Project.organization_id == org_id)
        if project_id:
            q = q.filter(DailyLog.project_id == project_id)
        if status_filter:
            q = q.filter(DailyLog.status == status_filter)
        if date_from:
            q = q.filter(DailyLog.log_date >= date_from)
        if date_to:
            q = q.filter(DailyLog.log_date <= date_to)

        logs = q.order_by(DailyLog.log_date.desc()).all()
        projects = db.query(Project).filter_by(organization_id=org_id).order_by(Project.title).all()

        return render_template('daily_logs/daily_log_list.html',
            active_page='daily_logs', user=current_user, divisions=_get_divisions(),
            logs=logs, projects=projects, today=date.today(),
            statuses=DAILY_LOG_STATUSES,
            filters={'project_id': project_id, 'status': status_filter,
                     'date_from': date_from, 'date_to': date_to},
        )
    finally:
        db.close()


# ── Detail ────────────────────────────────────────────────────────────────────

@daily_log_bp.route('/daily-logs/<int:log_id>')
@login_required
def daily_log_detail(log_id):
    db = get_session()
    try:
        log = db.query(DailyLog).filter_by(id=log_id).first()
        if not log:
            flash('Daily log not found.', 'error')
            return redirect(url_for('daily_logs.daily_log_list'))
        return render_template('daily_logs/daily_log_detail.html',
            active_page='daily_logs', user=current_user, divisions=_get_divisions(),
            log=log, today=date.today(),
        )
    finally:
        db.close()


# ── Create ────────────────────────────────────────────────────────────────────

@daily_log_bp.route('/daily-logs/new', methods=['GET', 'POST'])
@daily_log_bp.route('/daily-logs/new/<int:project_id>', methods=['GET', 'POST'])
@login_required
def daily_log_new(project_id=None):
    db = get_session()
    try:
        org_id = current_user.organization_id
        projects = db.query(Project).filter_by(organization_id=org_id).order_by(Project.title).all()
        project = db.query(Project).filter_by(id=project_id).first() if project_id else None
        jobs = db.query(Job).filter_by(project_id=project_id).all() if project_id else []

        if request.method == 'POST':
            pid = int(request.form['project_id'])
            log_date = _parse_date(request.form.get('log_date')) or date.today()

            existing = db.query(DailyLog).filter_by(project_id=pid, log_date=log_date).first()
            if existing:
                flash(f'A log already exists for this project on {log_date.strftime("%B %d, %Y")}.', 'warning')
                return redirect(url_for('daily_logs.daily_log_detail', log_id=existing.id))

            submit_action = request.form.get('submit_action', 'draft')
            log = DailyLog(
                log_number=DailyLog.next_number(db, pid),
                project_id=pid,
                job_id=int(request.form['job_id']) if request.form.get('job_id') else None,
                log_date=log_date,
                reported_by_id=current_user.id,
                weather=request.form.get('weather', '').strip() or None,
                temperature_high=int(request.form['temperature_high']) if request.form.get('temperature_high') else None,
                temperature_low=int(request.form['temperature_low']) if request.form.get('temperature_low') else None,
                weather_impact=request.form.get('weather_impact', 'none'),
                site_conditions=request.form.get('site_conditions', '').strip() or None,
                crew_on_site=_parse_crew(request.form),
                subcontractors_on_site=request.form.get('subcontractors_on_site', '').strip() or None,
                total_workers=int(request.form['total_workers']) if request.form.get('total_workers') else 0,
                hours_worked=float(request.form['hours_worked']) if request.form.get('hours_worked') else 0,
                work_description=request.form.get('work_description', '').strip(),
                areas_worked=request.form.get('areas_worked', '').strip() or None,
                milestones_reached=request.form.get('milestones_reached', '').strip() or None,
                materials_received=request.form.get('materials_received', '').strip() or None,
                equipment_on_site=request.form.get('equipment_on_site', '').strip() or None,
                delays=request.form.get('delays', '').strip() or None,
                safety_incidents=request.form.get('safety_incidents', '').strip() or None,
                visitor_log=request.form.get('visitor_log', '').strip() or None,
                issues_or_concerns=request.form.get('issues_or_concerns', '').strip() or None,
                status='submitted' if submit_action == 'submit' else 'draft',
                notes=request.form.get('notes', '').strip() or None,
            )
            db.add(log)
            db.commit()

            if log.is_late_entry:
                flash(f'Note: This log is {(date.today() - log.log_date).days} days late.', 'warning')
            flash(f'Daily Log {log.log_number} saved.', 'success')
            return redirect(url_for('daily_logs.daily_log_detail', log_id=log.id))

        return render_template('daily_logs/daily_log_form.html',
            active_page='daily_logs', user=current_user, divisions=_get_divisions(),
            log=None, projects=projects, project=project, jobs=jobs, today=date.today(),
            weather_impacts=WEATHER_IMPACTS,
        )
    finally:
        db.close()


# ── Edit ──────────────────────────────────────────────────────────────────────

@daily_log_bp.route('/daily-logs/<int:log_id>/edit', methods=['GET', 'POST'])
@login_required
def daily_log_edit(log_id):
    db = get_session()
    try:
        log = db.query(DailyLog).filter_by(id=log_id).first()
        if not log:
            flash('Not found.', 'error')
            return redirect(url_for('daily_logs.daily_log_list'))
        if log.status == 'reviewed':
            flash('Reviewed logs cannot be edited.', 'warning')
            return redirect(url_for('daily_logs.daily_log_detail', log_id=log_id))

        # Technicians can only edit their own logs
        if current_user.role not in ('owner', 'admin', 'dispatcher') and log.reported_by_id != current_user.id:
            flash('You can only edit your own daily logs.', 'error')
            return redirect(url_for('daily_logs.daily_log_detail', log_id=log_id))

        org_id = current_user.organization_id
        projects = db.query(Project).filter_by(organization_id=org_id).order_by(Project.title).all()
        jobs = db.query(Job).filter_by(project_id=log.project_id).all()

        if request.method == 'POST':
            submit_action = request.form.get('submit_action', 'draft')
            log.weather = request.form.get('weather', '').strip() or None
            log.temperature_high = int(request.form['temperature_high']) if request.form.get('temperature_high') else None
            log.temperature_low = int(request.form['temperature_low']) if request.form.get('temperature_low') else None
            log.weather_impact = request.form.get('weather_impact', 'none')
            log.site_conditions = request.form.get('site_conditions', '').strip() or None
            log.crew_on_site = _parse_crew(request.form)
            log.subcontractors_on_site = request.form.get('subcontractors_on_site', '').strip() or None
            log.total_workers = int(request.form['total_workers']) if request.form.get('total_workers') else 0
            log.hours_worked = float(request.form['hours_worked']) if request.form.get('hours_worked') else 0
            log.work_description = request.form.get('work_description', '').strip()
            log.areas_worked = request.form.get('areas_worked', '').strip() or None
            log.milestones_reached = request.form.get('milestones_reached', '').strip() or None
            log.materials_received = request.form.get('materials_received', '').strip() or None
            log.equipment_on_site = request.form.get('equipment_on_site', '').strip() or None
            log.delays = request.form.get('delays', '').strip() or None
            log.safety_incidents = request.form.get('safety_incidents', '').strip() or None
            log.visitor_log = request.form.get('visitor_log', '').strip() or None
            log.issues_or_concerns = request.form.get('issues_or_concerns', '').strip() or None
            log.notes = request.form.get('notes', '').strip() or None
            if submit_action == 'submit' and log.status == 'draft':
                log.status = 'submitted'
            db.commit()
            flash(f'Daily Log {log.log_number} updated.', 'success')
            return redirect(url_for('daily_logs.daily_log_detail', log_id=log_id))

        return render_template('daily_logs/daily_log_form.html',
            active_page='daily_logs', user=current_user, divisions=_get_divisions(),
            log=log, projects=projects, jobs=jobs, today=date.today(),
            weather_impacts=WEATHER_IMPACTS,
        )
    finally:
        db.close()


# ── Review ────────────────────────────────────────────────────────────────────

@daily_log_bp.route('/daily-logs/<int:log_id>/review', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def daily_log_review(log_id):
    db = get_session()
    try:
        log = db.query(DailyLog).filter_by(id=log_id).first()
        if log:
            log.status = 'reviewed'
            log.reviewed_by_id = current_user.id
            log.reviewed_at = datetime.now(timezone.utc)
            db.commit()
            flash(f'Daily Log {log.log_number} marked as reviewed.', 'success')
    finally:
        db.close()
    return redirect(url_for('daily_logs.daily_log_detail', log_id=log_id))


# ── Print ─────────────────────────────────────────────────────────────────────

@daily_log_bp.route('/daily-logs/<int:log_id>/print')
@login_required
def daily_log_print(log_id):
    db = get_session()
    try:
        log = db.query(DailyLog).filter_by(id=log_id).first()
        if not log:
            flash('Not found.', 'error')
            return redirect(url_for('daily_logs.daily_log_list'))
        return render_template('daily_logs/daily_log_print.html', log=log, today=date.today())
    finally:
        db.close()


# ── Calendar ──────────────────────────────────────────────────────────────────

@daily_log_bp.route('/daily-logs/calendar/<int:project_id>')
@login_required
def daily_log_calendar(project_id):
    db = get_session()
    try:
        project = db.query(Project).filter_by(id=project_id).first()
        if not project:
            flash('Project not found.', 'error')
            return redirect(url_for('daily_logs.daily_log_list'))
        year = request.args.get('year', date.today().year, type=int)
        month = request.args.get('month', date.today().month, type=int)
        return render_template('daily_logs/daily_log_calendar.html',
            active_page='daily_logs', user=current_user, divisions=_get_divisions(),
            project=project, year=year, month=month, today=date.today(),
        )
    finally:
        db.close()


@daily_log_bp.route('/daily-logs/api/calendar/<int:project_id>')
@login_required
def api_calendar_data(project_id):
    db = get_session()
    try:
        year = request.args.get('year', date.today().year, type=int)
        month = request.args.get('month', date.today().month, type=int)
        start = date(year, month, 1)
        end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
        logs = db.query(DailyLog).filter(
            DailyLog.project_id == project_id,
            DailyLog.log_date >= start,
            DailyLog.log_date <= end,
        ).all()
        return jsonify([{'date': l.log_date.isoformat(), 'id': l.id,
                         'number': l.log_number, 'status': l.status} for l in logs])
    finally:
        db.close()
