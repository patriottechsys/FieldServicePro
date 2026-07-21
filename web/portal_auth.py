"""Portal authentication: login, logout, password reset, invitation, decorators.

Uses Flask session with 'portal_*' keys, separate from Flask-Login (internal users).
"""
import time
from collections import defaultdict
from functools import wraps
from datetime import timezone, datetime, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    session, g, current_app, abort,
)

from models.database import get_session
from models.portal_user import PortalUser
from models.portal_settings import PortalSettings

# ── IP-based rate limiting (in-memory, no extra dependencies) ─────────────
_login_attempts = defaultdict(list)


def check_ip_rate_limit(ip, max_attempts=10, window_seconds=900):
    """Check if an IP has exceeded login attempt limits. Returns True if OK."""
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < window_seconds]
    if len(_login_attempts[ip]) >= max_attempts:
        return False
    _login_attempts[ip].append(now)
    return True

portal_auth_bp = Blueprint('portal_auth', __name__, url_prefix='/portal')


# ── Session Management ────────────────────────────────────────────────────

def get_current_portal_user():
    """Load portal user from session. Returns None if not logged in or timed out."""
    if hasattr(g, '_portal_user'):
        return g._portal_user

    portal_user_id = session.get('portal_user_id')
    if not portal_user_id:
        g._portal_user = None
        return None

    db = get_session()
    try:
        user = db.query(PortalUser).filter_by(id=portal_user_id, is_active=True).first()
        if not user:
            g._portal_user = None
            return None

        # Check session timeout
        last_activity = session.get('portal_last_activity')
        if last_activity:
            settings = PortalSettings.get_settings(db)
            timeout = timedelta(minutes=settings.session_timeout_minutes)
            try:
                last_dt = datetime.fromisoformat(last_activity)
            except (ValueError, TypeError):
                last_dt = datetime.now(timezone.utc)
            if datetime.now(timezone.utc) - last_dt > timeout:
                clear_portal_session()
                g._portal_user = None
                return None

        session['portal_last_activity'] = datetime.now(timezone.utc).isoformat()
        g._portal_user = user
        return user
    finally:
        db.close()


def set_portal_session(user):
    """Set portal session after successful login."""
    session['portal_user_id'] = user.id
    session['portal_client_id'] = user.client_id
    session['portal_user_role'] = user.role
    session['portal_last_activity'] = datetime.now(timezone.utc).isoformat()
    session.permanent = True


def clear_portal_session():
    """Remove all portal session keys."""
    keys_to_remove = [k for k in list(session.keys()) if k.startswith('portal_')]
    for key in keys_to_remove:
        session.pop(key, None)


# ── Decorators ─────────────────────────────────────────────────────────────

