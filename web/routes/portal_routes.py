"""Main portal routes: dashboard, profile, ping, and stub endpoints for navigation."""
from datetime import timezone, datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, g, jsonify, abort
from sqlalchemy import func, desc, or_

from models.database import get_session
from models.portal_user import PortalUser
from models.portal_message import PortalMessage
from models.portal_settings import PortalSettings
from models.job import Job
from models.quote import Quote
from models.invoice import Invoice
from models.contract import Contract, ContractStatus
from models.client import Property
from models.document import Document
from models.change_order import ChangeOrder

from web.portal_auth import (
    portal_login_required, portal_permission_required,
    get_accessible_property_ids, validate_password,
)
from web.utils.file_utils import save_uploaded_file

portal_bp = Blueprint('portal', __name__, url_prefix='/portal')


# ── Session Keep-alive ─────────────────────────────────────────────────────

@portal_bp.route('/ping', methods=['POST'])
@portal_login_required
def portal_ping():
    """Keep session alive."""
    return jsonify({'status': 'ok'})


# ── Profile ────────────────────────────────────────────────────────────────

@portal_bp.route('/profile', methods=['GET', 'POST'])
@portal_login_required
def portal_profile():
    user = g.portal_user
    db = get_session()
    try:
        # Re-attach user to this session
        user = db.query(PortalUser).filter_by(id=user.id).first()
        if request.method == 'POST':
            user.first_name = request.form.get('first_name', user.first_name).strip()
            user.last_name = request.form.get('last_name', user.last_name).strip()
            user.phone = request.form.get('phone', '').strip() or None

            new_password = request.form.get('new_password', '').strip()
            if new_password:
                current_password = request.form.get('current_password', '')
                if not user.check_password(current_password):
                    flash('Current password is incorrect.', 'danger')
                    return render_template('portal/profile.html', user=user, active_page='profile')
                is_valid, error = validate_password(new_password)
                if not is_valid:
                    flash(error, 'danger')
                    return render_template('portal/profile.html', user=user, active_page='profile')
                confirm = request.form.get('confirm_password', '')
                if new_password != confirm:
                    flash('New passwords do not match.', 'danger')
                    return render_template('portal/profile.html', user=user, active_page='profile')
                user.set_password(new_password)
                flash('Password updated successfully.', 'success')

            db.commit()
            flash('Profile updated.', 'success')
            return redirect(url_for('portal.portal_profile'))

        return render_template('portal/profile.html', user=user, active_page='profile')
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════

