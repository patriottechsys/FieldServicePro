"""Communication Log CRUD routes."""
from datetime import timezone, datetime, date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_, desc

from models.database import get_session
from models.communication import (
    CommunicationLog, CommunicationTemplate,
    COMM_TYPES, COMM_DIRECTIONS, COMM_PRIORITIES, COMM_SENTIMENTS, DIRECTION_MAP,
)
from models.client import Client
from models.job import Job
from models.quote import Quote
from models.invoice import Invoice
from models.service_request import ServiceRequest
from models.user import User
from models.division import Division
from web.auth import role_required
from web.utils.communication_utils import generate_log_number, derive_direction, get_communication_stats

communications_bp = Blueprint('communications', __name__, url_prefix='/communications')


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


# ── List ──────────────────────────────────────────────────────────────────────

@communications_bp.route('/')
@login_required
def communication_list():
    db = get_session()
    try:
        org_id = current_user.organization_id
        page = request.args.get('page', 1, type=int)
        per_page = 25

        query = db.query(CommunicationLog).join(Client).filter(Client.organization_id == org_id)

        # Filters
        f_type = request.args.get('type', '')
        f_client = request.args.get('client_id', '')
        f_follow_up = request.args.get('follow_up', '')
        f_priority = request.args.get('priority', '')
        f_search = request.args.get('q', '').strip()
        f_date_from = request.args.get('date_from', '')
        f_date_to = request.args.get('date_to', '')

        if f_type:
            query = query.filter(CommunicationLog.communication_type == f_type)
        if f_client:
            query = query.filter(CommunicationLog.client_id == int(f_client))
        if f_follow_up == 'overdue':
            query = query.filter(
                CommunicationLog.follow_up_required == True,
                CommunicationLog.follow_up_completed == False,
                CommunicationLog.follow_up_date < date.today()
            )
        elif f_follow_up == 'pending':
            query = query.filter(
                CommunicationLog.follow_up_required == True,
                CommunicationLog.follow_up_completed == False,
            )
        if f_priority:
            query = query.filter(CommunicationLog.priority == f_priority)
        if f_date_from:
            try:
                query = query.filter(CommunicationLog.communication_date >= datetime.strptime(f_date_from, '%Y-%m-%d'))
            except ValueError:
                pass
        if f_date_to:
            try:
                query = query.filter(CommunicationLog.communication_date <= datetime.strptime(f_date_to + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
            except ValueError:
                pass
        if f_search:
            s = f'%{f_search}%'
            query = query.filter(or_(
                CommunicationLog.subject.ilike(s),
                CommunicationLog.description.ilike(s),
                CommunicationLog.contact_name.ilike(s),
                CommunicationLog.log_number.ilike(s),
            ))

        total = query.count()
        logs = query.order_by(desc(CommunicationLog.communication_date)).offset((page - 1) * per_page).limit(per_page).all()
        total_pages = (total + per_page - 1) // per_page
        stats = get_communication_stats(db)
        clients = db.query(Client).filter_by(organization_id=org_id).order_by(Client.company_name).all()

        return render_template('communications/comm_list.html',
            active_page='communications', user=current_user, divisions=_get_divisions(),
            can_admin=current_user.role in ('owner', 'admin'),
            logs=logs, stats=stats, clients=clients,
            comm_types=COMM_TYPES, comm_priorities=COMM_PRIORITIES,
            page=page, total_pages=total_pages, total=total, per_page=per_page,
            filters={'type': f_type, 'client_id': f_client, 'follow_up': f_follow_up,
                     'priority': f_priority, 'q': f_search, 'date_from': f_date_from, 'date_to': f_date_to},
        )
    finally:
        db.close()


# ── Detail ────────────────────────────────────────────────────────────────────

@communications_bp.route('/<int:log_id>')
@login_required
def communication_detail(log_id):
    db = get_session()
    try:
        log = db.query(CommunicationLog).filter_by(id=log_id).first()
        if not log:
            flash('Communication not found.', 'error')
            return redirect(url_for('communications.communication_list'))

        # Thread: same client+job communications
        thread = []
        if log.job_id:
            thread = db.query(CommunicationLog).filter(
                CommunicationLog.client_id == log.client_id,
                CommunicationLog.job_id == log.job_id,
                CommunicationLog.id != log.id,
            ).order_by(CommunicationLog.communication_date).all()

        return render_template('communications/comm_detail.html',
            active_page='communications', user=current_user, divisions=_get_divisions(),
            can_admin=current_user.role in ('owner', 'admin'),
            log=log, thread=thread,
        )
    finally:
        db.close()


# ── Create ────────────────────────────────────────────────────────────────────

@communications_bp.route('/new', methods=['GET', 'POST'])
@login_required
def communication_new():
    db = get_session()
    try:
        org_id = current_user.organization_id

        if request.method == 'POST':
            return _handle_save(db, None)

        clients = db.query(Client).filter_by(organization_id=org_id).order_by(Client.company_name).all()
        templates = db.query(CommunicationTemplate).filter_by(is_active=True).order_by(CommunicationTemplate.name).all()

        prefill = {k: request.args.get(k) for k in
                   ('client_id', 'job_id', 'project_id', 'quote_id', 'invoice_id', 'warranty_id', 'service_request_id', 'type')}

        return render_template('communications/comm_form.html',
            active_page='communications', user=current_user, divisions=_get_divisions(),
            log=None, clients=clients, templates=templates, prefill=prefill,
            comm_types=COMM_TYPES, comm_priorities=COMM_PRIORITIES, comm_sentiments=COMM_SENTIMENTS,
        )
    finally:
        db.close()


# ── Edit ──────────────────────────────────────────────────────────────────────

@communications_bp.route('/<int:log_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('owner', 'admin', 'dispatcher')
def communication_edit(log_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        log = db.query(CommunicationLog).filter_by(id=log_id).first()
        if not log:
            flash('Not found.', 'error')
            return redirect(url_for('communications.communication_list'))

        if request.method == 'POST':
            return _handle_save(db, log)

        clients = db.query(Client).filter_by(organization_id=org_id).order_by(Client.company_name).all()
        templates = db.query(CommunicationTemplate).filter_by(is_active=True).order_by(CommunicationTemplate.name).all()

        return render_template('communications/comm_form.html',
            active_page='communications', user=current_user, divisions=_get_divisions(),
            log=log, clients=clients, templates=templates, prefill={},
            comm_types=COMM_TYPES, comm_priorities=COMM_PRIORITIES, comm_sentiments=COMM_SENTIMENTS,
        )
    finally:
        db.close()


# ── Delete ────────────────────────────────────────────────────────────────────

@communications_bp.route('/<int:log_id>/delete', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def communication_delete(log_id):
    db = get_session()
    try:
        log = db.query(CommunicationLog).filter_by(id=log_id).first()
        if log:
            db.delete(log)
            db.commit()
            flash('Communication deleted.', 'warning')
    finally:
        db.close()
    return redirect(url_for('communications.communication_list'))


# ── Complete Follow-Up ────────────────────────────────────────────────────────

@communications_bp.route('/<int:log_id>/complete-followup', methods=['POST'])
@login_required
def complete_follow_up(log_id):
    db = get_session()
    try:
        log = db.query(CommunicationLog).filter_by(id=log_id).first()
        if log:
            log.follow_up_completed = True
            log.follow_up_completed_date = date.today()
            log.follow_up_completed_by_id = current_user.id
            db.commit()
            flash('Follow-up completed.', 'success')
    finally:
        db.close()
    return redirect(request.referrer or url_for('communications.follow_up_queue'))


# ── Follow-Up Queue ──────────────────────────────────────────────────────────

@communications_bp.route('/follow-ups')
@login_required
def follow_up_queue():
    db = get_session()
    try:
        pending = db.query(CommunicationLog).join(Client).filter(
            Client.organization_id == current_user.organization_id,
            CommunicationLog.follow_up_required == True,
            CommunicationLog.follow_up_completed == False,
        ).order_by(CommunicationLog.follow_up_date).all()

        today_d = date.today()
        overdue = [l for l in pending if l.follow_up_date and l.follow_up_date < today_d]
        due_today = [l for l in pending if l.follow_up_date and l.follow_up_date == today_d]
        upcoming = [l for l in pending if not l.follow_up_date or l.follow_up_date > today_d]

        return render_template('communications/follow_up_queue.html',
            active_page='communications', user=current_user, divisions=_get_divisions(),
            overdue=overdue, due_today=due_today, upcoming=upcoming,
            stats={'overdue': len(overdue), 'due_today': len(due_today), 'total_pending': len(pending)},
        )
    finally:
        db.close()


# ── Quick Log (AJAX) ─────────────────────────────────────────────────────────

@communications_bp.route('/quick-log', methods=['POST'])
@login_required
def quick_log():
    db = get_session()
    try:
        log = _build_from_form(db, None)
        db.add(log)
        db.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'log_number': log.log_number})
        flash(f'Communication {log.log_number} logged.', 'success')
        return redirect(request.referrer or url_for('communications.communication_list'))
    except Exception as e:
        db.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': str(e)}), 400
        flash(f'Error: {e}', 'error')
        return redirect(request.referrer or url_for('communications.communication_list'))
    finally:
        db.close()


# ── API: Client entities ──────────────────────────────────────────────────────

@communications_bp.route('/api/client/<int:client_id>/entities')
@login_required
def api_client_entities(client_id):
    db = get_session()
    try:
        jobs = db.query(Job).filter_by(client_id=client_id).order_by(desc(Job.created_at)).limit(10).all()
        quotes = db.query(Quote).filter_by(client_id=client_id).order_by(desc(Quote.created_at)).limit(10).all()
        invoices = db.query(Invoice).filter_by(client_id=client_id).order_by(desc(Invoice.created_at)).limit(10).all()
        requests = db.query(ServiceRequest).filter_by(client_id=client_id).order_by(desc(ServiceRequest.created_at)).limit(10).all()
        return jsonify({
            'jobs': [{'id': j.id, 'number': j.job_number, 'title': j.title} for j in jobs],
            'quotes': [{'id': q.id, 'number': q.quote_number} for q in quotes],
            'invoices': [{'id': i.id, 'number': i.invoice_number} for i in invoices],
            'requests': [{'id': r.id, 'number': r.request_number, 'title': r.description[:50] if r.description else ''} for r in requests],
        })
    finally:
        db.close()


# ── API: Template detail ─────────────────────────────────────────────────────

@communications_bp.route('/api/template/<int:template_id>')
@login_required
def api_template_detail(template_id):
    db = get_session()
    try:
        t = db.query(CommunicationTemplate).filter_by(id=template_id).first()
        if not t:
            return jsonify({}), 404
        fu_date = (date.today() + timedelta(days=t.follow_up_days)).isoformat() if t.follow_up_required and t.follow_up_days else None
        return jsonify({
            'communication_type': t.communication_type,
            'subject': t.subject_template,
            'description': t.description_template or '',
            'follow_up_required': t.follow_up_required,
            'follow_up_date': fu_date,
            'priority': t.default_priority,
        })
    finally:
        db.close()


# ── Private helpers ───────────────────────────────────────────────────────────

def _handle_save(db, log):
    try:
        is_new = log is None
        if is_new:
            log = CommunicationLog(log_number=generate_log_number(db))
            db.add(log)
        _build_from_form(db, log)
        db.commit()
        flash(f'Communication {log.log_number} saved.', 'success')
        return redirect(url_for('communications.communication_detail', log_id=log.id))
    except Exception as e:
        db.rollback()
        flash(f'Error: {e}', 'error')
        return redirect(request.referrer or url_for('communications.communication_list'))


def _build_from_form(db, log):
    is_new = log is None
    if is_new:
        log = CommunicationLog(log_number=generate_log_number(db))

    f = request.form
    log.communication_type = f.get('communication_type', 'other')
    log.direction = derive_direction(log.communication_type) or f.get('direction') or None
    log.subject = f.get('subject', '').strip()
    log.description = f.get('description', '').strip() or None
    log.outcome = f.get('outcome', '').strip() or None

    log.follow_up_required = 'follow_up_required' in f
    fu = f.get('follow_up_date')
    log.follow_up_date = datetime.strptime(fu, '%Y-%m-%d').date() if fu else None
    log.follow_up_notes = f.get('follow_up_notes', '').strip() or None

    log.client_id = int(f.get('client_id'))
    log.contact_name = f.get('contact_name', '').strip() or None
    log.contact_phone = f.get('contact_phone', '').strip() or None
    log.contact_email = f.get('contact_email', '').strip() or None

    def _fk(field):
        v = f.get(field)
        return int(v) if v and v.isdigit() else None

    log.job_id = _fk('job_id')
    log.project_id = _fk('project_id')
    log.quote_id = _fk('quote_id')
    log.invoice_id = _fk('invoice_id')
    log.warranty_id = _fk('warranty_id')
    log.service_request_id = _fk('service_request_id')

    dur = f.get('duration_minutes')
    log.duration_minutes = int(dur) if dur and dur.isdigit() else None
    log.priority = f.get('priority', 'normal')
    log.sentiment = f.get('sentiment') or None
    log.is_escalation = 'is_escalation' in f
    log.escalated_to_id = _fk('escalated_to_id')

    tags_raw = f.get('tags', '').strip()
    log.tags = [t.strip() for t in tags_raw.split(',') if t.strip()] if tags_raw else None

    log.logged_by_id = current_user.id

    comm_date = f.get('communication_date')
    if comm_date:
        try:
            log.communication_date = datetime.strptime(comm_date, '%Y-%m-%dT%H:%M')
        except ValueError:
            try:
                log.communication_date = datetime.strptime(comm_date, '%Y-%m-%d')
            except ValueError:
                log.communication_date = datetime.now(timezone.utc)
    elif is_new:
        log.communication_date = datetime.now(timezone.utc)

    return log
