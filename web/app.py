"""FieldServicePro — Main Flask Application."""

import os
import sys
import logging
from datetime import datetime, date, timezone, timedelta
from sqlalchemy import func, case, text
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, stream_with_context, session, g, abort, send_from_directory
from flask_login import login_required, current_user
from flask_cors import CORS
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
# Try multiple paths to find .env (handles different working directories)
for _candidate in [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'),
    os.path.join(os.getcwd(), '.env'),
]:
    if os.path.exists(_candidate):
        load_dotenv(_candidate)
        break

from models import (
    get_session, init_db,
    Organization, Division,
    Client, Property,
    Job,
    Quote,
    Invoice,
    Technician,
    SLA,
    Contract,
    ContractStatus,
)
from web.auth import auth_bp, login_manager
from web.routes.sla_routes import sla_bp
from web.routes.contract_routes import contract_bp
from web.cli_commands import automation_cli, recurring_cli, warranty_cli, notif_cli, project_mgmt_cli
from web.routes.po_routes import po_bp
from web.routes.phase_routes import phases_bp
from web.routes.change_order_routes import change_orders_bp
from web.routes.document_routes import documents_bp
from web.routes.permit_routes import permits_bp
from web.routes.insurance_routes import insurance_bp
from web.routes.certification_routes import certifications_bp
from web.routes.checklist_routes import checklists_bp
from web.routes.lien_waiver_routes import lien_waivers_bp
from web.portal_auth import portal_auth_bp
from web.routes.portal_routes import portal_bp
from web.routes.portal_admin_routes import portal_admin_bp
from web.routes.request_routes import requests_bp
from web.routes.payment_routes import payments_bp
from web.routes.schedule_routes import schedule_api_bp
from web.routes.equipment_routes import equipment_bp
from web.routes.project_routes import projects_bp
from web.routes.time_tracking_routes import time_tracking_bp
from web.routes.parts_routes import parts_bp
from web.routes.inventory_routes import inventory_bp
from web.routes.transfer_routes import transfers_bp
from web.routes.materials_routes import materials_bp
from web.routes.truck_stock_routes import truck_bp
from web.routes.parts_report_routes import parts_reports_bp
from web.routes.recurring_routes import recurring_bp
from web.routes.warranty_routes import warranty_bp
from web.routes.callback_routes import callback_bp
from web.routes.warranty_report_routes import warranty_reports_bp
from web.routes.communication_routes import communications_bp
from web.routes.comm_template_routes import comm_templates_bp
from web.routes.comm_report_routes import comm_reports_bp
from web.routes.expense_routes import expense_bp
from web.routes.notification_routes import notifications_bp
from web.routes.vehicle_routes import vehicle_bp
from web.routes.payroll_routes import payroll_bp
from web.routes.rfi_routes import rfi_bp
from web.routes.submittal_routes import submittal_bp
from web.routes.punch_list_routes import punch_list_bp
from web.routes.daily_log_routes import daily_log_bp
from web.routes.reports_routes import reports_bp
from web.routes.vendor_routes import vendor_bp
from web.routes.supplier_po_routes import supplier_po_bp
from web.routes.mobile import mobile_bp
from web.routes.booking_routes import booking_bp
from web.routes.feedback_routes import feedback_bp
from web.routes.advanced_reports_routes import advanced_reports_bp
from web.routes.clients_routes import clients_bp
from web.routes.invoices_routes import invoices_bp

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

# ---------- App factory ----------
IS_PRODUCTION = os.environ.get('FLASK_ENV') == 'production'

app = Flask(__name__)
SECRET_KEY = os.environ.get('SECRET_KEY')
if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY env var is required in production. "
        "Set it in the Render dashboard before deploying."
    )
app.secret_key = SECRET_KEY or 'fsp-dev-secret-key-change-in-prod'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = IS_PRODUCTION

# Belt-and-suspenders: never expose the Werkzeug debugger in production,
# even if a stray FLASK_DEBUG env var or future code change tries to enable it.
if IS_PRODUCTION:
    app.config['DEBUG'] = False
    app.config['PROPAGATE_EXCEPTIONS'] = False
    app.config['TRAP_HTTP_EXCEPTIONS'] = False

# File upload config
app.config['UPLOAD_FOLDER'] = os.environ.get(
    'UPLOAD_FOLDER', os.path.join(app.instance_path, 'uploads'))
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25MB

