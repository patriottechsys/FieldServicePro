"""Change Order CRUD routes."""

from datetime import timezone, date, datetime
from flask import (
    Blueprint, request, render_template, redirect,
    url_for, flash, abort, jsonify,
)
from flask_login import login_required, current_user
from models.database import get_session
from models.job import Job
from models.job_phase import JobPhase
from models.change_order import (
    ChangeOrder, ChangeOrderStatus, ChangeOrderReason,
    ChangeOrderRequestedBy, ChangeOrderCostType,
)
from models.division import Division
from web.utils.change_order_utils import (
    create_change_order, update_change_order,
    save_line_items, can_create_change_order, apply_approved_change_order,
)
from web.auth import role_required

change_orders_bp = Blueprint('change_orders', __name__)


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


def _tpl_vars(**extra):
    base = dict(active_page='change_orders', user=current_user, divisions=_get_divisions())
    base.update(extra)
    return base


# -- New Change Order --

@change_orders_bp.route('/jobs/<int:job_id>/change-orders/new', methods=['GET', 'POST'])
@login_required
def new_change_order(job_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        job = db.query(Job).filter_by(id=job_id, organization_id=org_id).first()
        if not job:
            abort(404)

        allowed, reason_msg = can_create_change_order(job)
        if not allowed:
            flash(reason_msg, 'warning')
            return redirect(url_for('jobs_bp.job_detail', job_id=job_id))

        if current_user.role == 'viewer':
            abort(403)

        if request.method == 'POST':
            action = request.form.get('action', 'draft')
            try:
                co = create_change_order(db, job, request.form, created_by_id=current_user.id)
                save_line_items(db, co, request.form)

                if action == 'submit':
                    co.status = ChangeOrderStatus.submitted.value

                db.commit()

                if co.status in ('submitted', 'pending_approval'):
                    try:
                        from web.utils.notification_service import NotificationService
                        NotificationService.notify('approval_needed_change_order', co, triggered_by=current_user)
                    except Exception:
                        pass

                flash(f'Change Order {co.change_order_number} created.', 'success')
                return redirect(url_for('change_orders.co_detail', job_id=job_id, co_id=co.id))
            except Exception as e:
                db.rollback()
                flash(f'Error creating change order: {str(e)}', 'danger')

        phases = job.phases if job.is_multi_phase else []

        return render_template('change_orders/co_new.html',
                               **_tpl_vars(
                                   job=job, phases=phases, co=None,
                                   reasons=ChangeOrderReason,
                                   requested_bys=ChangeOrderRequestedBy,
                                   cost_types=ChangeOrderCostType,
                                   today=date.today(),
                               ))
    finally:
        db.close()


# -- Edit Change Order --

@change_orders_bp.route('/jobs/<int:job_id>/change-orders/<int:co_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_change_order(job_id, co_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        job = db.query(Job).filter_by(id=job_id, organization_id=org_id).first()
        if not job:
            abort(404)
        co = db.query(ChangeOrder).filter_by(id=co_id, job_id=job_id).first()
        if not co:
            abort(404)

        if not co.is_editable:
            flash('This change order cannot be edited in its current state.', 'warning')
            return redirect(url_for('change_orders.co_detail', job_id=job_id, co_id=co_id))

        if current_user.role == 'viewer':
            abort(403)

        if request.method == 'POST':
            action = request.form.get('action', 'draft')
            try:
                update_change_order(db, co, request.form)
                save_line_items(db, co, request.form)
                if action == 'submit':
                    co.status = ChangeOrderStatus.submitted.value
                db.commit()
                flash('Change order updated.', 'success')
                return redirect(url_for('change_orders.co_detail', job_id=job_id, co_id=co_id))
            except Exception as e:
                db.rollback()
                flash(f'Error: {str(e)}', 'danger')

        phases = job.phases if job.is_multi_phase else []
        return render_template('change_orders/co_new.html',
                               **_tpl_vars(
                                   job=job, phases=phases, co=co,
                                   reasons=ChangeOrderReason,
                                   requested_bys=ChangeOrderRequestedBy,
                                   cost_types=ChangeOrderCostType,
                                   today=date.today(),
                               ))
    finally:
        db.close()


# -- Change Order Detail --

@change_orders_bp.route('/jobs/<int:job_id>/change-orders/<int:co_id>')
@login_required
def co_detail(job_id, co_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        job = db.query(Job).filter_by(id=job_id, organization_id=org_id).first()
        if not job:
            abort(404)
        co = db.query(ChangeOrder).filter_by(id=co_id, job_id=job_id).first()
        if not co:
            abort(404)

        can_approve = current_user.role in ('admin', 'owner')

        return render_template('change_orders/co_detail.html',
                               **_tpl_vars(job=job, co=co, can_approve=can_approve))
    finally:
        db.close()


# -- Approve Change Order --

@change_orders_bp.route('/jobs/<int:job_id>/change-orders/<int:co_id>/approve', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def approve_change_order(job_id, co_id):
    db = get_session()
    try:
        co = db.query(ChangeOrder).filter_by(id=co_id, job_id=job_id).first()
        if not co:
            abort(404)
        if co.status not in ('submitted', 'pending_approval'):
            flash('Change order is not awaiting approval.', 'warning')
            return redirect(url_for('change_orders.co_detail', job_id=job_id, co_id=co_id))

        co.status = ChangeOrderStatus.approved.value
        co.internal_approved_by_id = current_user.id
        co.internal_approved_date = datetime.now(timezone.utc)

        # Record client approval if provided from modal
        client_approved_by = request.form.get('client_approved_by')
        if client_approved_by:
            co.client_approved = True
            co.client_approved_by = client_approved_by
            co.client_approved_date = datetime.now(timezone.utc)

        job = db.query(Job).filter_by(id=job_id).first()
        apply_approved_change_order(db, co)

        db.commit()

        try:
            from web.utils.notification_service import NotificationService
            NotificationService.notify('item_approved', co, triggered_by=current_user)
        except Exception:
            pass

        flash(f'Change Order {co.change_order_number} approved. Job total updated by ${co.cost_difference:+,.2f}.', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Error: {str(e)}', 'danger')
    finally:
        db.close()
    return redirect(url_for('change_orders.co_detail', job_id=job_id, co_id=co_id))


# -- Reject Change Order --

@change_orders_bp.route('/jobs/<int:job_id>/change-orders/<int:co_id>/reject', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def reject_change_order(job_id, co_id):
    db = get_session()
    try:
        co = db.query(ChangeOrder).filter_by(id=co_id, job_id=job_id).first()
        if not co:
            abort(404)

        reason = request.form.get('rejection_reason', '').strip()
        co.status = ChangeOrderStatus.rejected.value
        co.rejection_reason = reason
        db.commit()

        try:
            from web.utils.notification_service import NotificationService
            NotificationService.notify('item_rejected', co, triggered_by=current_user,
                                       extra_context={'reason': reason})
        except Exception:
            pass

        flash(f'Change Order {co.change_order_number} rejected.', 'warning')
    except Exception as e:
        db.rollback()
        flash(f'Error: {str(e)}', 'danger')
    finally:
        db.close()
    return redirect(url_for('change_orders.co_detail', job_id=job_id, co_id=co_id))


# -- Void Change Order --

@change_orders_bp.route('/jobs/<int:job_id>/change-orders/<int:co_id>/void', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def void_change_order(job_id, co_id):
    db = get_session()
    try:
        co = db.query(ChangeOrder).filter_by(id=co_id, job_id=job_id).first()
        if not co:
            abort(404)
        if co.status == 'approved':
            flash('Cannot void an approved change order. Create a corrective CO instead.', 'warning')
        else:
            co.status = ChangeOrderStatus.voided.value
            db.commit()
            flash(f'Change Order {co.change_order_number} voided.', 'info')
    finally:
        db.close()
    return redirect(url_for('change_orders.co_detail', job_id=job_id, co_id=co_id))


# -- Submit Change Order (draft -> submitted) --

@change_orders_bp.route('/jobs/<int:job_id>/change-orders/<int:co_id>/submit', methods=['POST'])
@login_required
def submit_change_order(job_id, co_id):
    db = get_session()
    try:
        co = db.query(ChangeOrder).filter_by(id=co_id, job_id=job_id).first()
        if not co:
            abort(404)
        if co.status != 'draft':
            flash('Only draft change orders can be submitted.', 'warning')
            return redirect(url_for('change_orders.co_detail', job_id=job_id, co_id=co_id))

        co.status = ChangeOrderStatus.submitted.value
        db.commit()
        flash(f'{co.change_order_number} submitted for approval.', 'success')
    finally:
        db.close()
    return redirect(url_for('change_orders.co_detail', job_id=job_id, co_id=co_id))


# -- Escalate to Pending Approval --

@change_orders_bp.route('/jobs/<int:job_id>/change-orders/<int:co_id>/pending-approval', methods=['POST'])
@login_required
@role_required('owner', 'admin', 'dispatcher')
def set_pending_approval(job_id, co_id):
    db = get_session()
    try:
        co = db.query(ChangeOrder).filter_by(id=co_id, job_id=job_id).first()
        if not co:
            abort(404)
        if co.status == 'submitted':
            co.status = ChangeOrderStatus.pending_approval.value
            db.commit()
            flash('Change order escalated to pending approval.', 'info')
    finally:
        db.close()
    return redirect(url_for('change_orders.co_detail', job_id=job_id, co_id=co_id))


# -- Global Change Order List --

@change_orders_bp.route('/change-orders')
@login_required
def co_list():
    db = get_session()
    try:
        org_id = current_user.organization_id
        status_filter = request.args.get('status', '')

        q = db.query(ChangeOrder).join(Job).filter(Job.organization_id == org_id)
        if status_filter:
            q = q.filter(ChangeOrder.status == status_filter)

        change_orders = q.order_by(ChangeOrder.created_at.desc()).all()

        pending_count = db.query(ChangeOrder).join(Job).filter(
            Job.organization_id == org_id,
            ChangeOrder.status.in_(['submitted', 'pending_approval'])
        ).count()

        return render_template('change_orders/co_list.html',
                               **_tpl_vars(
                                   change_orders=change_orders,
                                   status_filter=status_filter,
                                   statuses=ChangeOrderStatus,
                                   pending_count=pending_count,
                               ))
    finally:
        db.close()
