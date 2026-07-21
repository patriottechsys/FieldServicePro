"""Notification routes: center, API, preferences, client templates."""
from datetime import timezone, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import desc

from models.database import get_session
from models.notification import (
    Notification, NotificationPreference, ClientNotificationTemplate, NotificationLog,
    NOTIFICATION_CATEGORIES, NOTIFICATION_PRIORITIES,
)
from models.division import Division
from web.auth import role_required

notifications_bp = Blueprint('notifications', __name__)


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


# ── Notification Center ───────────────────────────────────────────────────────

@notifications_bp.route('/notifications')
@login_required
def notification_center():
    db = get_session()
    try:
        page = request.args.get('page', 1, type=int)
        tab = request.args.get('tab', 'all')
        category = request.args.get('category', '')
        per_page = 20

        query = db.query(Notification).filter(
            Notification.recipient_id == current_user.id,
            Notification.is_dismissed == False,
        )
        if tab == 'unread':
            query = query.filter(Notification.is_read == False)
        elif tab == 'actionable':
            query = query.filter(Notification.is_actionable == True, Notification.action_completed == False)
        if category:
            query = query.filter(Notification.category == category)

        total = query.count()
        notifications = query.order_by(
            Notification.is_read.asc(), Notification.created_at.desc()
        ).offset((page - 1) * per_page).limit(per_page).all()

        unread_count = db.query(Notification).filter(
            Notification.recipient_id == current_user.id,
            Notification.is_read == False, Notification.is_dismissed == False,
        ).count()

        return render_template('notifications/notification_center.html',
            active_page='notifications', user=current_user, divisions=_get_divisions(),
            notifications=notifications, unread_count=unread_count,
            total=total, page=page, total_pages=(total + per_page - 1) // per_page,
            current_tab=tab, current_category=category,
            categories=NOTIFICATION_CATEGORIES, priorities=NOTIFICATION_PRIORITIES,
        )
    finally:
        db.close()


# ── API: Unread (bell polling) ────────────────────────────────────────────────

@notifications_bp.route('/notifications/api/unread')
@login_required
def api_unread():
    db = get_session()
    try:
        notifs = db.query(Notification).filter(
            Notification.recipient_id == current_user.id,
            Notification.is_read == False, Notification.is_dismissed == False,
        ).order_by(desc(Notification.created_at)).limit(10).all()

        count = db.query(Notification).filter(
            Notification.recipient_id == current_user.id,
            Notification.is_read == False, Notification.is_dismissed == False,
        ).count()

        return jsonify({'unread_count': count, 'notifications': [n.to_dict() for n in notifs]})
    finally:
        db.close()


# ── Mark Read / Dismiss / Mark All Read ───────────────────────────────────────

@notifications_bp.route('/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_read(notif_id):
    db = get_session()
    try:
        n = db.query(Notification).filter_by(id=notif_id, recipient_id=current_user.id).first()
        if n:
            n.mark_read()
            db.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True})
        return redirect(request.referrer or url_for('notifications.notification_center'))
    finally:
        db.close()


@notifications_bp.route('/notifications/<int:notif_id>/dismiss', methods=['POST'])
@login_required
def dismiss(notif_id):
    db = get_session()
    try:
        n = db.query(Notification).filter_by(id=notif_id, recipient_id=current_user.id).first()
        if n:
            n.dismiss()
            db.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True})
        return redirect(request.referrer or url_for('notifications.notification_center'))
    finally:
        db.close()


@notifications_bp.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    from web.utils.notification_service import NotificationService
    count = NotificationService.mark_all_read(current_user.id)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'count': count})
    flash(f'Marked {count} notifications as read.', 'success')
    return redirect(url_for('notifications.notification_center'))


@notifications_bp.route('/notifications/<int:notif_id>/complete', methods=['POST'])
@login_required
def complete_action(notif_id):
    db = get_session()
    try:
        n = db.query(Notification).filter_by(id=notif_id, recipient_id=current_user.id).first()
        if n:
            n.action_completed = True
            n.mark_read()
            db.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True})
        return redirect(request.referrer or url_for('notifications.notification_center'))
    finally:
        db.close()


# ── Preferences ───────────────────────────────────────────────────────────────