# Email config (Flask-Mail, optional — portal emails degrade gracefully if unconfigured)
app.config.setdefault('MAIL_SERVER', os.environ.get('MAIL_SERVER', 'localhost'))
app.config.setdefault('MAIL_PORT', int(os.environ.get('MAIL_PORT', 587)))
app.config.setdefault('MAIL_USE_TLS', os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true')
app.config.setdefault('MAIL_USERNAME', os.environ.get('MAIL_USERNAME'))
app.config.setdefault('MAIL_PASSWORD', os.environ.get('MAIL_PASSWORD'))
app.config.setdefault('MAIL_DEFAULT_SENDER', os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@fieldservicepro.com'))
app.config.setdefault('MAIL_USE_SSL', os.environ.get('MAIL_USE_SSL', 'false').lower() == 'true')

# Initialize Flask-Mail (optional — degrades gracefully)
try:
    from flask_mail import Mail
    mail = Mail(app)
except ImportError:
    mail = None
    logger.info("flask-mail not installed — email features will use console fallback")

# Security headers via Talisman (HTTPS redirect, CSP, HSTS)
csp = {
    'default-src': "'self'",
    'script-src': ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net"],
    'style-src': ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://fonts.googleapis.com"],
    'font-src': ["'self'", "https://cdn.jsdelivr.net", "https://fonts.gstatic.com"],
    'img-src': ["'self'", "data:"],
    'connect-src': "'self'",
    'frame-ancestors': "'self'",
    'form-action': "'self'",
    'base-uri': "'self'",
}
Talisman(
    app,
    force_https=IS_PRODUCTION,
    content_security_policy=csp,
    session_cookie_secure=IS_PRODUCTION,
)

CORS(app, resources={r"/api/*": {"origins": "*" if not IS_PRODUCTION else []}})
login_manager.init_app(app)
app.register_blueprint(auth_bp)
app.register_blueprint(sla_bp)
app.register_blueprint(contract_bp)
app.register_blueprint(automation_cli)
app.register_blueprint(recurring_cli)
app.register_blueprint(notif_cli)
app.register_blueprint(project_mgmt_cli)
app.register_blueprint(warranty_cli)
app.register_blueprint(po_bp)
app.register_blueprint(phases_bp)
app.register_blueprint(change_orders_bp)
app.register_blueprint(documents_bp)
app.register_blueprint(permits_bp)
app.register_blueprint(insurance_bp)
app.register_blueprint(certifications_bp)
app.register_blueprint(checklists_bp)
app.register_blueprint(lien_waivers_bp)
app.register_blueprint(portal_auth_bp)
app.register_blueprint(portal_bp)
app.register_blueprint(portal_admin_bp)
app.register_blueprint(requests_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(schedule_api_bp)
app.register_blueprint(equipment_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(time_tracking_bp)
app.register_blueprint(parts_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(transfers_bp)
app.register_blueprint(materials_bp)
app.register_blueprint(truck_bp)
app.register_blueprint(parts_reports_bp)
app.register_blueprint(recurring_bp)
app.register_blueprint(warranty_bp)
app.register_blueprint(callback_bp)
app.register_blueprint(warranty_reports_bp)
app.register_blueprint(communications_bp)
app.register_blueprint(comm_templates_bp)
app.register_blueprint(comm_reports_bp)
app.register_blueprint(expense_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(vehicle_bp)
app.register_blueprint(payroll_bp)
app.register_blueprint(rfi_bp)
app.register_blueprint(submittal_bp)
app.register_blueprint(punch_list_bp)
app.register_blueprint(daily_log_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(vendor_bp)
app.register_blueprint(supplier_po_bp)
app.register_blueprint(mobile_bp)
app.register_blueprint(booking_bp)
app.register_blueprint(feedback_bp)
app.register_blueprint(advanced_reports_bp)
from web.routes.settings_routes import settings_bp
app.register_blueprint(settings_bp)
from web.routes.quotes_routes import quotes_bp
app.register_blueprint(quotes_bp)
from web.routes.jobs_routes import jobs_bp
app.register_blueprint(jobs_bp)
app.register_blueprint(clients_bp)
app.register_blueprint(invoices_bp)

# CSRF protection — exempt /api/* routes (they require login + accept JSON only)
csrf = CSRFProtect(app)
with app.app_context():
    for endpoint_name, view_fn in app.view_functions.items():
        # Get the first URL rule for this endpoint
        for rule in app.url_map.iter_rules():
            if rule.endpoint == endpoint_name and rule.rule.startswith('/api/'):
                csrf.exempt(view_fn)
                break


@app.before_request
def block_portal_from_internal():
    """Prevent portal users from accessing internal routes."""
    from flask import session as flask_session
    if flask_session.get('portal_user_id') and request.endpoint:
        # Allow portal routes and static files
        if (request.endpoint
            and not request.endpoint.startswith('portal')
            and request.endpoint != 'static'):
            abort(403)


# Make datetime.now available in templates
app.jinja_env.globals['now'] = datetime.now
app.jinja_env.globals['now_utc'] = lambda: datetime.now(timezone.utc)


@app.template_filter('format_number')
def format_number_filter(value):
    """Format integers with comma separators: 42500 -> 42,500"""
    try:
        return f'{int(value):,}'
    except (TypeError, ValueError):
        return str(value) if value is not None else '0'


@app.template_filter('unread_notification_count')
def unread_notification_count_filter(user):
    """Template filter: {{ current_user | unread_notification_count }}"""
    try:
        from models.notification import Notification
        db = get_session()
        try:
            return db.query(Notification).filter_by(recipient_id=user.id, is_read=False).count()
        finally:
            db.close()
    except Exception:
        return 0


# Initialize database
with app.app_context():
    init_db()
    # Seed default divisions for new installs
    db = get_session()
    try:
        if db.query(Division).count() == 0:
            org = db.query(Organization).first()
            if org:
                defaults = [
                    Division(organization_id=org.id, name='Plumbing', code='PLB', color='#2563eb', icon='bi-droplet-fill', sort_order=1),
                    Division(organization_id=org.id, name='HVAC', code='HVAC', color='#059669', icon='bi-thermometer-half', sort_order=2),
                    Division(organization_id=org.id, name='Electrical', code='ELEC', color='#f59e0b', icon='bi-lightning-fill', sort_order=3),
                    Division(organization_id=org.id, name='General Contracting', code='GC', color='#8b5cf6', icon='bi-hammer', sort_order=4),
                ]
                db.add_all(defaults)
                db.commit()
    except Exception as e:
        logger.error("Error seeding default divisions: %s", e)
    finally:
        db.close()

logger.info("FieldServicePro app initialized (production=%s)", IS_PRODUCTION)


# Dispose DB pool on shutdown to avoid ResourceWarning
import atexit
from models.database import dispose_engine
atexit.register(dispose_engine)


# ── Lightweight automation on request (runs at most once per hour) ──
@app.before_request
def run_background_checks():
    """Run contract expiry and SLA breach checks periodically."""
    _last_run_key = '_automation_last_run'
    now = datetime.now(timezone.utc)
    last_run = getattr(app, _last_run_key, None)
    if last_run is None or (now - last_run) > timedelta(hours=1):
        setattr(app, _last_run_key, now)
        try:
            from web.utils.contract_automation import (
                check_expired_contracts, check_sla_breaches
            )
            db = get_session()
            try:
                check_expired_contracts(db)
                check_sla_breaches(db)
            finally:
                db.close()
        except Exception:
            pass  # Never let automation errors break normal requests


# ── Mobile detection middleware ──
@app.before_request
def mobile_detection():
    """Detect mobile UA and set banner/preference flags."""
    from web.routes.mobile.middleware import should_show_mobile_banner, is_mobile_ua
    g.show_mobile_banner = False
    g.is_mobile = False
    if request.path.startswith('/static') or request.path.startswith('/auth'):
        return
    g.is_mobile = is_mobile_ua()
    if current_user.is_authenticated and should_show_mobile_banner():
        g.show_mobile_banner = True


@app.route('/set-mobile-pref')
def set_mobile_pref():
    """Set/clear mobile view preferences."""
    pref = request.args.get('pref', 'mobile')
    next_url = request.args.get('next', '/')
    if pref == 'mobile':
        session.pop('force_desktop', None)
        session['force_mobile'] = True
        return redirect(url_for('mobile.dashboard'))
    elif pref == 'desktop':
        session.pop('force_mobile', None)
        session['force_desktop'] = True
        session['mobile_banner_dismissed'] = True
        return redirect(next_url)
    elif pref == 'dismiss':
        session['mobile_banner_dismissed'] = True
        return redirect(next_url)
    return redirect(next_url)


# ── Mobile notification count context processor ──
@app.context_processor
def mobile_context():
    """Inject mobile-specific context variables."""
    notification_count = 0
    if current_user.is_authenticated:
        try:
            from models.notification import Notification
            db = get_session()
            try:
                notification_count = db.query(Notification).filter_by(
                    recipient_id=current_user.id, is_read=False
                ).count()
            finally:
                db.close()
        except Exception:
            pass
    return dict(notification_count=notification_count)


# ── Context processor: pending approval badge count ──
@app.context_processor
def inject_approval_count():
    count = 0
    if current_user.is_authenticated and current_user.role in ('owner', 'admin'):
        try:
            db = get_session()
            try:
                count = db.query(Invoice).filter(
                    Invoice.organization_id == current_user.organization_id,
                    Invoice.approval_status == 'pending'
                ).count()
            finally:
                db.close()
        except Exception:
            pass
    # Pending CO count
    co_count = 0
    if current_user.is_authenticated and current_user.role in ('owner', 'admin', 'dispatcher'):
        try:
            from models.change_order import ChangeOrder
            db2 = get_session()
            try:
                co_count = db2.query(ChangeOrder).join(Job).filter(
                    Job.organization_id == current_user.organization_id,
                    ChangeOrder.status.in_(['submitted', 'pending_approval'])
                ).count()
            finally:
                db2.close()
        except Exception:
            pass

    # New service request count
    new_request_count = 0
    if current_user.is_authenticated:
        try:
            from models.service_request import ServiceRequest
            db3 = get_session()
            try:
                new_request_count = db3.query(ServiceRequest).filter_by(
                    organization_id=current_user.organization_id, status='new'
                ).count()
            finally:
                db3.close()
        except Exception:
            pass

    # Active project count
    active_project_count = 0
    if current_user.is_authenticated:
        try:
            from models.project import Project
            db4 = get_session()
            try:
                active_project_count = db4.query(Project).filter_by(
                    organization_id=current_user.organization_id, status='active'
                ).count()
            finally:
                db4.close()
        except Exception:
            pass

    # Permission helpers for templates
    from web.utils.permissions import (
        can_manage_phase, can_approve_change_order,
        can_edit_change_order, can_create_change_order_fn,
    )
    return {
        'pending_approval_count': count,
        'pending_co_count': co_count,
        'new_request_count': new_request_count,
        'active_project_count': active_project_count,
        'pending_time_approvals': _get_pending_time_approvals(),
        'low_stock_count': _get_low_stock_count(),
        'recurring_alert_count': _get_recurring_alert_count(),
        'warranty_expiring_count': _get_warranty_expiring_count(),
        'open_callbacks_count': _get_open_callbacks_count(),
        'overdue_followups_count': _get_overdue_followups_count(),
        'pending_expenses_count': _get_pending_expenses_count(),
        'g_unread_notif_count': _get_unread_notif_count(),
        'open_rfi_count': _get_open_rfi_count(),
        'pending_sub_count': _get_pending_sub_count(),
        'pending_spo_count': _get_pending_spo_count(),
        'feedback_badge_count': _get_feedback_badge_count(),
        'all_clients': _get_all_clients_for_quicklog(),
        'comm_templates': _get_comm_templates_for_quicklog(),
        'can_manage_phase': can_manage_phase,
        'can_approve_change_order': can_approve_change_order,
        'can_edit_change_order': can_edit_change_order,
        'can_create_change_order_fn': can_create_change_order_fn,
    }


def _get_pending_time_approvals():
    """Get count of pending time entry approvals."""
    try:
        if current_user.is_authenticated and current_user.role in ('owner', 'admin'):
            from models.time_entry import TimeEntry
            db5 = get_session()
            try:
                return db5.query(TimeEntry).filter_by(status='submitted').count()
            finally:
                db5.close()
    except Exception:
        pass
    return 0


def _get_low_stock_count():
    """Get count of low-stock parts for sidebar badge."""
    try:
        if current_user.is_authenticated:
            from web.utils.parts_utils import get_low_stock_count
            db6 = get_session()
            try:
                return get_low_stock_count(db6, current_user.organization_id)
            finally:
                db6.close()
    except Exception:
        pass
    return 0


def _get_warranty_expiring_count():
    try:
        if current_user.is_authenticated:
            from sqlalchemy import func as _func
            from models.warranty import Warranty
            db8 = get_session()
            try:
                return db8.query(_func.count(Warranty.id)).filter(Warranty.status == 'expiring_soon').scalar() or 0
            finally:
                db8.close()
    except Exception:
        pass
    return 0


def _get_open_callbacks_count():
    try:
        if current_user.is_authenticated:
            from sqlalchemy import func as _func
            from models.callback import Callback
            db9 = get_session()
            try:
                return db9.query(_func.count(Callback.id)).filter(
                    Callback.status.notin_(['resolved', 'closed'])
                ).scalar() or 0
            finally:
                db9.close()
    except Exception:
        pass
    return 0


def _get_pending_expenses_count():
    try:
        if current_user.is_authenticated and current_user.role in ('owner', 'admin'):
            from models.expense import Expense
            from sqlalchemy import func as _f
            db_pe = get_session()
            try:
                return db_pe.query(_f.count(Expense.id)).filter(Expense.status == 'submitted').scalar() or 0
            finally:
                db_pe.close()
    except Exception:
        pass
    return 0


def _get_unread_notif_count():
    try:
        if current_user.is_authenticated:
            from web.utils.notification_service import NotificationService
            return NotificationService.get_unread_count(current_user.id)
    except Exception:
        pass
    return 0


def _get_open_rfi_count():
    try:
        if current_user.is_authenticated:
            from models.rfi import RFI
            db = get_session()
            try:
                return db.query(RFI).filter(RFI.status.in_(['open', 'pending_response'])).count()
            finally:
                db.close()
    except Exception:
        pass
    return 0


def _get_pending_sub_count():
    try:
        if current_user.is_authenticated:
            from models.submittal import Submittal
            db = get_session()
            try:
                return db.query(Submittal).filter(Submittal.status.in_(['submitted', 'under_review'])).count()
            finally:
                db.close()
    except Exception:
        pass
    return 0


def _get_pending_spo_count():
    try:
        if current_user.is_authenticated and current_user.role in ('owner', 'admin', 'dispatcher'):
            from models.supplier_po import SupplierPurchaseOrder
            db = get_session()
            try:
                return db.query(SupplierPurchaseOrder).filter(
                    SupplierPurchaseOrder.status.in_(['submitted', 'acknowledged', 'partially_received'])
                ).count()
            finally:
                db.close()
    except Exception:
        pass
    return 0


def _get_feedback_badge_count():
    """Count negative feedback needing follow-up."""
    try:
        if current_user.is_authenticated and current_user.role in ('owner', 'admin', 'dispatcher'):
            from models.feedback_survey import FeedbackSurvey
            db = get_session()
            try:
                return db.query(FeedbackSurvey).filter(
                    FeedbackSurvey.follow_up_required == True,
                    FeedbackSurvey.follow_up_completed == False,
                    FeedbackSurvey.status == 'completed',
                ).count()
            finally:
                db.close()
    except Exception:
        pass
    return 0





def _get_all_clients_for_quicklog():
    try:
        if current_user.is_authenticated:
            from models.client import Client as _Client
            db_ql = get_session()
            try:
                return db_ql.query(_Client).filter_by(organization_id=current_user.organization_id).order_by(_Client.company_name).all()
            finally:
                db_ql.close()
    except Exception:
        pass
    return []


def _get_comm_templates_for_quicklog():
    try:
        if current_user.is_authenticated:
            from models.communication import CommunicationTemplate as _CT
            db_ct = get_session()
            try:
                return db_ct.query(_CT).filter_by(is_active=True).order_by(_CT.name).all()
            finally:
                db_ct.close()
    except Exception:
        pass
    return []


def _get_overdue_followups_count():
    try:
        if current_user.is_authenticated:
            from web.utils.communication_utils import get_overdue_follow_up_count
            db10 = get_session()
            try:
                return get_overdue_follow_up_count(db10)
            finally:
                db10.close()
    except Exception:
        pass
    return 0


def _get_comm_overdue_for_dashboard(db):
    try:
        from models.communication import CommunicationLog
        return db.query(CommunicationLog).filter(
            CommunicationLog.follow_up_required == True,
            CommunicationLog.follow_up_completed == False,
            CommunicationLog.follow_up_date < date.today()
        ).count()
    except Exception:
        return 0


def _get_comm_due_today_for_dashboard(db):
    try:
        from models.communication import CommunicationLog
        return db.query(CommunicationLog).filter(
            CommunicationLog.follow_up_required == True,
            CommunicationLog.follow_up_completed == False,
            CommunicationLog.follow_up_date == date.today()
        ).count()
    except Exception:
        return 0


def _get_pm_dashboard_stats(db):
    """Project management stats for the dashboard."""
    try:
        from models.rfi import RFI
        from models.submittal import Submittal
        from models.punch_list import PunchList
        from models.daily_log import DailyLog
        today_date = date.today()

        open_rfis = db.query(RFI).filter(RFI.status.in_(['open', 'pending_response'])).count()
        overdue_rfis = db.query(RFI).filter(
            RFI.status.notin_(['answered', 'closed', 'void']),
            RFI.date_required != None, RFI.date_required < today_date,
        ).count()
        pending_submittals = db.query(Submittal).filter(
            Submittal.status.in_(['submitted', 'under_review'])
        ).count()
        active_pls = db.query(PunchList).filter(
            PunchList.status.in_(['active', 'in_progress'])
        ).all()
        avg_complete = round(sum(pl.percent_complete for pl in active_pls) / len(active_pls)) if active_pls else None
        logs_today = db.query(DailyLog).filter_by(log_date=today_date).count()

        return {
            'open_rfis': open_rfis, 'overdue_rfis': overdue_rfis,
            'pending_submittals': pending_submittals,
            'active_punch_lists': len(active_pls),
            'punch_list_avg_complete': avg_complete,
            'logs_today': logs_today,
        }
    except Exception:
        return {'open_rfis': 0, 'overdue_rfis': 0, 'pending_submittals': 0,
                'active_punch_lists': 0, 'punch_list_avg_complete': None, 'logs_today': 0}


def _get_warranty_dashboard_stats(db):
    try:
        from web.utils.warranty_utils import get_warranty_stats
        return get_warranty_stats(db)
    except Exception:
        return {'total_active': 0, 'expiring_soon': 0, 'expired_this_month': 0, 'claims_this_month': 0}


def _get_callback_dashboard_stats(db):
    try:
        from web.utils.callback_utils import get_callback_stats
        return get_callback_stats(db, current_user.organization_id)
    except Exception:
        return {'open_callbacks': 0, 'resolved_this_month': 0, 'callback_rate': 0, 'recent_callbacks': 0}


def _get_recurring_alert_count():
    """Get count of overdue + due-soon recurring schedules for sidebar badge."""
    try:
        if current_user.is_authenticated and current_user.role in ('owner', 'admin', 'dispatcher'):
            from web.utils.recurring_engine import get_dashboard_summary
            db7 = get_session()
            try:
                summary = get_dashboard_summary(db7, current_user.organization_id)
                return summary.get('alert_count', 0)
            finally:
                db7.close()
    except Exception:
        pass
    return 0


# ========== HEALTH CHECK (Render uses this) ==========

@app.route('/robots.txt')
def robots_txt():
    """Serve robots.txt at the conventional top-level URL."""
    return send_from_directory(app.static_folder, 'robots.txt', mimetype='text/plain')


@app.route('/health')
def health_check():
    """Health check endpoint for Render deploy verification."""
    db = get_session()
    try:
        db.execute(text('SELECT 1'))
        db_status = 'connected'
    except Exception:
        db_status = 'unavailable'
    finally:
        db.close()
    status_code = 200 if db_status == 'connected' else 503
    return jsonify({
        'status': 'healthy' if db_status == 'connected' else 'degraded',
        'database': db_status,
    }), status_code


@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html',
                           active_page='', user=current_user,
                           divisions=[]), 403


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return render_template('errors/404.html',
                           active_page='', user=current_user,
                           divisions=[]), 404


@app.errorhandler(500)
def server_error(e):
    """Branded 500 page. Logs full stack trace to stdout for Render log search."""
    logger.exception("Internal server error: %s", e)
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error'}), 500
    return render_template('errors/500.html',
                           active_page='', user=current_user,
                           divisions=[]), 500


def get_divisions():
    """Get all active divisions for the current user's org."""
    from web.utils.helpers import get_divisions as _get_divisions
    return _get_divisions()


def get_active_division(request):
    """Get the currently selected division from query param or session."""
    division_id = request.args.get('division')
    return int(division_id) if division_id else None


# ========== DASHBOARD ==========

@app.route('/')
@login_required
def dashboard():
    db = get_session()
    try:
        org_id = current_user.organization_id
        active_div = get_active_division(request)

        # Base queries
        jobs_q = db.query(Job).filter_by(organization_id=org_id)
        quotes_q = db.query(Quote).filter_by(organization_id=org_id)
        invoices_q = db.query(Invoice).filter_by(organization_id=org_id)
        clients_q = db.query(Client).filter_by(organization_id=org_id)

        if active_div:
            jobs_q = jobs_q.filter_by(division_id=active_div)
            quotes_q = quotes_q.filter_by(division_id=active_div)



        # ── Workflow pipeline counts ──
        # Requests = draft jobs (new requests)
        requests_new = jobs_q.filter_by(status='draft').count()
        requests_overdue = jobs_q.filter(
            Job.status == 'draft',
            Job.scheduled_date != None,
            Job.scheduled_date < datetime.now(timezone.utc)
        ).count()

        # Quotes
        quotes_draft = quotes_q.filter_by(status='draft').count()
        quotes_approved = quotes_q.filter_by(status='approved').count()
        quotes_changes = quotes_q.filter_by(status='declined').count()
        quotes_total_value = db.query(func.coalesce(func.sum(Quote.total), 0)).filter(
            Quote.organization_id == org_id, Quote.status == 'draft'
        ).scalar()

        # Jobs
        total_jobs = jobs_q.count()
        active_jobs = jobs_q.filter(Job.status.in_(['scheduled', 'in_progress'])).count()
        completed_jobs = jobs_q.filter_by(status='completed').count()
        jobs_requires_invoicing = jobs_q.filter_by(status='completed').count()
        jobs_action_required = jobs_q.filter(Job.status.in_(['on_hold'])).count()
        jobs_active_value = db.query(func.coalesce(func.sum(Job.estimated_amount), 0)).filter(
            Job.organization_id == org_id,
            Job.status.in_(['scheduled', 'in_progress'])
        ).scalar()
        jobs_action_value = db.query(func.coalesce(func.sum(Job.estimated_amount), 0)).filter(
            Job.organization_id == org_id,
            Job.status == 'on_hold'
        ).scalar()

        # Invoices
        total_quotes = quotes_q.count()
        total_clients = clients_q.count()
        invoices_awaiting = invoices_q.filter(Invoice.status.in_(['sent', 'viewed', 'partial', 'overdue'])).count()
        invoices_draft = invoices_q.filter_by(status='draft').count()
        invoices_past_due = invoices_q.filter_by(status='overdue').count()

        # ── Revenue / Financial ──
        total_invoiced = db.query(func.coalesce(func.sum(Invoice.total), 0)).filter_by(organization_id=org_id).scalar()
        total_outstanding = db.query(func.coalesce(func.sum(Invoice.balance_due), 0)).filter(
            Invoice.organization_id == org_id,
            Invoice.status.in_(['sent', 'viewed', 'partial', 'overdue'])
        ).scalar()
        total_overdue = db.query(func.coalesce(func.sum(Invoice.balance_due), 0)).filter(
            Invoice.organization_id == org_id,
            Invoice.status == 'overdue'
        ).scalar()
        invoices_draft_value = db.query(func.coalesce(func.sum(Invoice.total), 0)).filter(
            Invoice.organization_id == org_id, Invoice.status == 'draft'
        ).scalar()
        invoices_past_due_value = db.query(func.coalesce(func.sum(Invoice.balance_due), 0)).filter(
            Invoice.organization_id == org_id, Invoice.status == 'overdue'
        ).scalar()
        total_paid = db.query(func.coalesce(func.sum(Invoice.amount_paid), 0)).filter_by(organization_id=org_id).scalar()

        # ── Receivables breakdown (top clients who owe) ──
        receivables_clients = db.query(
            Client.id,
            Client.company_name, Client.first_name, Client.last_name, Client.client_type,
            func.sum(Invoice.balance_due).label('balance'),
            func.sum(
                case(
                    (Invoice.status == 'overdue', Invoice.balance_due),
                    else_=0
                )
            ).label('late')
        ).join(Invoice, Invoice.client_id == Client.id).filter(
            Invoice.organization_id == org_id,
            Invoice.status.in_(['sent', 'viewed', 'partial', 'overdue']),
            Invoice.balance_due > 0
        ).group_by(Client.id).order_by(func.sum(Invoice.balance_due).desc()).limit(5).all()

        receivables_count = db.query(func.count(func.distinct(Client.id))).join(
            Invoice, Invoice.client_id == Client.id
        ).filter(
            Invoice.organization_id == org_id,
            Invoice.status.in_(['sent', 'viewed', 'partial', 'overdue']),
            Invoice.balance_due > 0
        ).scalar()

        # ── Today's appointments ──
        today = datetime.now(timezone.utc).date()
        todays_jobs_q = jobs_q.filter(
            Job.scheduled_date != None,
            func.date(Job.scheduled_date) == today
        ).order_by(Job.scheduled_date)
        todays_jobs = todays_jobs_q.all()
        todays_total = db.query(func.coalesce(func.sum(Job.estimated_amount), 0)).filter(
            Job.organization_id == org_id,
            Job.scheduled_date != None,
            func.date(Job.scheduled_date) == today
        ).scalar()
        todays_active_value = db.query(func.coalesce(func.sum(Job.estimated_amount), 0)).filter(
            Job.organization_id == org_id,
            Job.scheduled_date != None,
            func.date(Job.scheduled_date) == today,
            Job.status.in_(['scheduled', 'in_progress'])
        ).scalar()
        todays_completed_value = db.query(func.coalesce(func.sum(Job.estimated_amount), 0)).filter(
            Job.organization_id == org_id,
            Job.scheduled_date != None,
            func.date(Job.scheduled_date) == today,
            Job.status == 'completed'
        ).scalar()
        now_utc = datetime.now(timezone.utc)
        todays_overdue_jobs = [j for j in todays_jobs if j.status in ('draft', 'scheduled') and j.scheduled_date and j.scheduled_date.replace(tzinfo=timezone.utc) < now_utc]

        # ── Upcoming jobs (this week) ──
        week_end = today + timedelta(days=7)
        upcoming_jobs_value = db.query(func.coalesce(func.sum(Job.estimated_amount), 0)).filter(
            Job.organization_id == org_id,
            Job.scheduled_date != None,
            func.date(Job.scheduled_date) >= today,
            func.date(Job.scheduled_date) <= week_end,
            Job.status.in_(['scheduled', 'in_progress', 'draft'])
        ).scalar()

        # Recent jobs
        recent_jobs = jobs_q.order_by(Job.created_at.desc()).limit(10).all()

        # ── Contract & SLA dashboard widgets ──
        in_30_days = today + timedelta(days=30)
        expiring_contracts = (db.query(Contract)
                               .filter(
                                   Contract.organization_id == org_id,
                                   Contract.status == ContractStatus.active,
                                   Contract.end_date >= today,
                                   Contract.end_date <= in_30_days
                               )
                               .order_by(Contract.end_date.asc())
                               .limit(5)
                               .all())

        from web.utils.sla_engine import get_sla_alert_jobs
        sla_alert_jobs = get_sla_alert_jobs(db, limit=5)

        month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        sla_jobs_month = (db.query(Job)
                            .filter(
                                Job.organization_id == org_id,
                                Job.sla_id.isnot(None),
                                Job.actual_resolution_time.isnot(None),
                                Job.actual_resolution_time >= month_ago
                            )
                            .all())
        sla_perf_pct = None
        if sla_jobs_month:
            met_count = sum(1 for j in sla_jobs_month if j.sla_resolution_met)
            sla_perf_pct = round(met_count / len(sla_jobs_month) * 100, 1)

        # ── Commercial dashboard widgets ──
        # AR Summary
        outstanding_invs = db.query(Invoice).filter(
            Invoice.organization_id == org_id,
            Invoice.status.in_(['sent', 'overdue', 'partial'])
        ).all()
        total_ar = sum(float(inv.balance_due or 0) for inv in outstanding_invs)
        overdue_amount = sum(float(inv.balance_due or 0) for inv in outstanding_invs if inv.days_overdue > 0)

        # Avg days to payment (paid invoices last 90 days)
        ninety_ago = datetime.now(timezone.utc) - timedelta(days=90)
        paid_invs = db.query(Invoice).filter(
            Invoice.organization_id == org_id,
            Invoice.status == 'paid',
            Invoice.updated_at >= ninety_ago,
            Invoice.due_date.isnot(None),
        ).all()
        avg_days_to_payment = 0
        if paid_invs:
            def _days_to_pay(inv):
                if not inv.updated_at or not inv.issued_date:
                    return 0
                end = inv.updated_at.date() if hasattr(inv.updated_at, 'date') else inv.updated_at
                start = inv.issued_date.date() if hasattr(inv.issued_date, 'date') else inv.issued_date
                return max(0, (end - start).days)
            avg_days_to_payment = round(
                sum(_days_to_pay(inv) for inv in paid_invs) / len(paid_invs), 1
            )

        # Pending approvals
        pending_approvals = db.query(Invoice).filter(
            Invoice.organization_id == org_id,
            Invoice.approval_status == 'pending'
        ).count()

        # Expiring POs
        from models.purchase_order import PurchaseOrder
        soon_30 = today + timedelta(days=30)
        expiring_pos = db.query(PurchaseOrder).filter(
            PurchaseOrder.organization_id == org_id,
            PurchaseOrder.status == 'active',
            PurchaseOrder.expiry_date.isnot(None),
            PurchaseOrder.expiry_date >= today,
            PurchaseOrder.expiry_date <= soon_30,
        ).order_by(PurchaseOrder.expiry_date).all()

        # ── Compliance alerts ──
        compliance_alerts = []
        try:
            from web.utils.compliance_checks import get_all_compliance_alerts
            compliance_alerts = get_all_compliance_alerts(db)
        except Exception:
            pass

        return render_template('dashboard.html',
            active_page='dashboard',
            user=current_user,
            divisions=get_divisions(),
            active_division=active_div,
            # Workflow pipeline
            requests_new=requests_new,
            requests_overdue=requests_overdue,
            quotes_draft=quotes_draft,
            quotes_approved=quotes_approved,
            quotes_changes=quotes_changes,
            quotes_total_value=quotes_total_value,
            total_jobs=total_jobs,
            active_jobs=active_jobs,
            completed_jobs=completed_jobs,
            jobs_requires_invoicing=jobs_requires_invoicing,
            jobs_action_required=jobs_action_required,
            jobs_active_value=jobs_active_value,
            jobs_action_value=jobs_action_value,
            invoices_awaiting=invoices_awaiting,
            invoices_draft=invoices_draft,
            invoices_past_due=invoices_past_due,
            invoices_draft_value=invoices_draft_value,
            invoices_past_due_value=invoices_past_due_value,
            # Financial
            total_quotes=total_quotes,
            total_clients=total_clients,
            total_invoiced=total_invoiced,
            total_outstanding=total_outstanding,
            total_overdue=total_overdue,
            total_paid=total_paid,
            # Receivables
            receivables_clients=receivables_clients,
            receivables_count=receivables_count,
            # Today
            todays_jobs=[j.to_dict() for j in todays_jobs],
            todays_total=todays_total,
            todays_active_value=todays_active_value,
            todays_completed_value=todays_completed_value,
            todays_overdue_value=sum(j.estimated_amount or 0 for j in todays_overdue_jobs),
            todays_remaining=todays_active_value - todays_completed_value,
            # Upcoming
            upcoming_jobs_value=upcoming_jobs_value,
            # Recent
            recent_jobs=[j.to_dict() for j in recent_jobs],
            # Contracts & SLA widgets
            expiring_contracts=expiring_contracts,
            sla_alert_jobs=sla_alert_jobs,
            sla_perf_pct=sla_perf_pct,
            sla_jobs_count=len(sla_jobs_month),
            # Commercial widgets
            total_ar=total_ar,
            overdue_amount=overdue_amount,
            avg_days_to_payment=avg_days_to_payment,
            pending_approvals=pending_approvals,
            expiring_pos=expiring_pos,
            compliance_alerts=compliance_alerts,
            warranty_stats=_get_warranty_dashboard_stats(db),
            callback_stats=_get_callback_dashboard_stats(db),
            comm_overdue_count=_get_comm_overdue_for_dashboard(db),
            comm_due_today_count=_get_comm_due_today_for_dashboard(db),
            pm_stats=_get_pm_dashboard_stats(db),
        )
    finally:
        db.close()


# ========== JOBS — moved to web/routes/jobs_routes.py ==========


# ========== QUOTES — moved to web/routes/quotes_routes.py ==========



# ========== CLIENTS — moved to web/routes/clients_routes.py ==========


# ========== INVOICES — moved to web/routes/invoices_routes.py ==========


# ========== SCHEDULE ==========

@app.route('/schedule')
@login_required
def schedule_page():
    db = get_session()
    try:
        org_id = current_user.organization_id
        active_div = get_active_division(request)

        base_q = db.query(Job).filter(
            Job.organization_id == org_id,
            Job.status.in_(['draft', 'scheduled', 'in_progress'])
        )
        if active_div:
            base_q = base_q.filter_by(division_id=active_div)

        # Scheduled jobs
        scheduled_jobs = base_q.filter(
            Job.scheduled_date != None
        ).order_by(Job.scheduled_date).all()

        # Unscheduled jobs
        unscheduled_jobs = base_q.filter(
            Job.scheduled_date == None
        ).order_by(Job.created_at.desc()).all()

        def job_to_event(job):
            prop = job.property
            location = ''
            if prop:
                parts = [p for p in [prop.address, prop.city, prop.province, prop.postal_code] if p]
                location = ', '.join(parts)
            return {
                'id': job.id,
                'title': job.title,
                'job_number': job.job_number or '',
                'start': job.scheduled_date.isoformat() if job.scheduled_date else None,
                'end': job.scheduled_end.isoformat() if job.scheduled_end else None,
                'status': job.status,
                'priority': job.priority or 'normal',
                'job_type': job.job_type or '',
                'technician': job.technician.full_name if job.technician else 'Unassigned',
                'client': job.client.display_name if job.client else '',
                'division': job.division.name if job.division else '',
                'color': job.division.color if job.division else '#2563eb',
                'location': location,
                'estimated_amount': job.estimated_amount or 0,
            }

        events = [job_to_event(j) for j in scheduled_jobs]
        unscheduled = [job_to_event(j) for j in unscheduled_jobs]

        # Phase events
        from models.job_phase import JobPhase
        phase_events = []
        phases_with_dates = db.query(JobPhase).join(Job).filter(
            Job.organization_id == org_id,
            JobPhase.scheduled_start_date.isnot(None),
            JobPhase.status.notin_(['skipped', 'completed']),
        ).all()

        # Conflict detection
        from collections import defaultdict
        tech_phases = defaultdict(list)
        for p in phases_with_dates:
            if p.assigned_technician_id and p.scheduled_start_date:
                tech_phases[p.assigned_technician_id].append(p)

        conflict_ids = set()
        for tid, tlist in tech_phases.items():
            sorted_p = sorted(tlist, key=lambda x: x.scheduled_start_date)
            for i in range(len(sorted_p)):
                for j in range(i + 1, len(sorted_p)):
                    a, b = sorted_p[i], sorted_p[j]
                    a_end = a.scheduled_end_date or a.scheduled_start_date
                    if a_end >= b.scheduled_start_date:
                        conflict_ids.add(a.id)
                        conflict_ids.add(b.id)

        phase_colors = {'not_started': '#6c757d', 'scheduled': '#0dcaf0', 'in_progress': '#0d6efd', 'on_hold': '#ffc107'}
        for p in phases_with_dates:
            evt = {
                'id': f'phase-{p.id}',
                'title': f'[{p.job.job_number}] P{p.phase_number}: {p.title[:25]}',
                'start': p.scheduled_start_date.isoformat(),
                'color': phase_colors.get(p.status, '#6c757d'),
                'url': f'/jobs/{p.job_id}#phases',
                'type': 'phase',
                'has_conflict': p.id in conflict_ids,
            }
            if p.scheduled_end_date:
                evt['end'] = p.scheduled_end_date.isoformat()
            phase_events.append(evt)

        all_events = events + phase_events
        phases_with_conflicts = [p for p in phases_with_dates if p.id in conflict_ids]

        technicians = db.query(Technician).filter_by(
            organization_id=org_id, is_active=True
        ).all()

        return render_template('schedule.html',
            active_page='schedule',
            user=current_user,
            divisions=get_divisions(),
            active_division=active_div,
            events=all_events,
            unscheduled=unscheduled,
            technicians=[t.to_dict() for t in technicians],
            events_json=all_events,
            unscheduled_json=unscheduled,
            phases_with_conflicts=phases_with_conflicts,
        )
    finally:
        db.close()


# ========== SETTINGS ==========


# ========== API: Lookup data for forms ==========

@app.route('/api/lookup/clients')
@login_required
def lookup_clients():
    db = get_session()
    try:
        clients = db.query(Client).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Client.company_name, Client.last_name).all()
        return jsonify([c.to_dict() for c in clients])
    finally:
        db.close()


@app.route('/api/lookup/properties/<int:client_id>')
@login_required
def lookup_properties(client_id):
    db = get_session()
    try:
        client = db.query(Client).filter_by(id=client_id, organization_id=current_user.organization_id).first()
        if not client:
            return jsonify([]), 404
        props = db.query(Property).filter_by(client_id=client_id, is_active=True).all()
        return jsonify([p.to_dict() for p in props])
    finally:
        db.close()


@app.route('/api/lookup/technicians')
@login_required
def lookup_technicians():
    db = get_session()
    try:
        division_id = request.args.get('division_id')
        q = db.query(Technician).filter_by(
            organization_id=current_user.organization_id, is_active=True
        )
        if division_id:
            q = q.filter_by(division_id=division_id)
        techs = q.all()
        return jsonify([t.to_dict() for t in techs])
    finally:
        db.close()


# ========== API: Chat ==========
@login_required
def chat_api():
    """AI chat endpoint with streaming support."""
    import json
    data = request.get_json()
    message = data.get('message', '').strip()
    client_id = data.get('client_id')
    mode = data.get('mode', 'general')
    session_id = data.get('session_id', f"user-{current_user.id}")

    if not message:
        return jsonify({'error': 'Message is required'}), 400

    # Check for API key
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured. Set it in your environment to enable AI chat.'}), 503

    db = get_session()
    try:
        from src.ai_core.context_builder import build_global_context, build_client_context
        from src.ai_core.chat_engine import ConversationMode

        # Build context
        org_id = current_user.organization_id
        context = build_global_context(db, org_id)
        if client_id:
            context += "\n\n" + build_client_context(db, int(client_id))

        # Map mode string to enum
        mode_map = {m.value: m for m in ConversationMode}
        conv_mode = mode_map.get(mode, ConversationMode.GENERAL)

        engine = get_chat_engine()

        # Stream response
        def generate():
            try:
                for chunk in engine.chat_stream(session_id, message, context, conv_mode):
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
        )
    finally:
        db.close()


@app.route('/api/chat/suggestions', methods=['GET'])
@login_required
def chat_suggestions():
    """Get context-aware suggested prompts."""
    client_id = request.args.get('client_id')
    db = get_session()
    try:
        from src.ai_core.context_builder import get_context_summary
        from src.ai_core.chat_engine import ChatEngine

        summary = get_context_summary(db, current_user.organization_id, client_id)
        engine = ChatEngine.__new__(ChatEngine)
        engine.sessions = {}
        prompts = engine.get_suggested_prompts(summary)
        return jsonify({'suggestions': prompts})
    except Exception:
        return jsonify({'suggestions': [
            "Give me a summary of our business this month",
            "Which clients have overdue invoices?",
            "What jobs are scheduled for this week?",
        ]})
    finally:
        db.close()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 58391))
    import webbrowser, threading
    threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
    app.run(debug=True, port=port)
