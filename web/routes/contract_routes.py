"""Contract CRUD routes — List, Create, Edit, Detail, Status, Attachments."""

import os
from datetime import timezone, date, datetime, timedelta
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, abort, current_app, jsonify)
from flask_login import login_required, current_user
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from models.database import get_session
from models.contract import (Contract, ContractLineItem, ContractActivityLog,
                              ContractAttachment, ContractType, ContractStatus,
                              BillingFrequency, ServiceFrequency)
from models.sla import SLA, PriorityLevel
from models.client import Client, Property
from models.division import Division
from models.job import Job
from web.auth import role_required

contract_bp = Blueprint('contracts', __name__, url_prefix='/contracts')

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'png', 'jpg', 'jpeg', 'xlsx'}


def _get_divisions():
    """Fetch active divisions for the current user's org (for base template)."""
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


def _tpl_vars(**extra):
    """Common template variables for all contract routes."""
    base = dict(
        active_page='contracts',
        user=current_user,
        divisions=_get_divisions(),
    )
    base.update(extra)
    return base


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ─────────────────────────────────────────────────────────────────────────────
# LIST
# ─────────────────────────────────────────────────────────────────────────────

@contract_bp.route('/', methods=['GET'])
@login_required
def contract_list():
    db = get_session()
    try:
        org_id = current_user.organization_id
        q = db.query(Contract).filter_by(organization_id=org_id)

        # Filters
        status_filter   = request.args.get('status', '')
        client_filter   = request.args.get('client_id', '', type=str)
        division_filter = request.args.get('division_id', '', type=str)
        type_filter     = request.args.get('contract_type', '')
        expiring_filter = request.args.get('expiring_soon', '')
        search          = request.args.get('search', '').strip()

        if status_filter:
            q = q.filter(Contract.status == status_filter)
        if client_filter:
            q = q.filter(Contract.client_id == int(client_filter))
        if division_filter:
            q = q.filter(Contract.division_id == int(division_filter))
        if type_filter:
            q = q.filter(Contract.contract_type == type_filter)
        if expiring_filter:
            today = date.today()
            q = q.filter(
                Contract.status == ContractStatus.active,
                Contract.end_date.between(today, today + timedelta(days=30))
            )
        if search:
            q = q.filter(or_(
                Contract.title.ilike(f'%{search}%'),
                Contract.contract_number.ilike(f'%{search}%'),
            ))

        contracts = q.order_by(Contract.created_at.desc()).all()

        # Quick stats
        base_q = db.query(Contract).filter_by(organization_id=org_id)
        all_active = base_q.filter(Contract.status == ContractStatus.active).all()
        total_value = sum(c.value for c in all_active)
        today = date.today()
        expiring_30 = [c for c in all_active
                       if 0 <= (c.end_date - today).days <= 30]

        # SLA breaches this month
        month_start = today.replace(day=1)
        breached_jobs = db.query(Job).filter(
            Job.contract_id.isnot(None),
            or_(
                Job.sla_response_met == False,
                Job.sla_resolution_met == False
            )
        ).filter(Job.created_at >= month_start).count()

        clients = db.query(Client).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Client.company_name, Client.last_name).all()
        divs = db.query(Division).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Division.sort_order).all()

        return render_template('contracts/contract_list.html',
                               **_tpl_vars(
                                   contracts=contracts,
                                   clients=clients,
                                   all_divisions=divs,
                                   ContractStatus=ContractStatus,
                                   ContractType=ContractType,
                                   active_count=len(all_active),
                                   total_value=total_value,
                                   expiring_soon_count=len(expiring_30),
                                   breached_slas_month=breached_jobs,
                                   status_filter=status_filter,
                                   client_filter=client_filter,
                                   division_filter=division_filter,
                                   type_filter=type_filter,
                                   search=search,
                               ))
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# DETAIL
# ─────────────────────────────────────────────────────────────────────────────

