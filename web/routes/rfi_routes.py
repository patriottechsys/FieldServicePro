"""RFI (Request for Information) routes — list, detail, create, edit, respond."""
from datetime import timezone, date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from models.database import get_session
from models.rfi import RFI, RFI_STATUSES, RFI_PRIORITIES, RFI_IMPACT_TYPES, STATUS_COLORS, PRIORITY_COLORS
from models.project import Project
from models.job import Job
from models.job_phase import JobPhase
from models.user import User
from models.division import Division
from web.auth import role_required

rfi_bp = Blueprint('rfis', __name__)


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


# ── List ──────────────────────────────────────────────────────────────────────

@rfi_bp.route('/rfis')
@login_required
def rfi_list():
    db = get_session()
    try:
        org_id = current_user.organization_id
        project_id = request.args.get('project_id', type=int)
        status_filter = request.args.get('status', '')
        priority_filter = request.args.get('priority', '')
        overdue_only = request.args.get('overdue', '') == '1'

        q = db.query(RFI).join(Project).filter(Project.organization_id == org_id)
        if project_id:
            q = q.filter(RFI.project_id == project_id)
        if status_filter:
            q = q.filter(RFI.status == status_filter)
        if priority_filter:
            q = q.filter(RFI.priority == priority_filter)
        if overdue_only:
            q = q.filter(
                RFI.status.notin_(['answered', 'closed', 'void']),
                RFI.date_required != None,
                RFI.date_required < date.today(),
            )

        rfis = q.order_by(RFI.date_submitted.desc()).all()

        from web.utils.rfi_utils import get_rfi_stats
        stats = get_rfi_stats(db, project_id=project_id)

        projects = db.query(Project).filter_by(organization_id=org_id).order_by(Project.title).all()
        users = db.query(User).filter_by(organization_id=org_id, is_active=True).order_by(User.first_name).all()

        return render_template('rfis/rfi_list.html',
            active_page='rfis', user=current_user, divisions=_get_divisions(),
            rfis=rfis, stats=stats, projects=projects, users=users,
            statuses=RFI_STATUSES, priorities=RFI_PRIORITIES,
            status_colors=STATUS_COLORS, priority_colors=PRIORITY_COLORS,
            today=date.today(),
            filters={'project_id': project_id, 'status': status_filter,
                     'priority': priority_filter, 'overdue': overdue_only},
        )
    finally:
        db.close()


# ── Detail ────────────────────────────────────────────────────────────────────

@rfi_bp.route('/rfis/<int:rfi_id>')
@login_required
def rfi_detail(rfi_id):
    db = get_session()
    try:
        rfi = db.query(RFI).filter_by(id=rfi_id).first()
        if not rfi:
            flash('RFI not found.', 'error')
            return redirect(url_for('rfis.rfi_list'))

        users = db.query(User).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(User.first_name).all()

        return render_template('rfis/rfi_detail.html',
            active_page='rfis', user=current_user, divisions=_get_divisions(),
            rfi=rfi, users=users,
            status_colors=STATUS_COLORS, priority_colors=PRIORITY_COLORS,
            today=date.today(),
        )
    finally:
        db.close()


# ── Create ────────────────────────────────────────────────────────────────────