def portal_login_required(f):
    """Decorator: require portal user login."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        db = get_session()
        try:
            settings = PortalSettings.get_settings(db)
            if not settings.portal_enabled:
                flash('The client portal is currently disabled.', 'warning')
                return redirect(url_for('portal_auth.portal_login'))
            g.portal_settings = settings
        finally:
            db.close()

        user = get_current_portal_user()
        if not user:
            flash('Please log in to access the portal.', 'info')
            return redirect(url_for('portal_auth.portal_login', next=request.url))
        g.portal_user = user
        g.portal_client_id = user.client_id
        return f(*args, **kwargs)
    return decorated_function


def portal_role_required(*allowed_roles):
    """Decorator: require specific portal user roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = g.get('portal_user')
            if not user or user.role not in allowed_roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('portal.portal_dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def portal_permission_required(permission_method):
    """Decorator: check a specific permission method on portal user.
    Usage: @portal_permission_required('can_view_invoices')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = g.get('portal_user')
            if not user or not getattr(user, permission_method, lambda: False)():
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('portal.portal_dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ── Query Helpers ──────────────────────────────────────────────────────────

def portal_filter_query(query, model_class, client_id_field='client_id'):
    """Apply mandatory client_id scoping to any query."""
    user = g.portal_user
    return query.filter(getattr(model_class, client_id_field) == user.client_id)


def get_accessible_property_ids():
    """Return property IDs the current portal user can access, or None for all."""
    user = g.portal_user
    return user.get_property_ids()


def portal_filter_by_property(query, property_id_field):
    """Apply property-level restrictions if user has accessible_properties set."""
    prop_ids = get_accessible_property_ids()
    if prop_ids is not None:
        query = query.filter(property_id_field.in_(prop_ids))
    return query


# ── Password Validation ───────────────────────────────────────────────────

def validate_password(password):
    """Validate password meets requirements. Returns (is_valid, error_message)."""
    if len(password) < 8:
        return False, 'Password must be at least 8 characters long.'
    has_letter = any(c.isalpha() for c in password)
    has_number = any(c.isdigit() for c in password)
    if not has_letter or not has_number:
        return False, 'Password must contain at least one letter and one number.'
    return True, None


# ── Routes ─────────────────────────────────────────────────────────────────

@portal_auth_bp.route('/login', methods=['GET', 'POST'])
def portal_login():
    """Portal login page."""
    if get_current_portal_user():
        return redirect(url_for('portal.portal_dashboard'))

    if request.method == 'POST':
        # IP-based rate limiting
        if not check_ip_rate_limit(request.remote_addr):
            flash('Too many login attempts. Please try again later.', 'danger')
            return render_template('portal/auth/login.html')

        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        db = get_session()
        try:
            user = db.query(PortalUser).filter_by(email=email).first()

            if not user:
                flash('Invalid email or password.', 'danger')
                return render_template('portal/auth/login.html')

            if not user.is_active:
                flash('Your account has been deactivated. Please contact your service provider.', 'danger')
                return render_template('portal/auth/login.html')

            if user.is_locked:
                remaining = (user.locked_until - datetime.now(timezone.utc)).seconds // 60 + 1
                flash(f'Account locked due to too many failed attempts. Try again in {remaining} minutes.', 'danger')
                return render_template('portal/auth/login.html')

            if not user.check_password(password):
                user.record_failed_login()
                db.commit()
                flash('Invalid email or password.', 'danger')
                return render_template('portal/auth/login.html')

            settings = PortalSettings.get_settings(db)
            if not settings.portal_enabled:
                flash('The client portal is currently disabled.', 'warning')
                return render_template('portal/auth/login.html')

            # Success
            user.record_login()
            db.commit()
            set_portal_session(user)

            next_url = request.args.get('next')
            if next_url and next_url.startswith('/portal/'):
                return redirect(next_url)
            return redirect(url_for('portal.portal_dashboard'))
        finally:
            db.close()

    return render_template('portal/auth/login.html')


@portal_auth_bp.route('/logout')
def portal_logout():
    """Portal logout."""
    clear_portal_session()
    flash('You have been logged out.', 'info')
    return redirect(url_for('portal_auth.portal_login'))


@portal_auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def portal_forgot_password():
    """Portal password reset request."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        db = get_session()
        try:
            user = db.query(PortalUser).filter_by(email=email, is_active=True).first()
            if user:
                token = user.generate_reset_token()
                db.commit()
                # Email sending would happen here
                try:
                    from web.utils.portal_email import send_password_reset_email
                    send_password_reset_email(user, token)
                except Exception as e:
                    current_app.logger.error(f"Failed to send reset email: {e}")
        finally:
            db.close()

        # Always show success to avoid email enumeration
        flash('If an account exists with that email, a password reset link has been sent.', 'info')
        return redirect(url_for('portal_auth.portal_login'))

    return render_template('portal/auth/forgot_password.html')


@portal_auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def portal_reset_password(token):
    """Portal password reset with token."""
    db = get_session()
    try:
        user = db.query(PortalUser).filter_by(password_reset_token=token).first()
        if not user or not user.validate_reset_token(token):
            flash('This password reset link is invalid or has expired.', 'danger')
            return redirect(url_for('portal_auth.portal_forgot_password'))

        if request.method == 'POST':
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')

            if password != confirm:
                flash('Passwords do not match.', 'danger')
                return render_template('portal/auth/reset_password.html', token=token)

            is_valid, error = validate_password(password)
            if not is_valid:
                flash(error, 'danger')
                return render_template('portal/auth/reset_password.html', token=token)

            user.set_password(password)
            user.password_reset_token = None
            user.password_reset_expiry = None
            db.commit()

            flash('Your password has been set. You can now log in.', 'success')
            return redirect(url_for('portal_auth.portal_login'))

        return render_template('portal/auth/reset_password.html', token=token)
    finally:
        db.close()


@portal_auth_bp.route('/setup-account/<token>', methods=['GET', 'POST'])
def portal_setup_account(token):
    """Initial account setup via invitation link."""
    db = get_session()
    try:
        user = db.query(PortalUser).filter_by(invitation_token=token).first()
        if not user or not user.validate_invitation_token(token):
            flash('This invitation link is invalid or has expired.', 'danger')
            return redirect(url_for('portal_auth.portal_login'))

        if user.invitation_accepted:
            flash('This invitation has already been used. Please log in.', 'info')
            return redirect(url_for('portal_auth.portal_login'))

        if request.method == 'POST':
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')

            if password != confirm:
                flash('Passwords do not match.', 'danger')
                return render_template('portal/auth/setup_account.html', token=token, user=user)

            is_valid, error = validate_password(password)
            if not is_valid:
                flash(error, 'danger')
                return render_template('portal/auth/setup_account.html', token=token, user=user)

            user.set_password(password)
            user.invitation_accepted = True
            user.invitation_token = None
            user.invitation_expiry = None
            db.commit()

            flash('Your account has been set up. Please log in.', 'success')
            return redirect(url_for('portal_auth.portal_login'))

        return render_template('portal/auth/setup_account.html', token=token, user=user)
    finally:
        db.close()
