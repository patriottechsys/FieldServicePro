"""Internal admin routes for managing portal users, portal settings, and notifications."""
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from sqlalchemy import desc, or_
from models.database import get_session
from models.portal_user import PortalUser
from models.portal_settings import PortalSettings
from models.portal_notification import PortalNotification
from models.client import Client, Property
from models.division import Division
from web.auth import role_required

portal_admin_bp = Blueprint('portal_admin', __name__, url_prefix='/admin/portal')


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  PORTAL USER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@portal_admin_bp.route('/clients/<int:client_id>/portal-users')
@login_required
@role_required('owner', 'admin')
def list_portal_users(client_id):
    db = get_session()
    try:
        client = db.query(Client).filter_by(id=client_id).first()
        if not client:
            flash('Client not found.', 'error')
            return redirect(url_for('clients_bp.clients_page'))

        portal_users = db.query(PortalUser).filter_by(client_id=client_id).order_by(
            PortalUser.created_at
        ).all()

        return render_template('portal_admin/portal_users_tab.html',
            active_page='clients', user=current_user, divisions=_get_divisions(),
            client=client, portal_users=portal_users)
    finally:
        db.close()


@portal_admin_bp.route('/clients/<int:client_id>/portal-users/new', methods=['GET', 'POST'])
@login_required
@role_required('owner', 'admin')
def create_portal_user(client_id):
    db = get_session()
    try:
        client = db.query(Client).filter_by(id=client_id).first()
        if not client:
            flash('Client not found.', 'error')
            return redirect(url_for('clients_bp.clients_page'))

        properties = db.query(Property).filter_by(client_id=client_id, is_active=True).all()

        if request.method == 'POST':
            f = request.form
            email = f.get('email', '').strip().lower()
            first_name = f.get('first_name', '').strip()
            last_name = f.get('last_name', '').strip()
            phone = f.get('phone', '').strip()
            role = f.get('role', 'standard')
            selected_properties = f.getlist('properties')

            if not email or not first_name or not last_name:
                flash('Email, first name, and last name are required.', 'danger')
                return render_template('portal_admin/portal_user_form.html',
                    active_page='clients', user=current_user, divisions=_get_divisions(),
                    client=client, properties=properties, mode='create')

            if db.query(PortalUser).filter_by(email=email).first():
                flash('A portal user with this email already exists.', 'danger')
                return render_template('portal_admin/portal_user_form.html',
                    active_page='clients', user=current_user, divisions=_get_divisions(),
                    client=client, properties=properties, mode='create')

            if role not in PortalUser.VALID_ROLES:
                flash('Invalid role.', 'danger')
                return render_template('portal_admin/portal_user_form.html',
                    active_page='clients', user=current_user, divisions=_get_divisions(),
                    client=client, properties=properties, mode='create')

            portal_user = PortalUser(
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone or None,
                client_id=client_id,
                role=role,
                created_by=current_user.id,
            )

            # Property restrictions
            if selected_properties:
                for pid in selected_properties:
                    prop = db.query(Property).filter_by(id=int(pid), client_id=client_id).first()
                    if prop:
                        portal_user.accessible_properties.append(prop)

            db.add(portal_user)
            db.flush()

            token = portal_user.generate_invitation_token()
            db.commit()

            # Send welcome email
            try:
                from web.utils.portal_email import send_welcome_email
                send_welcome_email(portal_user, token)
                flash(f'Portal user {email} created and welcome email sent.', 'success')
            except Exception as e:
                current_app.logger.error(f"Failed to send welcome email: {e}")
                flash(f'Portal user {email} created but welcome email failed to send.', 'warning')

            return redirect(url_for('portal_admin.list_portal_users', client_id=client_id))

        return render_template('portal_admin/portal_user_form.html',
            active_page='clients', user=current_user, divisions=_get_divisions(),
            client=client, properties=properties, mode='create')
    finally:
        db.close()