@notifications_bp.route('/settings/notifications')
@login_required
def preferences():
    db = get_session()
    try:
        prefs = db.query(NotificationPreference).filter_by(user_id=current_user.id).all()
        pref_map = {p.category: p for p in prefs}

        cats = []
        for val, label in NOTIFICATION_CATEGORIES:
            p = pref_map.get(val)
            if not p:
                p = NotificationPreference(user_id=current_user.id, category=val, in_app=True, email=False, enabled=True)
                db.add(p)
            cats.append({'category': val, 'label': label, 'pref': p})
        db.commit()

        return render_template('notifications/preferences.html',
            active_page='settings', user=current_user, divisions=_get_divisions(),
            categories_display=cats,
        )
    finally:
        db.close()


@notifications_bp.route('/settings/notifications', methods=['POST'])
@login_required
def preferences_save():
    db = get_session()
    try:
        for val, _ in NOTIFICATION_CATEGORIES:
            p = db.query(NotificationPreference).filter_by(user_id=current_user.id, category=val).first()
            if not p:
                p = NotificationPreference(user_id=current_user.id, category=val)
                db.add(p)
            p.enabled = '1' in request.form.getlist(f'enabled_{val}')
            p.in_app = '1' in request.form.getlist(f'in_app_{val}')
            p.email = '1' in request.form.getlist(f'email_{val}')
        db.commit()
        flash('Preferences saved.', 'success')
    finally:
        db.close()
    return redirect(url_for('notifications.preferences'))


@notifications_bp.route('/settings/notifications/test', methods=['POST'])
@login_required
def preferences_test():
    from web.utils.notification_service import NotificationService
    notif = NotificationService.create_internal_notification(
        recipient=current_user, title='Test Notification',
        message='Your notification system is working correctly!',
        category='system', action_url=url_for('notifications.notification_center'),
    )
    flash('Test notification sent!' if notif else 'Could not create — check preferences.', 'success' if notif else 'warning')
    return redirect(url_for('notifications.preferences'))


# ── Client Templates ──────────────────────────────────────────────────────────

TRIGGER_EVENTS = [
    ('job_scheduled', 'Job Scheduled'), ('job_completed', 'Job Completed'),
    ('tech_en_route', 'Technician En Route'), ('appointment_reminder', 'Appointment Reminder'),
    ('quote_sent', 'Quote Sent'), ('invoice_issued', 'Invoice Issued'),
    ('invoice_reminder', 'Invoice Reminder'), ('payment_received', 'Payment Received'),
    ('warranty_created', 'Warranty Created'), ('warranty_expiring', 'Warranty Expiring'),
]

TEMPLATE_PLACEHOLDERS = [
    '{client_name}', '{client_first_name}', '{company_name}',
    '{job_number}', '{job_type}', '{technician_name}',
    '{scheduled_date}', '{scheduled_time}', '{property_address}',
    '{quote_number}', '{quote_total}',
    '{invoice_number}', '{invoice_total}', '{invoice_due_date}',
]


@notifications_bp.route('/settings/client-notifications')
@login_required
@role_required('admin', 'owner')
def client_templates():
    db = get_session()
    try:
        templates = db.query(ClientNotificationTemplate).order_by(ClientNotificationTemplate.name).all()
        return render_template('notifications/client_templates.html',
            active_page='settings', user=current_user, divisions=_get_divisions(),
            templates=templates, trigger_events=TRIGGER_EVENTS,
        )
    finally:
        db.close()


@notifications_bp.route('/settings/client-notifications/new', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'owner')
def client_template_new():
    db = get_session()
    try:
        if request.method == 'POST':
            t = ClientNotificationTemplate(
                name=request.form['name'].strip(),
                trigger_event=request.form['trigger_event'],
                channel=request.form.get('channel', 'email'),
                subject_template=request.form.get('subject_template', '').strip(),
                body_template=request.form['body_template'],
                sms_template=request.form.get('sms_template', '').strip() or None,
                is_active=request.form.get('is_active') == '1',
                send_delay_minutes=int(request.form.get('send_delay_minutes', 0) or 0),
                created_by=current_user.id,
            )
            db.add(t)
            db.commit()
            flash('Template created.', 'success')
            return redirect(url_for('notifications.client_templates'))

        return render_template('notifications/client_template_form.html',
            active_page='settings', user=current_user, divisions=_get_divisions(),
            template=None, trigger_events=TRIGGER_EVENTS,
            placeholders=TEMPLATE_PLACEHOLDERS,
        )
    finally:
        db.close()


