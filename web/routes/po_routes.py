"""Purchase Order CRUD routes."""

import os
from datetime import timezone, date, datetime, timedelta
from flask import (
    Blueprint, render_template, redirect, url_for, request,
    flash, jsonify, abort, current_app,
)
from flask_login import login_required, current_user
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from models.database import get_session
from models.purchase_order import PurchaseOrder, POStatus
from models.po_attachment import POAttachment
from models.client import Client
from models.contract import Contract, ContractStatus
from models.invoice import Invoice
from models.division import Division
from web.auth import role_required

po_bp = Blueprint('purchase_orders', __name__, url_prefix='/purchase-orders')

ALLOWED_PO_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'tif', 'tiff'}


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


def _tpl_vars(**extra):
    base = dict(active_page='purchase_orders', user=current_user, divisions=_get_divisions())
    base.update(extra)
    return base


# -- LIST --

@po_bp.route('/')
@login_required
@role_required('owner', 'admin', 'dispatcher', 'viewer')
def po_list():
    db = get_session()
    try:
        org_id = current_user.organization_id
        q = db.query(PurchaseOrder).filter_by(organization_id=org_id)

        status_filter = request.args.get('status', '')
        client_filter = request.args.get('client_id', '', type=str)
        expiring_soon = request.args.get('expiring_soon', '')
        search = request.args.get('q', '')

        if status_filter:
            q = q.filter(PurchaseOrder.status == status_filter)
        if client_filter:
            q = q.filter(PurchaseOrder.client_id == int(client_filter))
        if expiring_soon:
            cutoff = date.today() + timedelta(days=30)
            q = q.filter(
                PurchaseOrder.expiry_date <= cutoff,
                PurchaseOrder.expiry_date >= date.today(),
                PurchaseOrder.status == POStatus.active.value,
            )
        if search:
            q = q.filter(or_(
                PurchaseOrder.po_number.ilike(f'%{search}%'),
                PurchaseOrder.department.ilike(f'%{search}%'),
                PurchaseOrder.cost_code.ilike(f'%{search}%'),
            ))

        pos = q.order_by(PurchaseOrder.created_at.desc()).all()

        # Stats
        active_pos = db.query(PurchaseOrder).filter_by(
            organization_id=org_id, status=POStatus.active.value
        ).all()
        total_authorized = sum(float(p.amount_authorized or 0) for p in active_pos)
        total_remaining = sum(p.amount_remaining for p in active_pos)

        # Auto-expire
        changed = False
        for po in active_pos:
            if po.is_expired:
                po.status = POStatus.expired.value
                changed = True
        if changed:
            db.commit()

        clients = db.query(Client).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Client.company_name, Client.last_name).all()

        return render_template('purchase_orders/po_list.html',
                               **_tpl_vars(
                                   pos=pos,
                                   total_authorized=total_authorized,
                                   total_remaining=total_remaining,
                                   active_count=len(active_pos),
                                   clients=clients,
                                   status_filter=status_filter,
                                   client_filter=client_filter,
                                   expiring_soon=expiring_soon,
                                   search=search,
                                   POStatus=POStatus,
                               ))
    finally:
        db.close()


# -- DETAIL --

@po_bp.route('/<int:po_id>')
@login_required
@role_required('owner', 'admin', 'dispatcher', 'viewer')
def po_detail(po_id):
    db = get_session()
    try:
        po = db.query(PurchaseOrder).filter_by(
            id=po_id, organization_id=current_user.organization_id
        ).first()
        if not po:
            abort(404)

        po.check_and_update_status()
        db.commit()

        linked_invoices = db.query(Invoice).filter_by(po_id=po.id)\
                            .order_by(Invoice.created_at.desc()).all()

        return render_template('purchase_orders/po_detail.html',
                               **_tpl_vars(
                                   po=po,
                                   linked_invoices=linked_invoices,
                                   POStatus=POStatus,
                               ))
    finally:
        db.close()


# -- CREATE --

