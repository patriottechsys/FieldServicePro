"""Routes for service request intake and management."""
from datetime import timezone, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
from sqlalchemy import desc, or_
from models.database import get_session
from models.service_request import ServiceRequest
from models.client import Client, Property
from models.job import Job
from models.division import Division
from models.user import User
from web.auth import role_required

requests_bp = Blueprint('requests', __name__)


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


def _tpl_vars(**extra):
    base = dict(active_page='requests', user=current_user, divisions=_get_divisions())
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@requests_bp.route('/requests')
@login_required
def request_list():
    db = get_session()
    try:
        org_id = current_user.organization_id
        query = db.query(ServiceRequest).filter_by(organization_id=org_id)

        # Filters
        status = request.args.get('status', '')
        priority = request.args.get('priority', '')
        req_type = request.args.get('type', '')
        search = request.args.get('search', '').strip()

        if status:
            query = query.filter(ServiceRequest.status == status)
        if priority:
            query = query.filter(ServiceRequest.priority == priority)
        if req_type:
            query = query.filter(ServiceRequest.request_type == req_type)
        if search:
            s = f'%{search}%'
            query = query.filter(or_(
                ServiceRequest.contact_name.ilike(s),
                ServiceRequest.description.ilike(s),
                ServiceRequest.request_number.ilike(s),
            ))

        requests_list = query.order_by(desc(ServiceRequest.created_at)).all()

        # Stats
        new_count = db.query(ServiceRequest).filter_by(
            organization_id=org_id, status='new').count()
        today = datetime.now(timezone.utc).date()
        today_count = db.query(ServiceRequest).filter(
            ServiceRequest.organization_id == org_id,
            ServiceRequest.created_at >= datetime.combine(today, datetime.min.time())
        ).count()
        reviewed_count = db.query(ServiceRequest).filter_by(
            organization_id=org_id, status='reviewed').count()

        return render_template('requests/request_list.html',
                               **_tpl_vars(
                                   requests=requests_list,
                                   new_count=new_count,
                                   today_count=today_count,
                                   reviewed_count=reviewed_count,
                                   filter_status=status,
                                   filter_priority=priority,
                                   filter_type=req_type,
                                   search=search,
                                   status_choices=ServiceRequest.STATUS_CHOICES,
                                   priority_choices=ServiceRequest.PRIORITY_CHOICES,
                                   type_choices=ServiceRequest.TYPE_CHOICES,
                               ))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@requests_bp.route('/requests/new', methods=['GET', 'POST'])
@login_required
def request_new():
    db = get_session()
    try:
        org_id = current_user.organization_id

        if request.method == 'POST':
            f = request.form
            sr = ServiceRequest(
                organization_id=org_id,
                request_number=ServiceRequest.generate_number(db, org_id),
                contact_name=f.get('contact_name', '').strip(),
                contact_phone=f.get('contact_phone', '').strip() or None,
                contact_email=f.get('contact_email', '').strip() or None,
                source=f.get('source', 'phone'),
                request_type=f.get('request_type', '').strip() or None,
                priority=f.get('priority', 'medium'),
                description=f.get('description', '').strip(),
                preferred_time=f.get('preferred_time', '').strip() or None,
                notes=f.get('notes', '').strip() or None,
                status='new',
                created_by=current_user.id,
            )

            client_id = f.get('client_id', '').strip()
            if client_id:
                sr.client_id = int(client_id)
            property_id = f.get('property_id', '').strip()
            if property_id:
                sr.property_id = int(property_id)
            assigned_to = f.get('assigned_to', '').strip()
            if assigned_to:
                sr.assigned_to = int(assigned_to)

            pref_date = f.get('preferred_date', '').strip()
            if pref_date:
                try:
                    sr.preferred_date = datetime.strptime(pref_date, '%Y-%m-%d').date()
                except ValueError:
                    pass

            if not sr.contact_name or not sr.description:
                flash('Contact name and description are required.', 'danger')
                users = db.query(User).filter_by(
                    organization_id=org_id, is_active=True
                ).order_by(User.first_name).all()
                return render_template('requests/request_form.html',
                                       **_tpl_vars(sr=None, mode='create', users=users))

            db.add(sr)
            db.commit()

            try:
                from web.utils.notification_service import NotificationService
                NotificationService.notify('request_new', sr, triggered_by=current_user)
            except Exception:
                pass

            flash(f'Request {sr.request_number} created.', 'success')
            return redirect(url_for('requests.request_detail', request_id=sr.id))

        users = db.query(User).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(User.first_name).all()

        return render_template('requests/request_form.html',
                               **_tpl_vars(sr=None, mode='create', users=users))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Detail / Edit
# ---------------------------------------------------------------------------