@portal_admin_bp.route('/portal-users/<int:user_id>/toggle', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def toggle_portal_user(user_id):
    db = get_session()
    try:
        portal_user = db.query(PortalUser).filter_by(id=user_id).first()
        if not portal_user:
            flash('Portal user not found.', 'error')
            return redirect(url_for('clients_bp.clients_page'))

        portal_user.is_active = not portal_user.is_active
        db.commit()
        status = 'activated' if portal_user.is_active else 'deactivated'
        flash(f'Portal user {portal_user.email} has been {status}.', 'success')
        return redirect(url_for('portal_admin.list_portal_users', client_id=portal_user.client_id))
    finally:
        db.close()


@portal_admin_bp.route('/portal-users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def reset_portal_user_password(user_id):
    db = get_session()
    try:
        portal_user = db.query(PortalUser).filter_by(id=user_id).first()
        if not portal_user:
            flash('Portal user not found.', 'error')
            return redirect(url_for('clients_bp.clients_page'))

        token = portal_user.generate_reset_token()
        db.commit()

        try:
            from web.utils.portal_email import send_password_reset_email
            send_password_reset_email(portal_user, token)
            flash(f'Password reset email sent to {portal_user.email}.', 'success')
        except Exception as e:
            current_app.logger.error(f"Failed to send reset email: {e}")
            flash('Failed to send reset email.', 'danger')

        return redirect(url_for('portal_admin.list_portal_users', client_id=portal_user.client_id))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  PORTAL SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

@portal_admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@role_required('owner', 'admin')
def portal_settings_page():
    db = get_session()
    try:
        settings = PortalSettings.get_settings(db)

        if request.method == 'POST':
            f = request.form
            settings.portal_enabled = f.get('portal_enabled') == 'on'
            settings.welcome_message = f.get('welcome_message', '').strip() or None
            settings.payment_instructions = f.get('payment_instructions', '').strip() or None
            settings.company_contact_info = f.get('company_contact_info', '').strip() or None
            settings.session_timeout_minutes = int(f.get('session_timeout_minutes', 30))
            settings.allow_service_requests = f.get('allow_service_requests') == 'on'
            settings.allow_quote_approval = f.get('allow_quote_approval') == 'on'
            settings.allow_change_order_approval = f.get('allow_change_order_approval') == 'on'
            settings.auto_convert_approved_quotes = f.get('auto_convert_approved_quotes') == 'on'
            settings.email_on_service_request = f.get('email_on_service_request') == 'on'
            settings.email_on_quote_approval = f.get('email_on_quote_approval') == 'on'
            settings.email_on_co_approval = f.get('email_on_co_approval') == 'on'
            settings.email_on_portal_message = f.get('email_on_portal_message') == 'on'
            settings.email_on_job_status_change = f.get('email_on_job_status_change') == 'on'
            settings.email_on_invoice_issued = f.get('email_on_invoice_issued') == 'on'

            db.commit()
            flash('Portal settings updated.', 'success')
            return redirect(url_for('portal_admin.portal_settings_page'))

        return render_template('settings/portal_settings.html',
            active_page='settings', user=current_user, divisions=_get_divisions(),
            settings=settings)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
#  NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════

@portal_admin_bp.route('/notifications')
@login_required
def portal_notifications():
    db = get_session()
    try:
        user_role = current_user.role

        query = db.query(PortalNotification).filter_by(target_type='internal')
        if user_role not in ('owner', 'admin'):
            query = query.filter(
                or_(
                    PortalNotification.target_role == user_role,
                    PortalNotification.target_role == None
                )
            )

        notifications_list = query.order_by(desc(PortalNotification.created_at)).limit(50).all()

        return render_template('portal_admin/notifications.html',
            active_page='notifications', user=current_user, divisions=_get_divisions(),
            notifications=notifications_list)
    finally:
        db.close()


@portal_admin_bp.route('/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notif_id):
    db = get_session()
    try:
        notif = db.query(PortalNotification).filter_by(id=notif_id).first()
        if not notif:
            return redirect(url_for('portal_admin.portal_notifications'))
        notif.is_read = True
        db.commit()
        if notif.link:
            return redirect(notif.link)
        return redirect(url_for('portal_admin.portal_notifications'))
    finally:
        db.close()


@portal_admin_bp.route('/api/notifications/count')
@login_required
def notification_count():
    db = get_session()
    try:
        user_role = current_user.role
        query = db.query(PortalNotification).filter_by(target_type='internal', is_read=False)
        if user_role not in ('owner', 'admin'):
            query = query.filter(
                or_(
                    PortalNotification.target_role == user_role,
                    PortalNotification.target_role == None
                )
            )
        count = query.count()
        return jsonify({'count': count})
    finally:
        db.close()