@rfi_bp.route('/rfis/new', methods=['GET', 'POST'])
@rfi_bp.route('/rfis/new/<int:project_id>', methods=['GET', 'POST'])
@login_required
def rfi_new(project_id=None):
    db = get_session()
    try:
        org_id = current_user.organization_id
        projects = db.query(Project).filter_by(organization_id=org_id).order_by(Project.title).all()
        users = db.query(User).filter_by(organization_id=org_id, is_active=True).order_by(User.first_name).all()

        if request.method == 'POST':
            pid = int(request.form['project_id'])
            rfi = RFI(
                rfi_number=RFI.next_number(db, pid),
                project_id=pid,
                job_id=int(request.form['job_id']) if request.form.get('job_id') else None,
                phase_id=int(request.form['phase_id']) if request.form.get('phase_id') else None,
                subject=request.form['subject'].strip(),
                question=request.form['question'].strip(),
                context=request.form.get('context', '').strip() or None,
                reference=request.form.get('reference', '').strip() or None,
                submitted_by_id=current_user.id,
                assigned_to_id=int(request.form['assigned_to_id']) if request.form.get('assigned_to_id') else None,
                directed_to=request.form.get('directed_to', '').strip() or None,
                directed_to_email=request.form.get('directed_to_email', '').strip() or None,
                priority=request.form.get('priority', 'normal'),
                status=request.form.get('status', 'open'),
                date_submitted=date.today(),
                date_required=_parse_date(request.form.get('date_required')),
                cost_impact=request.form.get('cost_impact', 'none'),
                cost_impact_amount=float(request.form['cost_impact_amount']) if request.form.get('cost_impact_amount') else None,
                schedule_impact=request.form.get('schedule_impact', 'none'),
                schedule_impact_days=int(request.form['schedule_impact_days']) if request.form.get('schedule_impact_days') else None,
                notes=request.form.get('notes', '').strip() or None,
            )
            db.add(rfi)
            db.commit()

            try:
                from web.utils.notification_service import NotificationService
                if rfi.assigned_to_id:
                    NotificationService.notify('system', rfi, triggered_by=current_user,
                                               title=f'New RFI Assigned: {rfi.rfi_number}',
                                               message=f'RFI "{rfi.subject}" assigned to you.')
            except Exception:
                pass

            flash(f'RFI {rfi.rfi_number} created.', 'success')
            return redirect(url_for('rfis.rfi_detail', rfi_id=rfi.id))

        jobs = db.query(Job).filter_by(project_id=project_id).all() if project_id else []
        project = db.query(Project).filter_by(id=project_id).first() if project_id else None

        return render_template('rfis/rfi_form.html',
            active_page='rfis', user=current_user, divisions=_get_divisions(),
            rfi=None, projects=projects, users=users, jobs=jobs, project=project,
            statuses=RFI_STATUSES, priorities=RFI_PRIORITIES, impacts=RFI_IMPACT_TYPES,
        )
    finally:
        db.close()


# ── Edit ──────────────────────────────────────────────────────────────────────

@rfi_bp.route('/rfis/<int:rfi_id>/edit', methods=['GET', 'POST'])
@login_required
def rfi_edit(rfi_id):
    db = get_session()
    try:
        rfi = db.query(RFI).filter_by(id=rfi_id).first()
        if not rfi:
            flash('RFI not found.', 'error')
            return redirect(url_for('rfis.rfi_list'))

        if rfi.status in ('closed', 'void'):
            flash('Cannot edit a closed or voided RFI.', 'warning')
            return redirect(url_for('rfis.rfi_detail', rfi_id=rfi_id))

        org_id = current_user.organization_id
        projects = db.query(Project).filter_by(organization_id=org_id).order_by(Project.title).all()
        users = db.query(User).filter_by(organization_id=org_id, is_active=True).order_by(User.first_name).all()
        jobs = db.query(Job).filter_by(project_id=rfi.project_id).all()

        if request.method == 'POST':
            rfi.subject = request.form['subject'].strip()
            rfi.question = request.form['question'].strip()
            rfi.context = request.form.get('context', '').strip() or None
            rfi.reference = request.form.get('reference', '').strip() or None
            rfi.job_id = int(request.form['job_id']) if request.form.get('job_id') else None
            rfi.phase_id = int(request.form['phase_id']) if request.form.get('phase_id') else None
            rfi.assigned_to_id = int(request.form['assigned_to_id']) if request.form.get('assigned_to_id') else None
            rfi.directed_to = request.form.get('directed_to', '').strip() or None
            rfi.directed_to_email = request.form.get('directed_to_email', '').strip() or None
            rfi.priority = request.form.get('priority', 'normal')
            rfi.date_required = _parse_date(request.form.get('date_required'))
            rfi.cost_impact = request.form.get('cost_impact', 'none')
            rfi.cost_impact_amount = float(request.form['cost_impact_amount']) if request.form.get('cost_impact_amount') else None
            rfi.schedule_impact = request.form.get('schedule_impact', 'none')
            rfi.schedule_impact_days = int(request.form['schedule_impact_days']) if request.form.get('schedule_impact_days') else None
            rfi.notes = request.form.get('notes', '').strip() or None
            db.commit()
            flash(f'RFI {rfi.rfi_number} updated.', 'success')
            return redirect(url_for('rfis.rfi_detail', rfi_id=rfi_id))

        return render_template('rfis/rfi_form.html',
            active_page='rfis', user=current_user, divisions=_get_divisions(),
            rfi=rfi, projects=projects, users=users, jobs=jobs, project=rfi.project,
            statuses=RFI_STATUSES, priorities=RFI_PRIORITIES, impacts=RFI_IMPACT_TYPES,
        )
    finally:
        db.close()