@notifications_bp.route('/settings/client-notifications/<int:tmpl_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'owner')
def client_template_edit(tmpl_id):
    db = get_session()
    try:
        tmpl = db.query(ClientNotificationTemplate).filter_by(id=tmpl_id).first()
        if not tmpl:
            flash('Template not found.', 'error')
            return redirect(url_for('notifications.client_templates'))

        if request.method == 'POST':
            tmpl.name = request.form['name'].strip()
            tmpl.trigger_event = request.form['trigger_event']
            tmpl.channel = request.form.get('channel', 'email')
            tmpl.subject_template = request.form.get('subject_template', '').strip()
            tmpl.body_template = request.form['body_template']
            tmpl.sms_template = request.form.get('sms_template', '').strip() or None
            tmpl.is_active = request.form.get('is_active') == '1'
            tmpl.send_delay_minutes = int(request.form.get('send_delay_minutes', 0) or 0)
            db.commit()
            flash('Template updated.', 'success')
            return redirect(url_for('notifications.client_templates'))

        return render_template('notifications/client_template_form.html',
            active_page='settings', user=current_user, divisions=_get_divisions(),
            template=tmpl, trigger_events=TRIGGER_EVENTS,
            placeholders=TEMPLATE_PLACEHOLDERS,
        )
    finally:
        db.close()


@notifications_bp.route('/settings/client-notifications/<int:tmpl_id>/delete', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def client_template_delete(tmpl_id):
    db = get_session()
    try:
        tmpl = db.query(ClientNotificationTemplate).filter_by(id=tmpl_id).first()
        if tmpl:
            db.delete(tmpl)
            db.commit()
            flash('Template deleted.', 'warning')
    finally:
        db.close()
    return redirect(url_for('notifications.client_templates'))


@notifications_bp.route('/settings/client-notifications/<int:tmpl_id>/toggle', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def client_template_toggle(tmpl_id):
    db = get_session()
    try:
        tmpl = db.query(ClientNotificationTemplate).filter_by(id=tmpl_id).first()
        if tmpl:
            tmpl.is_active = not tmpl.is_active
            db.commit()
            return jsonify({'success': True, 'is_active': tmpl.is_active})
        return jsonify({'success': False}), 404
    finally:
        db.close()


# ── Notification Log (Admin) ─────────────────────────────────────────────────

@notifications_bp.route('/admin/notification-log')
@login_required
@role_required('admin', 'owner')
def notification_log():
    db = get_session()
    try:
        page = request.args.get('page', 1, type=int)
        channel = request.args.get('channel', '')
        status = request.args.get('status', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        search = request.args.get('q', '')
        per_page = 25

        query = db.query(NotificationLog)

        if channel:
            query = query.filter(NotificationLog.channel == channel)
        if status:
            query = query.filter(NotificationLog.status == status)
        if date_from:
            query = query.filter(NotificationLog.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
        if date_to:
            from datetime import timedelta as _td
            query = query.filter(NotificationLog.created_at < datetime.strptime(date_to, '%Y-%m-%d') + _td(days=1))
        if search:
            query = query.filter(
                NotificationLog.recipient_email.ilike(f'%{search}%') |
                NotificationLog.subject.ilike(f'%{search}%')
            )

        total = query.count()
        logs = query.order_by(desc(NotificationLog.created_at)).offset((page - 1) * per_page).limit(per_page).all()

        from sqlalchemy import func
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        stats = {
            'total_today': db.query(NotificationLog).filter(NotificationLog.created_at >= today_start).count(),
            'total_failed': db.query(NotificationLog).filter(NotificationLog.status == 'failed').count(),
            'total_emails': db.query(NotificationLog).filter(NotificationLog.channel == 'email').count(),
            'total_sms': db.query(NotificationLog).filter(NotificationLog.channel == 'sms').count(),
        }

        return render_template('notifications/notification_log.html',
            active_page='notifications', user=current_user, divisions=_get_divisions(),
            logs=logs, total=total, page=page,
            total_pages=(total + per_page - 1) // per_page,
            stats=stats,
            current_filters={'channel': channel, 'status': status, 'date_from': date_from, 'date_to': date_to, 'q': search},
        )
    finally:
        db.close()