@po_bp.route('/new', methods=['GET', 'POST'])
@login_required
@role_required('owner', 'admin', 'dispatcher')
def po_new():
    db = get_session()
    try:
        org_id = current_user.organization_id
        clients = db.query(Client).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Client.company_name, Client.last_name).all()

        if request.method == 'POST':
            errors = []
            f = request.form

            client_id = f.get('client_id', type=int)
            po_number = f.get('po_number', '').strip()
            amount_str = f.get('amount_authorized', '0').replace(',', '')

            if not client_id:
                errors.append('Client is required.')
            if not po_number:
                errors.append('PO Number is required.')
            elif db.query(PurchaseOrder).filter_by(
                    client_id=client_id, po_number=po_number).first():
                errors.append(f"PO number '{po_number}' already exists for this client.")

            try:
                amount_authorized = float(amount_str)
                if amount_authorized <= 0:
                    errors.append('Authorized amount must be greater than zero.')
            except ValueError:
                errors.append('Invalid authorized amount.')
                amount_authorized = 0

            issue_date_str = f.get('issue_date', '')
            try:
                issue_date = date.fromisoformat(issue_date_str) if issue_date_str else date.today()
            except ValueError:
                errors.append('Invalid issue date.')
                issue_date = date.today()

            expiry_date = None
            expiry_str = f.get('expiry_date', '')
            if expiry_str:
                try:
                    expiry_date = date.fromisoformat(expiry_str)
                    if expiry_date <= issue_date:
                        errors.append('Expiry date must be after issue date.')
                except ValueError:
                    errors.append('Invalid expiry date.')

            if errors:
                for e in errors:
                    flash(e, 'danger')
                return render_template('purchase_orders/po_form.html',
                                       **_tpl_vars(
                                           po=None, clients=clients, form_data=f, mode='new',
                                       ))

            po = PurchaseOrder(
                organization_id=org_id,
                po_number=po_number,
                client_id=client_id,
                contract_id=f.get('contract_id', type=int) or None,
                description=f.get('description', '').strip(),
                status=POStatus.active.value,
                amount_authorized=amount_authorized,
                amount_used=0,
                issue_date=issue_date,
                expiry_date=expiry_date,
                department=f.get('department', '').strip() or None,
                cost_code=f.get('cost_code', '').strip() or None,
                notes=f.get('notes', '').strip() or None,
                created_by=current_user.id,
                updated_by=current_user.id,
            )
            db.add(po)
            db.commit()

            flash(f'Purchase Order {po.po_number} created successfully.', 'success')
            return redirect(url_for('purchase_orders.po_detail', po_id=po.id))

        # GET
        return render_template('purchase_orders/po_form.html',
                               **_tpl_vars(
                                   po=None, clients=clients, form_data={}, mode='new',
                               ))
    finally:
        db.close()


# -- EDIT --