@portal_bp.route('/dashboard')
@portal_login_required
def portal_dashboard():
    user = g.portal_user
    client_id = user.client_id
    prop_ids = get_accessible_property_ids()

    db = get_session()
    try:
        # Active Jobs
        active_q = db.query(Job).filter(
            Job.client_id == client_id,
            Job.status.in_(['scheduled', 'in_progress'])
        )
        if prop_ids is not None:
            active_q = active_q.filter(Job.property_id.in_(prop_ids))
        active_jobs_count = active_q.count()

        # Open Service Requests
        requests_q = db.query(Job).filter(
            Job.client_id == client_id,
            Job.status == 'draft',
            Job.source == 'portal_request'
        )
        if prop_ids is not None:
            requests_q = requests_q.filter(Job.property_id.in_(prop_ids))
        open_requests_count = requests_q.count()

        # Pending Quotes
        pending_quotes_count = 0
        if user.can_view_quotes():
            pending_quotes_count = db.query(Quote).filter(
                Quote.client_id == client_id,
                Quote.status == 'sent'
            ).count()

        # Outstanding Balance
        outstanding_balance = 0
        if user.can_view_invoices():
            result = db.query(func.coalesce(func.sum(Invoice.balance_due), 0)).filter(
                Invoice.client_id == client_id,
                Invoice.status.in_(['sent', 'overdue', 'partial'])
            ).scalar()
            outstanding_balance = float(result or 0)

        # Next Scheduled Service
        next_job = db.query(Job).filter(
            Job.client_id == client_id,
            Job.status == 'scheduled',
            Job.scheduled_date >= datetime.now(timezone.utc)
        ).order_by(Job.scheduled_date.asc()).first()

        # Recent Activity
        recent_activity = []

        recent_jobs = db.query(Job).filter(
            Job.client_id == client_id
        ).order_by(desc(Job.updated_at)).limit(10).all()

        for job in recent_jobs:
            recent_activity.append({
                'type': 'job',
                'icon': 'clipboard-check',
                'icon_bg': '#dbeafe',
                'icon_color': '#2563eb',
                'text': f'Job #{job.job_number or job.id} -- {(job.status or "").replace("_", " ").title()}',
                'description': (job.title or '')[:80],
                'time': job.updated_at,
                'link': url_for('portal.portal_job_detail', job_id=job.id),
            })

        if user.can_view_invoices():
            recent_invoices = db.query(Invoice).filter(
                Invoice.client_id == client_id
            ).order_by(desc(Invoice.created_at)).limit(5).all()

            for inv in recent_invoices:
                recent_activity.append({
                    'type': 'invoice',
                    'icon': 'receipt',
                    'icon_bg': '#f3e8ff',
                    'icon_color': '#7c3aed',
                    'text': f'Invoice #{inv.id} -- ${float(inv.total or 0):,.2f}',
                    'description': (inv.status or '').replace('_', ' ').title(),
                    'time': inv.created_at,
                    'link': url_for('portal.portal_invoice_detail', invoice_id=inv.id),
                })

        recent_activity.sort(key=lambda x: x['time'] or datetime.min, reverse=True)
        recent_activity = recent_activity[:10]

        # Active Contracts
        active_contracts = db.query(Contract).filter(
            Contract.client_id == client_id,
            Contract.status == ContractStatus.active
        ).all()

        # Settings
        settings = PortalSettings.get_settings(db)

        return render_template('portal/dashboard.html',
            user=user,
            active_page='dashboard',
            active_jobs_count=active_jobs_count,
            open_requests_count=open_requests_count,
            pending_quotes_count=pending_quotes_count,
            outstanding_balance=outstanding_balance,
            next_job=next_job,
            recent_activity=recent_activity,
            active_contracts=active_contracts,
            settings=settings,
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  STUB ENDPOINTS (to be implemented in later tasks)
#  These prevent url_for errors in the base template navigation
# ═══════════════════════════════════════════════════════════════════════════

@portal_bp.route('/properties')
@portal_login_required
@portal_permission_required('can_view_properties')
def portal_properties():
    user = g.portal_user
    db = get_session()
    try:
        query = db.query(Property).filter_by(client_id=user.client_id, is_active=True)
        prop_ids = get_accessible_property_ids()
        if prop_ids is not None:
            query = query.filter(Property.id.in_(prop_ids))

        properties_list = query.order_by(Property.name).all()

        # Get job counts for each property
        property_stats = {}
        for prop in properties_list:
            active_count = db.query(Job).filter(
                Job.property_id == prop.id,
                Job.client_id == user.client_id,
                Job.status.in_(['scheduled', 'in_progress'])
            ).count()

            last_job = db.query(Job).filter(
                Job.property_id == prop.id,
                Job.client_id == user.client_id,
                Job.status == 'completed'
            ).order_by(desc(Job.completed_at)).first()

            property_stats[prop.id] = {
                'active_jobs': active_count,
                'last_service': last_job.completed_at if last_job else None,
            }

        view_mode = request.args.get('view', 'grid')

        return render_template('portal/properties.html',
            user=user,
            active_page='properties',
            properties=properties_list,
            property_stats=property_stats,
            view_mode=view_mode,
        )
    finally:
        db.close()


@portal_bp.route('/properties/<int:property_id>')
@portal_login_required
@portal_permission_required('can_view_properties')
def portal_property_detail(property_id):
    user = g.portal_user
    db = get_session()
    try:
        prop = db.query(Property).filter_by(id=property_id, client_id=user.client_id).first()
        if not prop:
            abort(404)

        prop_ids = get_accessible_property_ids()
        if prop_ids is not None and prop.id not in prop_ids:
            abort(403)

        # Active jobs
        active_jobs = db.query(Job).filter(
            Job.property_id == prop.id,
            Job.client_id == user.client_id,
            Job.status.in_(['scheduled', 'in_progress'])
        ).order_by(desc(Job.created_at)).all()

        # Completed jobs (recent 20)
        completed_jobs = db.query(Job).filter(
            Job.property_id == prop.id,
            Job.client_id == user.client_id,
            Job.status == 'completed'
        ).order_by(desc(Job.completed_at)).limit(20).all()

        # Upcoming scheduled
        upcoming = db.query(Job).filter(
            Job.property_id == prop.id,
            Job.client_id == user.client_id,
            Job.status == 'scheduled',
            Job.scheduled_date >= datetime.now(timezone.utc)
        ).order_by(Job.scheduled_date).limit(5).all()

        # Documents for jobs at this property
        all_job_ids = [j.id for j in active_jobs + completed_jobs]
        documents = []
        if all_job_ids:
            documents = db.query(Document).filter(
                Document.entity_type == 'job',
                Document.entity_id.in_(all_job_ids),
                Document.is_confidential == False
            ).order_by(desc(Document.created_at)).limit(20).all()

        return render_template('portal/property_detail.html',
            user=user,
            active_page='properties',
            property=prop,
            active_jobs=active_jobs,
            completed_jobs=completed_jobs,
            upcoming=upcoming,
            documents=documents,
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  SERVICE REQUESTS
# ═══════════════════════════════════════════════════════════════════════════

@portal_bp.route('/service-requests')
@portal_login_required
@portal_permission_required('can_create_service_requests')
def portal_service_requests():
    user = g.portal_user
    db = get_session()
    try:
        query = db.query(Job).filter(
            Job.client_id == user.client_id,
            Job.source == 'portal_request'
        )

        prop_ids = get_accessible_property_ids()
        if prop_ids is not None:
            query = query.filter(Job.property_id.in_(prop_ids))

        status = request.args.get('status')
        property_id = request.args.get('property')
        if status:
            query = query.filter(Job.status == status)
        if property_id:
            query = query.filter(Job.property_id == int(property_id))

        requests_list = query.order_by(desc(Job.created_at)).all()

        properties_q = db.query(Property).filter_by(client_id=user.client_id, is_active=True)
        if prop_ids is not None:
            properties_q = properties_q.filter(Property.id.in_(prop_ids))
        properties_list = properties_q.all()

        return render_template('portal/service_requests.html',
            user=user,
            active_page='service_requests',
            requests=requests_list,
            properties=properties_list,
            selected_status=status,
            selected_property=property_id,
        )
    finally:
        db.close()


@portal_bp.route('/service-requests/new', methods=['GET', 'POST'])
@portal_login_required
@portal_permission_required('can_create_service_requests')
def portal_new_service_request():
    user = g.portal_user
    db = get_session()
    try:
        settings = PortalSettings.get_settings(db)
        if not settings.allow_service_requests:
            flash('Online service requests are currently disabled. Please call us directly.', 'warning')
            return redirect(url_for('portal.portal_dashboard'))

        properties_q = db.query(Property).filter_by(client_id=user.client_id, is_active=True)
        prop_ids = get_accessible_property_ids()
        if prop_ids is not None:
            properties_q = properties_q.filter(Property.id.in_(prop_ids))
        properties_list = properties_q.all()

        if request.method == 'POST':
            f = request.form
            property_id = f.get('property_id', '').strip()
            description = f.get('description', '').strip()
            service_type = f.get('service_type', '').strip()
            priority = f.get('priority', 'normal')
            preferred_date = f.get('preferred_date', '').strip()
            preferred_time = f.get('preferred_time', 'anytime')
            contact_name = f.get('contact_name', '').strip()
            contact_phone = f.get('contact_phone', '').strip()
            access_instructions = f.get('access_instructions', '').strip()

            if not property_id or not description:
                flash('Please select a property and describe the issue.', 'danger')
                return render_template('portal/service_request_new.html',
                    user=user, active_page='service_requests',
                    properties=properties_list,
                    preselect_property=property_id)

            prop = db.query(Property).filter_by(id=int(property_id), client_id=user.client_id).first()
            if not prop:
                abort(403)
            if prop_ids is not None and prop.id not in prop_ids:
                abort(403)

            # Parse date
            sched_date = None
            if preferred_date:
                try:
                    sched_date = datetime.strptime(preferred_date, '%Y-%m-%d')
                except ValueError:
                    pass

            # Build title from service type or description
            title = service_type or description[:80]
            if preferred_time and preferred_time != 'anytime':
                description += f"\n\n[Preferred Time: {preferred_time}]"

            # Get org_id and a default division from the client
            client = user.client
            org_id = client.organization_id if client else 1

            # Use client's first property's division, or first available division
            from models.division import Division
            default_div = db.query(Division).filter_by(
                organization_id=org_id, is_active=True
            ).first()
            div_id = default_div.id if default_div else 1

            job = Job(
                organization_id=org_id,
                division_id=div_id,
                client_id=user.client_id,
                property_id=prop.id,
                title=title,
                description=description,
                status='draft',
                source='portal_request',
                priority=priority,
                job_type=service_type or None,
                scheduled_date=sched_date,
                portal_contact_name=contact_name or None,
                portal_contact_phone=contact_phone or None,
                portal_access_instructions=access_instructions or None,
            )
            db.add(job)
            db.flush()

            # Handle file uploads
            for file in request.files.getlist('photos'):
                if file and file.filename:
                    try:
                        save_uploaded_file(db, file, entity_type='job',
                                           entity_id=job.id, category='photo',
                                           uploaded_by=None)
                    except Exception:
                        pass

            # Create notification
            from models.portal_notification import PortalNotification
            notification = PortalNotification(
                notification_type='service_request',
                title=f'New service request from {client.display_name if client else "client"}',
                message=f'{user.full_name} submitted: {title[:100]}',
                link=f'/jobs/{job.id}',
                triggered_by_portal_user_id=user.id,
                target_type='internal',
                target_role='dispatcher',
                client_id=user.client_id,
                job_id=job.id,
            )
            db.add(notification)
            db.commit()

            flash(f'Service request submitted! Reference: #{job.job_number or job.id}', 'success')
            return redirect(url_for('portal.portal_service_request_detail', job_id=job.id))

        preselect_property = request.args.get('property_id')
        return render_template('portal/service_request_new.html',
            user=user,
            active_page='service_requests',
            properties=properties_list,
            preselect_property=preselect_property,
        )
    finally:
        db.close()


@portal_bp.route('/service-requests/<int:job_id>')
@portal_login_required
@portal_permission_required('can_create_service_requests')
def portal_service_request_detail(job_id):
    user = g.portal_user
    db = get_session()
    try:
        job = db.query(Job).filter_by(
            id=job_id, client_id=user.client_id, source='portal_request'
        ).first()
        if not job:
            abort(404)

        prop_ids = get_accessible_property_ids()
        if prop_ids is not None and job.property_id and job.property_id not in prop_ids:
            abort(403)

        # Get messages for this job
        messages = db.query(PortalMessage).filter_by(job_id=job.id).order_by(
            PortalMessage.created_at.asc()
        ).all()

        return render_template('portal/service_request_detail.html',
            user=user,
            active_page='service_requests',
            job=job,
            messages=messages,
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  JOBS
# ═══════════════════════════════════════════════════════════════════════════

@portal_bp.route('/jobs')
@portal_login_required
@portal_permission_required('can_view_jobs')
def portal_jobs():
    user = g.portal_user
    db = get_session()
    try:
        query = db.query(Job).filter(
            Job.client_id == user.client_id,
            Job.status != 'draft'
        )

        prop_ids = get_accessible_property_ids()
        if prop_ids is not None:
            query = query.filter(Job.property_id.in_(prop_ids))

        status = request.args.get('status')
        property_id = request.args.get('property')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')

        if status:
            query = query.filter(Job.status == status)
        if property_id:
            query = query.filter(Job.property_id == int(property_id))
        if date_from:
            try:
                query = query.filter(Job.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
            except ValueError:
                pass
        if date_to:
            try:
                query = query.filter(Job.created_at <= datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
            except ValueError:
                pass

        jobs_list = query.order_by(desc(Job.created_at)).all()

        properties_q = db.query(Property).filter_by(client_id=user.client_id, is_active=True)
        if prop_ids is not None:
            properties_q = properties_q.filter(Property.id.in_(prop_ids))

        return render_template('portal/jobs.html',
            user=user,
            active_page='jobs',
            jobs=jobs_list,
            properties=properties_q.all(),
            selected_status=status,
            selected_property=property_id,
            date_from=date_from,
            date_to=date_to,
        )
    finally:
        db.close()


@portal_bp.route('/jobs/<int:job_id>')
@portal_login_required
@portal_permission_required('can_view_jobs')
def portal_job_detail(job_id):
    user = g.portal_user
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, client_id=user.client_id).first()
        if not job:
            abort(404)

        # Don't show drafts unless it's a portal request
        if job.status == 'draft' and job.source != 'portal_request':
            abort(404)

        prop_ids = get_accessible_property_ids()
        if prop_ids is not None and job.property_id and job.property_id not in prop_ids:
            abort(403)

        # Status timeline
        status_order = ['draft', 'scheduled', 'in_progress', 'completed']
        current_idx = status_order.index(job.status) if job.status in status_order else -1
        timeline_steps = []
        for i, s in enumerate(status_order):
            label_map = {'draft': 'Requested', 'scheduled': 'Scheduled',
                         'in_progress': 'In Progress', 'completed': 'Completed'}
            timeline_steps.append({
                'key': s, 'label': label_map.get(s, s.title()),
                'completed': i < current_idx, 'active': i == current_idx,
            })

        # Phases
        phases = list(job.phases) if job.phases else []

        # Change orders
        change_orders = db.query(ChangeOrder).filter_by(job_id=job.id).order_by(
            ChangeOrder.created_at).all()

        # Documents (non-confidential)
        documents = db.query(Document).filter(
            Document.entity_type == 'job',
            Document.entity_id == job.id,
            or_(Document.is_confidential == False, Document.is_confidential == None)
        ).order_by(desc(Document.created_at)).all()

        # Portal messages
        messages = []
        if user.can_send_messages():
            messages = db.query(PortalMessage).filter_by(job_id=job.id).order_by(
                PortalMessage.created_at).all()
            # Mark unread messages as read
            unread = db.query(PortalMessage).filter_by(
                job_id=job.id, sender_type='internal_user', is_read_by_recipient=False
            ).all()
            for msg in unread:
                msg.is_read_by_recipient = True
            if unread:
                db.commit()

        # Linked quote and invoice
        linked_quote = None
        linked_invoice = None
        if user.can_view_quotes() and job.quote_id:
            linked_quote = db.query(Quote).filter_by(id=job.quote_id, client_id=user.client_id).first()
        if user.can_view_invoices():
            linked_invoice = db.query(Invoice).filter_by(job_id=job.id, client_id=user.client_id).first()

        return render_template('portal/job_detail.html',
            user=user,
            active_page='jobs',
            job=job,
            timeline_steps=timeline_steps,
            phases=phases,
            change_orders=change_orders,
            documents=documents,
            messages=messages,
            linked_quote=linked_quote,
            linked_invoice=linked_invoice,
        )
    finally:
        db.close()


@portal_bp.route('/jobs/<int:job_id>/message', methods=['POST'])
@portal_login_required
@portal_permission_required('can_send_messages')
def portal_send_message(job_id):
    user = g.portal_user
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, client_id=user.client_id).first()
        if not job:
            abort(404)

        message_text = request.form.get('message', '').strip()
        if not message_text:
            flash('Message cannot be empty.', 'danger')
            return redirect(url_for('portal.portal_job_detail', job_id=job_id))

        if len(message_text) > 5000:
            flash('Message is too long (max 5000 characters).', 'danger')
            return redirect(url_for('portal.portal_job_detail', job_id=job_id))

        msg = PortalMessage(
            job_id=job_id,
            sender_type='portal_user',
            sender_id=user.id,
            message=message_text,
        )
        db.add(msg)

        # Create notification for internal users
        from models.portal_notification import PortalNotification
        notification = PortalNotification(
            notification_type='portal_message',
            title=f'New message from {user.full_name}',
            message=message_text[:200],
            link=f'/jobs/{job_id}',
            triggered_by_portal_user_id=user.id,
            target_type='internal',
            client_id=user.client_id,
            job_id=job_id,
        )
        db.add(notification)
        db.commit()

        flash('Message sent.', 'success')
    finally:
        db.close()
    return redirect(url_for('portal.portal_job_detail', job_id=job_id))


# ═══════════════════════════════════════════════════════════════════════════
#  QUOTES
# ═══════════════════════════════════════════════════════════════════════════

@portal_bp.route('/quotes')
@portal_login_required
@portal_permission_required('can_view_quotes')
def portal_quotes():
    user = g.portal_user
    db = get_session()
    try:
        query = db.query(Quote).filter(
            Quote.client_id == user.client_id,
            Quote.status != 'draft'
        )

        status = request.args.get('status')
        if status:
            query = query.filter(Quote.status == status)

        quotes_list = query.order_by(desc(Quote.created_at)).all()

        return render_template('portal/quotes.html',
            user=user,
            active_page='quotes',
            quotes=quotes_list,
            selected_status=status,
        )
    finally:
        db.close()


@portal_bp.route('/quotes/<int:quote_id>')
@portal_login_required
@portal_permission_required('can_view_quotes')
def portal_quote_detail(quote_id):
    user = g.portal_user
    db = get_session()
    try:
        quote = db.query(Quote).filter_by(id=quote_id, client_id=user.client_id).first()
        if not quote or quote.status == 'draft':
            abort(404)

        return render_template('portal/quote_detail.html',
            user=user,
            active_page='quotes',
            quote=quote,
        )
    finally:
        db.close()


@portal_bp.route('/quotes/<int:quote_id>/approve', methods=['POST'])
@portal_login_required
@portal_permission_required('can_approve_quotes')
def portal_approve_quote(quote_id):
    user = g.portal_user
    db = get_session()
    try:
        settings = PortalSettings.get_settings(db)
        if not settings.allow_quote_approval:
            flash('Online quote approval is currently disabled.', 'warning')
            return redirect(url_for('portal.portal_quote_detail', quote_id=quote_id))

        quote = db.query(Quote).filter_by(id=quote_id, client_id=user.client_id).first()
        if not quote:
            abort(404)

        if quote.status not in ('sent', 'pending'):
            flash('This quote has already been processed.', 'warning')
            return redirect(url_for('portal.portal_quote_detail', quote_id=quote_id))

        quote.status = 'approved'
        quote.approved_date = datetime.now(timezone.utc)
        quote.portal_approved_by = user.id
        quote.portal_approved_at = datetime.now(timezone.utc)

        from models.portal_notification import PortalNotification
        notification = PortalNotification(
            notification_type='quote_approved',
            title=f'Quote #{quote.quote_number or quote.id} approved by {user.full_name}',
            message=f'{user.full_name} approved quote ${float(quote.total or 0):,.2f}',
            link=f'/quotes/{quote.id}',
            triggered_by_portal_user_id=user.id,
            target_type='internal',
            client_id=user.client_id,
        )
        db.add(notification)
        db.commit()

        flash(f'Quote #{quote.quote_number or quote.id} has been approved.', 'success')
        return redirect(url_for('portal.portal_quote_detail', quote_id=quote_id))
    finally:
        db.close()


@portal_bp.route('/quotes/<int:quote_id>/request-changes', methods=['POST'])
@portal_login_required
@portal_permission_required('can_approve_quotes')
def portal_request_quote_changes(quote_id):
    user = g.portal_user
    db = get_session()
    try:
        quote = db.query(Quote).filter_by(id=quote_id, client_id=user.client_id).first()
        if not quote:
            abort(404)

        if quote.status not in ('sent', 'pending'):
            flash('This quote has already been processed.', 'warning')
            return redirect(url_for('portal.portal_quote_detail', quote_id=quote_id))

        feedback = request.form.get('feedback', '').strip()
        if not feedback:
            flash('Please provide details about the changes you need.', 'danger')
            return redirect(url_for('portal.portal_quote_detail', quote_id=quote_id))

        quote.status = 'declined'  # Using existing status; internal team sees feedback
        quote.portal_approval_note = feedback

        from models.portal_notification import PortalNotification
        notification = PortalNotification(
            notification_type='quote_change_requested',
            title=f'Quote #{quote.quote_number or quote.id} -- changes requested',
            message=f'{user.full_name}: {feedback[:200]}',
            link=f'/quotes/{quote.id}',
            triggered_by_portal_user_id=user.id,
            target_type='internal',
            client_id=user.client_id,
        )
        db.add(notification)
        db.commit()

        flash('Your feedback has been sent. We will revise the quote and get back to you.', 'success')
        return redirect(url_for('portal.portal_quote_detail', quote_id=quote_id))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  CHANGE ORDERS
# ═══════════════════════════════════════════════════════════════════════════

@portal_bp.route('/jobs/<int:job_id>/change-orders/<int:co_id>')
@portal_login_required
@portal_permission_required('can_approve_change_orders')
def portal_change_order_review(job_id, co_id):
    user = g.portal_user
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, client_id=user.client_id).first()
        if not job:
            abort(404)
        co = db.query(ChangeOrder).filter_by(id=co_id, job_id=job.id).first()
        if not co:
            abort(404)

        return render_template('portal/change_order_review.html',
            user=user, active_page='jobs', job=job, co=co)
    finally:
        db.close()


@portal_bp.route('/jobs/<int:job_id>/change-orders/<int:co_id>/approve', methods=['POST'])
@portal_login_required
@portal_permission_required('can_approve_change_orders')
def portal_approve_change_order(job_id, co_id):
    user = g.portal_user
    db = get_session()
    try:
        settings = PortalSettings.get_settings(db)
        if not settings.allow_change_order_approval:
            flash('Online change order approval is currently disabled.', 'warning')
            return redirect(url_for('portal.portal_change_order_review', job_id=job_id, co_id=co_id))

        job = db.query(Job).filter_by(id=job_id, client_id=user.client_id).first()
        if not job:
            abort(404)
        co = db.query(ChangeOrder).filter_by(id=co_id, job_id=job.id).first()
        if not co:
            abort(404)

        if co.client_approved is not None:
            flash('This change order has already been reviewed.', 'warning')
            return redirect(url_for('portal.portal_job_detail', job_id=job_id))

        co.client_approved = True
        co.client_approved_by = user.full_name
        co.client_approved_by_portal_id = user.id
        co.client_approved_date = datetime.now(timezone.utc)
        co.status = 'approved'

        from models.portal_notification import PortalNotification
        notification = PortalNotification(
            notification_type='co_approved',
            title=f'CO {co.change_order_number} approved by {user.full_name}',
            message=f'{user.full_name} approved change order for job #{job.job_number or job.id}',
            link=f'/jobs/{job.id}',
            triggered_by_portal_user_id=user.id,
            target_type='internal',
            client_id=user.client_id,
            job_id=job.id,
        )
        db.add(notification)
        db.commit()

        flash(f'Change Order {co.change_order_number} has been approved.', 'success')
    finally:
        db.close()
    return redirect(url_for('portal.portal_job_detail', job_id=job_id))


@portal_bp.route('/jobs/<int:job_id>/change-orders/<int:co_id>/reject', methods=['POST'])
@portal_login_required
@portal_permission_required('can_approve_change_orders')
def portal_reject_change_order(job_id, co_id):
    user = g.portal_user
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, client_id=user.client_id).first()
        if not job:
            abort(404)
        co = db.query(ChangeOrder).filter_by(id=co_id, job_id=job.id).first()
        if not co:
            abort(404)

        if co.client_approved is not None:
            flash('This change order has already been reviewed.', 'warning')
            return redirect(url_for('portal.portal_job_detail', job_id=job_id))

        reason = request.form.get('reason', '').strip()
        if not reason:
            flash('Please provide a reason for rejection.', 'danger')
            return redirect(url_for('portal.portal_change_order_review', job_id=job_id, co_id=co_id))

        co.client_approved = False
        co.client_approved_by = user.full_name
        co.client_approved_by_portal_id = user.id
        co.client_approved_date = datetime.now(timezone.utc)
        co.client_rejection_reason = reason
        co.rejection_reason = reason
        co.status = 'rejected'

        from models.portal_notification import PortalNotification
        notification = PortalNotification(
            notification_type='co_rejected',
            title=f'CO {co.change_order_number} rejected by {user.full_name}',
            message=f'{user.full_name} rejected: {reason[:200]}',
            link=f'/jobs/{job.id}',
            triggered_by_portal_user_id=user.id,
            target_type='internal',
            client_id=user.client_id,
            job_id=job.id,
        )
        db.add(notification)
        db.commit()

        flash(f'Change Order {co.change_order_number} has been rejected.', 'info')
    finally:
        db.close()
    return redirect(url_for('portal.portal_job_detail', job_id=job_id))


# ═══════════════════════════════════════════════════════════════════════════
#  INVOICES
# ═══════════════════════════════════════════════════════════════════════════

@portal_bp.route('/invoices')
@portal_login_required
@portal_permission_required('can_view_invoices')
def portal_invoices():
    user = g.portal_user
    db = get_session()
    try:
        query = db.query(Invoice).filter(
            Invoice.client_id == user.client_id,
            Invoice.status != 'draft'
        )

        status = request.args.get('status')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')

        if status:
            if status == 'outstanding':
                query = query.filter(Invoice.status.in_(['sent', 'overdue', 'partial']))
            else:
                query = query.filter(Invoice.status == status)

        if date_from:
            try:
                query = query.filter(Invoice.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
            except ValueError:
                pass
        if date_to:
            try:
                query = query.filter(Invoice.created_at <= datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
            except ValueError:
                pass

        invoices_list = query.order_by(desc(Invoice.created_at)).all()

        # Account Summary
        outstanding_total = float(db.query(
            func.coalesce(func.sum(Invoice.balance_due), 0)
        ).filter(
            Invoice.client_id == user.client_id,
            Invoice.status.in_(['sent', 'overdue', 'partial'])
        ).scalar() or 0)

        # Aging breakdown
        now = datetime.now(timezone.utc)
        aging = {'current': 0, 'thirty': 0, 'sixty': 0, 'ninety_plus': 0}

        outstanding_invs = db.query(Invoice).filter(
            Invoice.client_id == user.client_id,
            Invoice.status.in_(['sent', 'overdue', 'partial'])
        ).all()

        for inv in outstanding_invs:
            due = inv.due_date or inv.created_at
            if due and hasattr(due, 'date'):
                due = due.date() if callable(getattr(due, 'date', None)) else due
            days = (now.date() - due).days if due else 0
            amt = float(inv.balance_due or 0)
            if days <= 0:
                aging['current'] += amt
            elif days <= 30:
                aging['thirty'] += amt
            elif days <= 60:
                aging['sixty'] += amt
            else:
                aging['ninety_plus'] += amt

        return render_template('portal/invoices.html',
            user=user,
            active_page='invoices',
            invoices=invoices_list,
            outstanding_total=outstanding_total,
            aging=aging,
            selected_status=status,
            date_from=date_from,
            date_to=date_to,
        )
    finally:
        db.close()


@portal_bp.route('/invoices/<int:invoice_id>')
@portal_login_required
@portal_permission_required('can_view_invoices')
def portal_invoice_detail(invoice_id):
    user = g.portal_user
    db = get_session()
    try:
        invoice = db.query(Invoice).filter_by(id=invoice_id, client_id=user.client_id).first()
        if not invoice or invoice.status == 'draft':
            abort(404)

        settings = PortalSettings.get_settings(db)

        return render_template('portal/invoice_detail.html',
            user=user,
            active_page='invoices',
            invoice=invoice,
            settings=settings,
        )
    finally:
        db.close()


@portal_bp.route('/invoices/statement')
@portal_login_required
@portal_permission_required('can_view_invoices')
def portal_generate_statement():
    """Generate account statement for date range."""
    user = g.portal_user
    db = get_session()
    try:
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')

        if not date_from or not date_to:
            date_to_dt = datetime.now(timezone.utc)
            date_from_dt = date_to_dt - timedelta(days=90)
        else:
            try:
                date_from_dt = datetime.strptime(date_from, '%Y-%m-%d')
                date_to_dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            except ValueError:
                flash('Invalid date format.', 'danger')
                return redirect(url_for('portal.portal_invoices'))

        invoices_list = db.query(Invoice).filter(
            Invoice.client_id == user.client_id,
            Invoice.status != 'draft',
            Invoice.created_at >= date_from_dt,
            Invoice.created_at <= date_to_dt
        ).order_by(Invoice.created_at).all()

        total_invoiced = sum(float(inv.total or 0) for inv in invoices_list)
        total_paid = sum(float(inv.amount_paid or 0) for inv in invoices_list)
        total_outstanding = sum(float(inv.balance_due or 0) for inv in invoices_list)

        return render_template('portal/statement.html',
            user=user,
            active_page='invoices',
            invoices=invoices_list,
            date_from=date_from_dt,
            date_to=date_to_dt,
            total_invoiced=total_invoiced,
            total_paid=total_paid,
            total_outstanding=total_outstanding,
            client=user.client,
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  DOCUMENTS
# ═══════════════════════════════════════════════════════════════════════════

@portal_bp.route('/documents')
@portal_login_required
@portal_permission_required('can_view_documents')
def portal_documents():
    user = g.portal_user
    db = get_session()
    try:
        # Find all job IDs for this client (for entity_type='job' lookup)
        job_ids_q = db.query(Job.id).filter(Job.client_id == user.client_id)
        prop_ids = get_accessible_property_ids()
        if prop_ids is not None:
            job_ids_q = job_ids_q.filter(Job.property_id.in_(prop_ids))
        client_job_ids = [r[0] for r in job_ids_q.all()]

        # Documents: job-linked + portal-uploaded by this client's portal users
        from models.portal_user import PortalUser
        portal_user_ids = [r[0] for r in db.query(PortalUser.id).filter_by(client_id=user.client_id).all()]

        query = db.query(Document).filter(
            Document.is_confidential == False,
            or_(
                # Job-linked documents
                (Document.entity_type == 'job') & (Document.entity_id.in_(client_job_ids)) if client_job_ids else False,
                # Portal-uploaded documents
                Document.uploaded_by_portal_user_id.in_(portal_user_ids) if portal_user_ids else False,
            )
        )

        # Billing-only: restrict categories
        if user.role == 'billing_only':
            query = query.filter(Document.category.in_(['invoice', 'contract', 'quote', 'correspondence', 'other']))

        # Search
        search = request.args.get('search', '').strip()
        if search:
            query = query.filter(
                or_(
                    Document.display_name.ilike(f'%{search}%'),
                    Document.category.ilike(f'%{search}%'),
                    Document.description.ilike(f'%{search}%'),
                )
            )

        # Category filter
        category = request.args.get('category')
        if category:
            query = query.filter(Document.category == category)

        documents_list = query.order_by(desc(Document.created_at)).all()

        # Unique categories for filter
        all_cats = set(d.category for d in documents_list if d.category)

        return render_template('portal/documents.html',
            user=user,
            active_page='documents',
            documents=documents_list,
            categories=sorted(all_cats),
            selected_category=category,
            search=search,
        )
    finally:
        db.close()


@portal_bp.route('/documents/<int:document_id>/download')
@portal_login_required
@portal_permission_required('can_view_documents')
def portal_download_document(document_id):
    user = g.portal_user
    db = get_session()
    try:
        doc = db.query(Document).filter_by(id=document_id).first()
        if not doc:
            abort(404)

        # Security: verify document belongs to client's scope
        if doc.is_confidential:
            abort(403)

        # Check via entity linkage
        if doc.entity_type == 'job' and doc.entity_id:
            job = db.query(Job).filter_by(id=doc.entity_id, client_id=user.client_id).first()
            if not job:
                abort(403)
        elif doc.uploaded_by_portal_user_id:
            from models.portal_user import PortalUser
            uploader = db.query(PortalUser).filter_by(id=doc.uploaded_by_portal_user_id).first()
            if not uploader or uploader.client_id != user.client_id:
                abort(403)
        else:
            abort(403)

        import os
        if not os.path.exists(doc.file_path):
            abort(404)

        from flask import send_file
        return send_file(doc.file_path, download_name=doc.filename, as_attachment=True)
    finally:
        db.close()


@portal_bp.route('/documents/upload', methods=['POST'])
@portal_login_required
@portal_permission_required('can_upload_documents')
def portal_upload_document():
    user = g.portal_user
    db = get_session()
    try:
        file = request.files.get('file')
        if not file or not file.filename:
            flash('Please select a file to upload.', 'danger')
            return redirect(url_for('portal.portal_documents'))

        description = request.form.get('description', '').strip()

        try:
            save_uploaded_file(
                db, file,
                entity_type='client_upload',
                entity_id=user.client_id,
                category='other',
                display_name=None,
                description=description or None,
                uploaded_by=None,
            )
            # Set portal user on the just-created document
            doc = db.query(Document).order_by(desc(Document.id)).first()
            if doc:
                doc.uploaded_by_portal_user_id = user.id
            db.commit()
            flash(f'Document uploaded successfully.', 'success')
        except ValueError as e:
            flash(str(e), 'danger')

        return redirect(url_for('portal.portal_documents'))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  REPORTS
# ═══════════════════════════════════════════════════════════════════════════

@portal_bp.route('/reports')
@portal_login_required
@portal_permission_required('can_view_reports')
def portal_reports():
    return render_template('portal/reports.html',
        user=g.portal_user, active_page='reports')


@portal_bp.route('/reports/service-history')
@portal_login_required
@portal_permission_required('can_view_reports')
def portal_report_service_history():
    user = g.portal_user
    db = get_session()
    try:
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        property_id = request.args.get('property')

        now = datetime.now(timezone.utc)
        date_from_dt = datetime.strptime(date_from, '%Y-%m-%d') if date_from else now - timedelta(days=365)
        date_to_dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1) if date_to else now

        query = db.query(Job).filter(
            Job.client_id == user.client_id,
            Job.status != 'draft',
            Job.created_at >= date_from_dt,
            Job.created_at <= date_to_dt
        )

        prop_ids = get_accessible_property_ids()
        if prop_ids is not None:
            query = query.filter(Job.property_id.in_(prop_ids))
        if property_id:
            query = query.filter(Job.property_id == int(property_id))

        jobs_list = query.order_by(desc(Job.created_at)).all()

        total_jobs = len(jobs_list)
        completed = sum(1 for j in jobs_list if j.status in ('completed',))
        in_progress = sum(1 for j in jobs_list if j.status == 'in_progress')

        properties_q = db.query(Property).filter_by(client_id=user.client_id, is_active=True)
        if prop_ids is not None:
            properties_q = properties_q.filter(Property.id.in_(prop_ids))

        # CSV export
        if request.args.get('format') == 'csv':
            import csv, io
            from flask import Response
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Job #', 'Property', 'Title', 'Status', 'Date', 'Type'])
            for j in jobs_list:
                writer.writerow([
                    j.job_number or j.id,
                    j.property.display_address if j.property else '',
                    j.title or '',
                    j.status or '',
                    j.created_at.strftime('%Y-%m-%d') if j.created_at else '',
                    j.job_type or '',
                ])
            output.seek(0)
            return Response(output.getvalue(), mimetype='text/csv',
                           headers={'Content-Disposition': 'attachment; filename=service_history.csv'})

        return render_template('portal/report_service_history.html',
            user=user, active_page='reports',
            jobs=jobs_list,
            total_jobs=total_jobs,
            completed=completed,
            in_progress=in_progress,
            properties=properties_q.all(),
            date_from=date_from_dt,
            date_to=date_to_dt,
            selected_property=property_id,
        )
    finally:
        db.close()


@portal_bp.route('/reports/spend-summary')
@portal_login_required
@portal_permission_required('can_view_reports')
def portal_report_spend_summary():
    user = g.portal_user
    db = get_session()
    try:
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')

        now = datetime.now(timezone.utc)
        date_from_dt = datetime.strptime(date_from, '%Y-%m-%d') if date_from else now - timedelta(days=365)
        date_to_dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1) if date_to else now

        invoices = db.query(Invoice).filter(
            Invoice.client_id == user.client_id,
            Invoice.status != 'draft',
            Invoice.created_at >= date_from_dt,
            Invoice.created_at <= date_to_dt
        ).order_by(Invoice.created_at).all()

        total_spend = sum(float(inv.total or 0) for inv in invoices)
        total_paid = sum(float(inv.amount_paid or 0) for inv in invoices)

        # Monthly breakdown
        monthly = {}
        for inv in invoices:
            if not inv.created_at:
                continue
            key = inv.created_at.strftime('%Y-%m')
            if key not in monthly:
                monthly[key] = {'label': inv.created_at.strftime('%b %Y'), 'amount': 0, 'count': 0}
            monthly[key]['amount'] += float(inv.total or 0)
            monthly[key]['count'] += 1

        monthly_data = list(monthly.values())

        # CSV export
        if request.args.get('format') == 'csv':
            import csv, io
            from flask import Response
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Month', 'Invoice Count', 'Total Amount'])
            for m in monthly_data:
                writer.writerow([m['label'], m['count'], f"{m['amount']:.2f}"])
            output.seek(0)
            return Response(output.getvalue(), mimetype='text/csv',
                           headers={'Content-Disposition': 'attachment; filename=spend_summary.csv'})

        return render_template('portal/report_spend_summary.html',
            user=user, active_page='reports',
            invoices=invoices,
            total_spend=total_spend,
            total_paid=total_paid,
            monthly_data=monthly_data,
            date_from=date_from_dt,
            date_to=date_to_dt,
        )
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  PORTAL USER MANAGEMENT (for primary portal users)
# ═══════════════════════════════════════════════════════════════════════════

@portal_bp.route('/manage-users')
@portal_login_required
@portal_permission_required('can_manage_portal_users')
def portal_manage_users():
    user = g.portal_user
    db = get_session()
    try:
        users = db.query(PortalUser).filter_by(client_id=user.client_id).order_by(
            PortalUser.created_at
        ).all()
        return render_template('portal/manage_users.html',
            user=user, active_page='manage_users', users=users)
    finally:
        db.close()


@portal_bp.route('/manage-users/invite', methods=['POST'])
@portal_login_required
@portal_permission_required('can_manage_portal_users')
def portal_invite_user():
    user = g.portal_user
    db = get_session()
    try:
        f = request.form
        email = f.get('email', '').strip().lower()
        first_name = f.get('first_name', '').strip()
        last_name = f.get('last_name', '').strip()
        role = f.get('role', 'standard')

        if not email or not first_name or not last_name:
            flash('All fields are required.', 'danger')
            return redirect(url_for('portal.portal_manage_users'))

        # Primary users can only create standard, billing_only, view_only
        allowed_roles = ['standard', 'billing_only', 'view_only']
        if role not in allowed_roles:
            flash('You can only create Standard, Billing Only, or View Only users.', 'danger')
            return redirect(url_for('portal.portal_manage_users'))

        if db.query(PortalUser).filter_by(email=email).first():
            flash('A user with this email already exists.', 'danger')
            return redirect(url_for('portal.portal_manage_users'))

        new_user = PortalUser(
            email=email,
            first_name=first_name,
            last_name=last_name,
            client_id=user.client_id,
            role=role,
        )
        db.add(new_user)
        db.flush()

        token = new_user.generate_invitation_token()
        db.commit()

        try:
            from web.utils.portal_email import send_welcome_email
            send_welcome_email(new_user, token)
            flash(f'Invitation sent to {email}.', 'success')
        except Exception as e:
            current_app.logger.error(f"Failed to send invitation: {e}")
            flash(f'User created but invitation email failed.', 'warning')

        return redirect(url_for('portal.portal_manage_users'))
    finally:
        db.close()
