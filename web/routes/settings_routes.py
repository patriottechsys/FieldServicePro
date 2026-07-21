"""Settings routes — organization settings management."""

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from models.database import get_session
from models.user import Organization
from models.division import Division
from models.technician import Technician
from web.auth import role_required

settings_bp = Blueprint('settings_bp', __name__)


@settings_bp.route('/settings')
@login_required
@role_required('owner', 'admin', 'dispatcher')
def settings_page():
    db = get_session()
    try:
        org = db.query(Organization).filter_by(id=current_user.organization_id).first()
        divisions = db.query(Division).filter_by(organization_id=current_user.organization_id).order_by(Division.sort_order).all()
        technicians = db.query(Technician).filter_by(organization_id=current_user.organization_id).all()

        from models.settings import OrganizationSettings
        org_settings = OrganizationSettings.get_or_create(db, current_user.organization_id)

        from web.utils.helpers import get_divisions

        tech_list = []
        div_map = {d.id: d.to_dict() for d in divisions}
        for t in technicians:
            td = t.to_dict()
            td['division_name'] = div_map.get(t.division_id, {}).get('name', '—')
            tech_list.append(td)

        return render_template('settings.html',
            active_page='settings',
            user=current_user,
            divisions=get_divisions(),
            organization=org.to_dict() if org else {},
            all_divisions=[d.to_dict() for d in divisions],
            technicians=tech_list,
            org_settings=org_settings,
        )
    finally:
        db.close()


@settings_bp.route('/settings/approvals', methods=['POST'])
@login_required
def save_approval_settings():
    from models.settings import OrganizationSettings
    if current_user.role not in ('owner', 'admin'):
        abort(403)

    db = get_session()
    try:
        org_id = current_user.organization_id
        settings = OrganizationSettings.get_or_create(db, org_id)
        settings.invoice_approval_enabled = 'invoice_approval_enabled' in request.form
        threshold = request.form.get('invoice_approval_threshold', '').strip()
        settings.invoice_approval_threshold = float(threshold) if threshold else None
        settings.invoice_approval_roles = request.form.get('invoice_approval_roles', 'owner,admin')
        settings.updated_by = current_user.id
        db.commit()
        flash('Approval settings saved.', 'success')
    finally:
        db.close()
    return redirect(url_for('settings_page'))


@settings_bp.route('/settings/warranty', methods=['POST'])
@login_required
def save_warranty_settings():
    from models.settings import OrganizationSettings
    if current_user.role not in ('owner', 'admin'):
        abort(403)
    db = get_session()
    try:
        org_id = current_user.organization_id
        settings = OrganizationSettings.get_or_create(db, org_id)
        settings.default_labor_warranty_months = int(request.form.get('default_labor_warranty_months', 12))
        settings.default_parts_warranty_months = int(request.form.get('default_parts_warranty_months', 12))
        mcv = request.form.get('default_max_claim_value', '').strip()
        settings.default_max_claim_value = float(mcv) if mcv else None
        settings.callback_lookback_days = int(request.form.get('callback_lookback_days', 90))
        settings.callback_rate_threshold = float(request.form.get('callback_rate_threshold', 5.0))
        settings.auto_create_warranty_on_completion = 'auto_create_warranty_on_completion' in request.form
        settings.default_warranty_terms = request.form.get('default_warranty_terms', '').strip() or None
        db.commit()
        flash('Warranty settings saved.', 'success')
    finally:
        db.close()
    return redirect(url_for('settings_page'))


@settings_bp.route('/settings/communications', methods=['POST'])
@login_required
def save_comm_settings():
    from models.settings import OrganizationSettings
    if current_user.role not in ('owner', 'admin'):
        abort(403)
    db = get_session()
    try:
        org_id = current_user.organization_id
        settings = OrganizationSettings.get_or_create(db, org_id)
        settings.inactive_client_alert_days = int(request.form.get('inactive_client_alert_days', 7))
        settings.default_follow_up_days = int(request.form.get('default_follow_up_days', 3))
        settings.require_comm_log_on_status_change = 'require_comm_log_on_status_change' in request.form
        db.commit()
        flash('Communication settings saved.', 'success')
    finally:
        db.close()
    return redirect(url_for('settings_page'))


@settings_bp.route('/settings/expenses', methods=['POST'])
@login_required
def save_expense_settings():
    from models.settings import OrganizationSettings
    if current_user.role not in ('owner', 'admin'):
        abort(403)
    db = get_session()
    try:
        org_id = current_user.organization_id
        settings = OrganizationSettings.get_or_create(db, org_id)
        for field in ['expense_approval_threshold', 'expense_receipt_required_threshold', 'mileage_rate', 'default_expense_markup']:
            val = request.form.get(field, '').strip()
            if val:
                setattr(settings, field, float(val))
            else:
                setattr(settings, field, None)
        settings.expense_approval_roles = request.form.get('expense_approval_roles', 'owner,admin').strip()
        db.commit()
        flash('Expense settings saved.', 'success')
    finally:
        db.close()
    return redirect(url_for('settings_page'))


@settings_bp.route('/settings/notifications/global', methods=['POST'])
@login_required
def save_notification_settings():
    from models.settings import OrganizationSettings
    if current_user.role not in ('owner', 'admin'):
        abort(403)
    db = get_session()
    try:
        settings = OrganizationSettings.get_or_create(db, current_user.organization_id)
        for field in ('notifications_enabled', 'client_notifications_enabled', 'sms_enabled'):
            setattr(settings, field, request.form.get(field) == '1')
        for field in ('notification_polling_interval', 'appointment_reminder_hours'):
            val = request.form.get(field, '').strip()
            if val:
                setattr(settings, field, int(val))
        for field in ('email_from_name', 'email_from_address', 'email_reply_to',
                      'sms_provider', 'sms_api_key', 'sms_from_number', 'invoice_reminder_days'):
            setattr(settings, field, request.form.get(field, '').strip() or None)
        db.commit()
        flash('Notification settings saved.', 'success')
    finally:
        db.close()
    return redirect(url_for('settings_page'))