@contract_bp.route('/<int:contract_id>', methods=['GET'])
@login_required
def contract_detail(contract_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        contract = db.query(Contract).filter_by(
            id=contract_id, organization_id=org_id
        ).first()
        if not contract:
            abort(404)

        # Auto-expire check
        _run_contract_checks(db, contract)

        jobs = db.query(Job).filter_by(contract_id=contract_id)\
                  .order_by(Job.created_at.desc()).all()

        # Financial summary
        from models.invoice import Invoice
        invoiced_total = 0
        try:
            if hasattr(Invoice, 'contract_id'):
                invoices = db.query(Invoice).filter_by(contract_id=contract_id).all()
                invoiced_total = sum(getattr(inv, 'total', 0) or 0 for inv in invoices)
        except Exception:
            invoiced_total = 0

        # SLA compliance
        contract_jobs_with_sla = [j for j in jobs if j.sla_id]
        if contract_jobs_with_sla:
            met = sum(1 for j in contract_jobs_with_sla if j.sla_resolution_met)
            sla_pct = round(met / len(contract_jobs_with_sla) * 100, 1)
        else:
            sla_pct = None

        return render_template('contracts/contract_detail.html',
                               **_tpl_vars(
                                   contract=contract,
                                   jobs=jobs,
                                   invoiced_total=invoiced_total,
                                   sla_pct=sla_pct,
                                   ContractStatus=ContractStatus,
                                   today=date.today(),
                               ))
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# CREATE
# ─────────────────────────────────────────────────────────────────────────────

@contract_bp.route('/new', methods=['GET', 'POST'])
@login_required
@role_required('owner', 'admin')
def contract_new():
    db = get_session()
    try:
        if request.method == 'POST':
            return _save_contract(db, None)

        org_id = current_user.organization_id
        clients = db.query(Client).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Client.company_name, Client.last_name).all()
        divs = db.query(Division).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Division.sort_order).all()
        slas = db.query(SLA).filter_by(is_active=True)\
                  .order_by(SLA.priority_level).all()

        return render_template('contracts/contract_form.html',
                               **_tpl_vars(
                                   contract=None,
                                   clients=clients,
                                   all_divisions=divs,
                                   slas=slas,
                                   properties=[],
                                   ContractType=ContractType,
                                   ContractStatus=ContractStatus,
                                   BillingFrequency=BillingFrequency,
                                   ServiceFrequency=ServiceFrequency,
                                   action='new',
                               ))
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# EDIT
# ─────────────────────────────────────────────────────────────────────────────

@contract_bp.route('/<int:contract_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('owner', 'admin')
def contract_edit(contract_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        contract = db.query(Contract).filter_by(
            id=contract_id, organization_id=org_id
        ).first()
        if not contract:
            abort(404)

        if request.method == 'POST':
            return _save_contract(db, contract)

        clients = db.query(Client).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Client.company_name, Client.last_name).all()
        divs = db.query(Division).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Division.sort_order).all()
        slas = db.query(SLA).filter_by(is_active=True)\
                  .order_by(SLA.priority_level).all()
        properties = db.query(Property)\
                       .filter_by(client_id=contract.client_id).all() \
                       if contract.client_id else []

        return render_template('contracts/contract_form.html',
                               **_tpl_vars(
                                   contract=contract,
                                   clients=clients,
                                   all_divisions=divs,
                                   slas=slas,
                                   properties=properties,
                                   ContractType=ContractType,
                                   ContractStatus=ContractStatus,
                                   BillingFrequency=BillingFrequency,
                                   ServiceFrequency=ServiceFrequency,
                                   action='edit',
                               ))
    finally:
        db.close()