@requests_bp.route('/requests/<int:request_id>', methods=['GET', 'POST'])
@login_required
def request_detail(request_id):
    db = get_session()
    try:
        sr = db.query(ServiceRequest).filter_by(
            id=request_id, organization_id=current_user.organization_id
        ).first()
        if not sr:
            abort(404)

        if request.method == 'POST':
            f = request.form
            sr.contact_name = f.get('contact_name', sr.contact_name).strip()
            sr.contact_phone = f.get('contact_phone', '').strip() or None
            sr.contact_email = f.get('contact_email', '').strip() or None
            sr.source = f.get('source', sr.source)
            sr.request_type = f.get('request_type', '').strip() or None
            sr.priority = f.get('priority', sr.priority)
            sr.description = f.get('description', sr.description).strip()
            sr.preferred_time = f.get('preferred_time', '').strip() or None
            sr.notes = f.get('notes', '').strip() or None

            client_id = f.get('client_id', '').strip()
            sr.client_id = int(client_id) if client_id else None
            property_id = f.get('property_id', '').strip()
            sr.property_id = int(property_id) if property_id else None
            assigned_to = f.get('assigned_to', '').strip()
            sr.assigned_to = int(assigned_to) if assigned_to else None

            pref_date = f.get('preferred_date', '').strip()
            if pref_date:
                try:
                    sr.preferred_date = datetime.strptime(pref_date, '%Y-%m-%d').date()
                except ValueError:
                    pass
            else:
                sr.preferred_date = None

            db.commit()
            flash('Request updated.', 'success')
            return redirect(url_for('requests.request_detail', request_id=sr.id))

        users = db.query(User).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(User.first_name).all()

        return render_template('requests/request_detail.html',
                               **_tpl_vars(sr=sr, users=users))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Status Changes
# ---------------------------------------------------------------------------

@requests_bp.route('/requests/<int:request_id>/review', methods=['POST'])
@login_required
def request_mark_reviewed(request_id):
    db = get_session()
    try:
        sr = db.query(ServiceRequest).filter_by(
            id=request_id, organization_id=current_user.organization_id
        ).first()
        if not sr:
            abort(404)
        sr.status = 'reviewed'
        sr.assigned_to = sr.assigned_to or current_user.id
        db.commit()
        flash(f'Request {sr.request_number} marked as reviewed.', 'success')
    finally:
        db.close()
    return redirect(url_for('requests.request_detail', request_id=request_id))


@requests_bp.route('/requests/<int:request_id>/decline', methods=['POST'])
@login_required
def request_decline(request_id):
    db = get_session()
    try:
        sr = db.query(ServiceRequest).filter_by(
            id=request_id, organization_id=current_user.organization_id
        ).first()
        if not sr:
            abort(404)
        sr.status = 'declined'
        db.commit()
        flash(f'Request {sr.request_number} declined.', 'info')
    finally:
        db.close()
    return redirect(url_for('requests.request_detail', request_id=request_id))


@requests_bp.route('/requests/<int:request_id>/convert', methods=['POST'])
@login_required
def request_convert_to_job(request_id):
    """Convert a service request into a new job."""
    db = get_session()
    try:
        sr = db.query(ServiceRequest).filter_by(
            id=request_id, organization_id=current_user.organization_id
        ).first()
        if not sr:
            abort(404)

        if sr.status == 'converted':
            flash('This request has already been converted.', 'warning')
            return redirect(url_for('requests.request_detail', request_id=request_id))

        org_id = current_user.organization_id

        # Get a default division
        default_div = db.query(Division).filter_by(
            organization_id=org_id, is_active=True
        ).first()

        # Auto-generate job number
        from models.job import Job
        last_job = db.query(Job).filter_by(organization_id=org_id).order_by(
            Job.id.desc()).first()
        job_seq = (last_job.id + 1) if last_job else 1
        job_number = f"JOB-{datetime.now(timezone.utc).year}-{job_seq:04d}"

        job = Job(
            organization_id=org_id,
            division_id=default_div.id if default_div else 1,
            client_id=sr.client_id or 0,
            property_id=sr.property_id,
            job_number=job_number,
            title=f"{sr.type_display}: {sr.contact_name}",
            description=sr.description,
            status='draft',
            priority=sr.priority,
            job_type=sr.request_type,
            scheduled_date=datetime.combine(sr.preferred_date, datetime.min.time()) if sr.preferred_date else None,
            source='service_request',
            portal_contact_name=sr.contact_name,
            portal_contact_phone=sr.contact_phone,
            created_by_id=current_user.id,
        )
        db.add(job)
        db.flush()

        sr.status = 'converted'
        sr.converted_job_id = job.id
        db.commit()

        try:
            from web.utils.notification_service import NotificationService
            NotificationService.notify('job_created', job, triggered_by=current_user,
                                       extra_context={'job_number': job.job_number})
        except Exception:
            pass

        flash(f'Request converted to Job {job.job_number}.', 'success')
        return redirect(url_for('jobs_bp.job_detail', job_id=job.id))
    finally:
        db.close()