# ── Respond ───────────────────────────────────────────────────────────────────

@rfi_bp.route('/rfis/<int:rfi_id>/respond', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def rfi_respond(rfi_id):
    db = get_session()
    try:
        rfi = db.query(RFI).filter_by(id=rfi_id).first()
        if not rfi:
            flash('RFI not found.', 'error')
            return redirect(url_for('rfis.rfi_list'))

        if request.method == 'POST':
            rfi.response = request.form['response'].strip()
            rfi.responded_by_id = current_user.id
            rfi.responded_by_external = request.form.get('responded_by_external', '').strip() or None
            rfi.response_date = datetime.now(timezone.utc)
            rfi.status = 'answered'
            db.commit()

            try:
                from web.utils.notification_service import NotificationService
                NotificationService.notify('system', rfi, triggered_by=current_user,
                                           title=f'RFI Answered: {rfi.rfi_number}',
                                           message=f'RFI "{rfi.subject}" has been answered.',
                                           override_recipients=[rfi.submitted_by] if rfi.submitted_by else None)
            except Exception:
                pass

            flash(f'Response recorded for {rfi.rfi_number}.', 'success')
            return redirect(url_for('rfis.rfi_detail', rfi_id=rfi_id))

        return render_template('rfis/rfi_respond.html',
            active_page='rfis', user=current_user, divisions=_get_divisions(), rfi=rfi,
        )
    finally:
        db.close()


# ── Status Actions ────────────────────────────────────────────────────────────

@rfi_bp.route('/rfis/<int:rfi_id>/close', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def rfi_close(rfi_id):
    db = get_session()
    try:
        rfi = db.query(RFI).filter_by(id=rfi_id).first()
        if rfi:
            rfi.status = 'closed'
            db.commit()
            flash(f'{rfi.rfi_number} closed.', 'success')
    finally:
        db.close()
    return redirect(url_for('rfis.rfi_detail', rfi_id=rfi_id))


@rfi_bp.route('/rfis/<int:rfi_id>/void', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def rfi_void(rfi_id):
    db = get_session()
    try:
        rfi = db.query(RFI).filter_by(id=rfi_id).first()
        if rfi:
            rfi.status = 'void'
            db.commit()
            flash(f'{rfi.rfi_number} voided.', 'warning')
    finally:
        db.close()
    return redirect(url_for('rfis.rfi_detail', rfi_id=rfi_id))


# ── AJAX: jobs/phases for project ─────────────────────────────────────────────

@rfi_bp.route('/rfis/api/project/<int:project_id>/jobs')
@login_required
def api_project_jobs(project_id):
    db = get_session()
    try:
        jobs = db.query(Job).filter_by(project_id=project_id).order_by(Job.title).all()
        return jsonify([{'id': j.id, 'title': j.title, 'job_number': j.job_number} for j in jobs])
    finally:
        db.close()


@rfi_bp.route('/rfis/api/job/<int:job_id>/phases')
@login_required
def api_job_phases(job_id):
    db = get_session()
    try:
        phases = db.query(JobPhase).filter_by(job_id=job_id).order_by(JobPhase.phase_order).all()
        return jsonify([{'id': p.id, 'name': p.name} for p in phases])
    finally:
        db.close()