def _save_contract(db, contract):
    """Shared save logic for new and edit."""
    is_new = contract is None
    user_id = current_user.id

    try:
        f = request.form

        if is_new:
            contract = Contract(
                organization_id = current_user.organization_id,
                contract_number = Contract.generate_contract_number(db),
                created_by      = user_id,
            )
            db.add(contract)

        contract.client_id             = int(f['client_id'])
        contract.division_id           = int(f['division_id']) if f.get('division_id') else None
        contract.title                 = f['title'].strip()
        contract.description           = f.get('description', '').strip() or None
        contract.contract_type         = ContractType(f['contract_type'])
        contract.status                = ContractStatus(f.get('status', 'draft'))
        contract.start_date            = datetime.strptime(f['start_date'], '%Y-%m-%d').date()
        contract.end_date              = datetime.strptime(f['end_date'], '%Y-%m-%d').date()
        contract.value                 = float(f.get('value', 0) or 0)
        contract.billing_frequency     = BillingFrequency(f['billing_frequency'])
        contract.auto_renew            = 'auto_renew' in f
        contract.renewal_terms         = f.get('renewal_terms', '').strip() or None
        contract.renewal_reminder_days = int(f.get('renewal_reminder_days', 30))
        contract.terms_and_conditions  = f.get('terms_and_conditions', '').strip() or None
        contract.internal_notes        = f.get('internal_notes', '').strip() or None
        contract.updated_by            = user_id

        # Properties (many-to-many)
        prop_ids = request.form.getlist('property_ids')
        if prop_ids:
            contract.properties = db.query(Property)\
                                    .filter(Property.id.in_(
                                        [int(p) for p in prop_ids])).all()
        else:
            contract.properties = []

        # SLAs (many-to-many)
        sla_ids = request.form.getlist('sla_ids')
        if sla_ids:
            contract.slas = db.query(SLA)\
                               .filter(SLA.id.in_([int(s) for s in sla_ids])).all()
        else:
            contract.slas = []

        db.flush()

        # Line items
        _save_line_items_from_form(db, contract, request.form)

        action_str = 'Contract created' if is_new else 'Contract updated'
        contract.log_activity(db, user_id, action_str,
                               f'Status: {contract.status.value}')
        db.commit()
        flash(f'Contract {contract.contract_number} saved successfully.', 'success')
        return redirect(url_for('contracts.contract_detail',
                                contract_id=contract.id))

    except Exception as e:
        db.rollback()
        flash(f'Error saving contract: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('contracts.contract_list'))


def _save_line_items_from_form(db, contract, form):
    """Parse multi-row line item fields from form submission."""
    service_types = form.getlist('li_service_type[]')
    if not service_types:
        return

    db.query(ContractLineItem).filter_by(contract_id=contract.id).delete()

    for i, stype in enumerate(service_types):
        if not stype.strip():
            continue

        def fget(key, default=''):
            vals = form.getlist(f'{key}[]')
            return vals[i] if i < len(vals) else default

        next_date_str = fget('li_next_scheduled_date')
        try:
            next_date = datetime.strptime(next_date_str, '%Y-%m-%d').date() \
                        if next_date_str else None
        except ValueError:
            next_date = None

        li = ContractLineItem(
            contract_id              = contract.id,
            service_type             = stype.strip(),
            description              = fget('li_description') or None,
            frequency                = ServiceFrequency(fget('li_frequency', 'annual')),
            quantity                 = float(fget('li_quantity', '1') or 1),
            unit_price               = float(fget('li_unit_price', '0') or 0),
            estimated_hours_per_visit= float(fget('li_estimated_hours', '') or 0) or None,
            next_scheduled_date      = next_date,
            is_included              = fget('li_is_included', '1') == '1',
            sort_order               = i,
        )
        db.add(li)


# ─────────────────────────────────────────────────────────────────────────────
# STATUS CHANGE
# ─────────────────────────────────────────────────────────────────────────────

@contract_bp.route('/<int:contract_id>/status', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def contract_status_change(contract_id):
    db = get_session()
    try:
        contract = db.query(Contract).filter_by(
            id=contract_id, organization_id=current_user.organization_id
        ).first()
        if not contract:
            abort(404)
        new_status = ContractStatus(request.form['status'])
        old_status = contract.status
        contract.status = new_status
        contract.log_activity(db, current_user.id,
                               f'Status changed: {old_status.value} -> {new_status.value}',
                               request.form.get('reason', ''))
        db.commit()

        if new_status.value == 'expired':
            try:
                from web.utils.notification_service import NotificationService
                NotificationService.notify('contract_expired', contract, triggered_by=current_user)
            except Exception:
                pass

        flash(f'Contract status updated to {new_status.value}.', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Error: {str(e)}', 'danger')
    finally:
        db.close()
    return redirect(url_for('contracts.contract_detail', contract_id=contract_id))


# ─────────────────────────────────────────────────────────────────────────────
# ATTACHMENTS
# ─────────────────────────────────────────────────────────────────────────────

@contract_bp.route('/<int:contract_id>/attachments', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def contract_upload(contract_id):
    db = get_session()
    try:
        contract = db.query(Contract).filter_by(
            id=contract_id, organization_id=current_user.organization_id
        ).first()
        if not contract:
            abort(404)

        if 'file' not in request.files:
            flash('No file selected.', 'warning')
            return redirect(url_for('contracts.contract_detail',
                                    contract_id=contract_id))

        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename):
            flash('Invalid file type.', 'danger')
            return redirect(url_for('contracts.contract_detail',
                                    contract_id=contract_id))

        upload_dir = os.path.join(current_app.root_path, 'uploads', 'contracts',
                                  str(contract_id))
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = secure_filename(file.filename)
        stored_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{safe_name}"
        file.save(os.path.join(upload_dir, stored_name))

        att = ContractAttachment(
            contract_id   = contract_id,
            filename      = stored_name,
            original_name = safe_name,
            file_size     = os.path.getsize(os.path.join(upload_dir, stored_name)),
            mime_type     = file.content_type,
            uploaded_by   = current_user.id,
        )
        db.add(att)
        db.commit()
        flash('Attachment uploaded successfully.', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Upload error: {str(e)}', 'danger')
    finally:
        db.close()
    return redirect(url_for('contracts.contract_detail',
                            contract_id=contract_id, _anchor='attachments'))


@contract_bp.route('/<int:contract_id>/attachments/<int:att_id>/delete',
                   methods=['POST'])
@login_required
@role_required('owner', 'admin')
def contract_attachment_delete(contract_id, att_id):
    db = get_session()
    try:
        att = db.query(ContractAttachment).filter_by(
            id=att_id, contract_id=contract_id
        ).first()
        if att:
            file_path = os.path.join(current_app.root_path, 'uploads', 'contracts',
                                     str(contract_id), att.filename)
            if os.path.exists(file_path):
                os.remove(file_path)
            db.delete(att)
            db.commit()
            flash('Attachment removed.', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Error: {str(e)}', 'danger')
    finally:
        db.close()
    return redirect(url_for('contracts.contract_detail',
                            contract_id=contract_id, _anchor='attachments'))


# ─────────────────────────────────────────────────────────────────────────────
# AJAX HELPERS
# ─────────────────────────────────────────────────────────────────────────────

@contract_bp.route('/api/client-properties/<int:client_id>')
@login_required
def api_client_properties(client_id):
    """Return JSON list of properties for a client (dynamic form population)."""
    db = get_session()
    try:
        client = db.query(Client).filter_by(id=client_id, organization_id=current_user.organization_id).first()
        if not client:
            return jsonify([]), 404
        props = db.query(Property).filter_by(client_id=client_id).all()
        return jsonify([{
            'id': p.id,
            'address': p.display_address if hasattr(p, 'display_address') else p.address,
            'name': p.name or p.address or f'Property {p.id}',
        } for p in props])
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# AUTOMATED CHECKS
# ─────────────────────────────────────────────────────────────────────────────

def _run_contract_checks(db, contract):
    """Auto-expire contracts past their end date."""
    today = date.today()
    changed = False

    if (contract.status == ContractStatus.active and
            contract.end_date < today):
        contract.status = ContractStatus.expired
        contract.log_activity(db, None, 'Auto-expired',
                               f'Contract passed end date {contract.end_date}')
        changed = True

    if changed:
        try:
            db.commit()
        except Exception:
            db.rollback()