@po_bp.route('/<int:po_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('owner', 'admin')
def po_edit(po_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        po = db.query(PurchaseOrder).filter_by(
            id=po_id, organization_id=org_id
        ).first()
        if not po:
            abort(404)

        clients = db.query(Client).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Client.company_name, Client.last_name).all()

        if request.method == 'POST':
            errors = []
            f = request.form

            po_number = f.get('po_number', '').strip()
            if not po_number:
                errors.append('PO Number is required.')
            elif po_number != po.po_number:
                existing = db.query(PurchaseOrder).filter_by(
                    client_id=po.client_id, po_number=po_number
                ).filter(PurchaseOrder.id != po.id).first()
                if existing:
                    errors.append(f"PO number '{po_number}' already exists for this client.")

            try:
                amount_authorized = float(f.get('amount_authorized', '0').replace(',', ''))
            except ValueError:
                errors.append('Invalid authorized amount.')
                amount_authorized = float(po.amount_authorized or 0)

            expiry_date = None
            expiry_str = f.get('expiry_date', '')
            if expiry_str:
                try:
                    expiry_date = date.fromisoformat(expiry_str)
                except ValueError:
                    errors.append('Invalid expiry date.')

            if errors:
                for e in errors:
                    flash(e, 'danger')
                return render_template('purchase_orders/po_form.html',
                                       **_tpl_vars(
                                           po=po, clients=clients, form_data=f, mode='edit',
                                       ))

            po.po_number = po_number
            po.description = f.get('description', '').strip()
            po.amount_authorized = amount_authorized
            po.expiry_date = expiry_date
            po.department = f.get('department', '').strip() or None
            po.cost_code = f.get('cost_code', '').strip() or None
            po.notes = f.get('notes', '').strip() or None
            po.status = f.get('status', po.status)
            po.updated_by = current_user.id
            po.recalculate_amount_used()

            db.commit()
            flash(f'Purchase Order {po.po_number} updated.', 'success')
            return redirect(url_for('purchase_orders.po_detail', po_id=po.id))

        return render_template('purchase_orders/po_form.html',
                               **_tpl_vars(
                                   po=po, clients=clients, form_data=po, mode='edit',
                               ))
    finally:
        db.close()


# -- CANCEL --

@po_bp.route('/<int:po_id>/cancel', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def po_cancel(po_id):
    db = get_session()
    try:
        po = db.query(PurchaseOrder).filter_by(
            id=po_id, organization_id=current_user.organization_id
        ).first()
        if not po:
            abort(404)
        po.status = POStatus.cancelled.value
        po.updated_by = current_user.id
        db.commit()
        flash(f'PO {po.po_number} has been cancelled.', 'warning')
    finally:
        db.close()
    return redirect(url_for('purchase_orders.po_detail', po_id=po_id))


# -- ATTACHMENT UPLOAD --

@po_bp.route('/<int:po_id>/upload', methods=['POST'])
@login_required
@role_required('owner', 'admin', 'dispatcher')
def po_upload_attachment(po_id):
    db = get_session()
    try:
        po = db.query(PurchaseOrder).filter_by(
            id=po_id, organization_id=current_user.organization_id
        ).first()
        if not po:
            abort(404)

        if 'attachment' not in request.files:
            flash('No file selected.', 'warning')
            return redirect(url_for('purchase_orders.po_detail', po_id=po_id))

        file = request.files['attachment']
        if file.filename == '':
            flash('No file selected.', 'warning')
            return redirect(url_for('purchase_orders.po_detail', po_id=po_id))

        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        if ext not in ALLOWED_PO_EXTENSIONS:
            flash('Invalid file type. Allowed: PDF, PNG, JPG, TIFF.', 'danger')
            return redirect(url_for('purchase_orders.po_detail', po_id=po_id))

        upload_dir = os.path.join(current_app.root_path, 'uploads', 'po', str(po_id))
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = secure_filename(file.filename)
        stored_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{safe_name}"
        file_path = os.path.join(upload_dir, stored_name)
        file.save(file_path)

        att = POAttachment(
            purchase_order_id=po_id,
            filename=stored_name,
            original_filename=safe_name,
            file_size=os.path.getsize(file_path),
            content_type=file.content_type,
            uploaded_by=current_user.id,
            notes=request.form.get('notes', '').strip() or None,
        )
        db.add(att)
        db.commit()
        flash('Attachment uploaded.', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Upload error: {str(e)}', 'danger')
    finally:
        db.close()
    return redirect(url_for('purchase_orders.po_detail', po_id=po_id))


# -- API: Contracts for client (AJAX) --

@po_bp.route('/api/client/<int:client_id>/contracts')
@login_required
def api_client_contracts(client_id):
    db = get_session()
    try:
        client = db.query(Client).filter_by(id=client_id, organization_id=current_user.organization_id).first()
        if not client:
            return jsonify([]), 404
        contracts = db.query(Contract).filter_by(
            client_id=client_id, status=ContractStatus.active
        ).all()
        return jsonify([
            {'id': c.id, 'title': c.title or f'Contract #{c.id}'}
            for c in contracts
        ])
    finally:
        db.close()


# -- API: POs for client (AJAX, used in invoice form) --

@po_bp.route('/api/client/<int:client_id>/pos')
@login_required
def api_client_pos(client_id):
    db = get_session()
    try:
        client = db.query(Client).filter_by(id=client_id, organization_id=current_user.organization_id).first()
        if not client:
            return jsonify([]), 404
        pos = db.query(PurchaseOrder).filter_by(
            client_id=client_id, status=POStatus.active.value
        ).order_by(PurchaseOrder.issue_date.desc()).all()

        today = date.today()
        result = []
        for po in pos:
            if po.expiry_date and today > po.expiry_date:
                continue
            result.append({
                'id': po.id,
                'po_number': po.po_number,
                'amount_remaining': po.amount_remaining,
                'amount_authorized': float(po.amount_authorized or 0),
                'expiry_date': po.expiry_date.isoformat() if po.expiry_date else None,
                'department': po.department,
                'cost_code': po.cost_code,
                'display': (
                    f"{po.po_number} -- ${po.amount_remaining:,.2f} remaining"
                    + (f" (expires {po.expiry_date})" if po.expiry_date else "")
                ),
            })
        return jsonify(result)
    finally:
        db.close()


# -- API: PO selector for invoice form (with selector dict) --

@po_bp.route('/api/purchase-orders/client/<int:client_id>')
@login_required
def api_pos_selector(client_id):
    """JSON list of POs for the invoice form PO selector."""
    db = get_session()
    try:
        client = db.query(Client).filter_by(id=client_id, organization_id=current_user.organization_id).first()
        if not client:
            return jsonify([]), 404
        from web.utils.po_utils import get_active_pos_for_client
        include_all = request.args.get('include_all', 'false').lower() == 'true'

        if include_all:
            pos = db.query(PurchaseOrder).filter_by(client_id=client_id)\
                    .order_by(PurchaseOrder.created_at.desc()).all()
        else:
            pos = get_active_pos_for_client(db, client_id)

        return jsonify([po.to_selector_dict() for po in pos])
    finally:
        db.close()


# -- API: PO capacity check (real-time invoice form feedback) --

@po_bp.route('/api/purchase-orders/<int:po_id>/capacity', methods=['POST'])
@login_required
def api_po_capacity(po_id):
    """POST { amount, exclude_invoice_id } -> capacity check result."""
    from web.utils.po_utils import check_po_capacity
    from web.utils.validation import validate, POCapacitySchema
    db = get_session()
    try:
        po = db.query(PurchaseOrder).filter_by(id=po_id, organization_id=current_user.organization_id).first()
        if not po:
            return jsonify({'error': 'PO not found'}), 404

        data = request.get_json(force=True)
        obj, err = validate(POCapacitySchema, data)
        if err:
            return jsonify(err), 400

        result = check_po_capacity(db, po, obj.amount, exclude_invoice_id=obj.exclude_invoice_id)
        return jsonify(result)
    finally:
        db.close()
