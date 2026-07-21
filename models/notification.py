"""Notification system models."""
from datetime import timezone, datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, Index, JSON
)
from sqlalchemy.orm import relationship
from .database import Base


NOTIFICATION_TYPES = [
    ('info', 'Info'), ('success', 'Success'), ('warning', 'Warning'),
    ('danger', 'Danger'), ('action_required', 'Action Required'),
]

NOTIFICATION_CATEGORIES = [
    ('job_update', 'Job Update'), ('schedule_change', 'Schedule Change'),
    ('request_new', 'New Request'), ('quote_update', 'Quote Update'),
    ('invoice_update', 'Invoice Update'), ('approval_needed', 'Approval Needed'),
    ('compliance_alert', 'Compliance Alert'), ('warranty_alert', 'Warranty Alert'),
    ('callback_alert', 'Callback Alert'), ('expense_update', 'Expense Update'),
    ('communication_follow_up', 'Communication Follow-up'),
    ('contract_alert', 'Contract Alert'), ('time_tracking', 'Time Tracking'),
    ('system', 'System'), ('other', 'Other'),
]

NOTIFICATION_PRIORITIES = [
    ('low', 'Low'), ('normal', 'Normal'), ('high', 'High'), ('urgent', 'Urgent'),
]

TYPE_COLORS = {
    'info': 'accent', 'success': 'success', 'warning': 'warning',
    'danger': 'danger', 'action_required': 'danger',
}

CATEGORY_ICONS = {
    'job_update': 'bi-briefcase', 'schedule_change': 'bi-calendar-event',
    'request_new': 'bi-inbox', 'quote_update': 'bi-file-text',
    'invoice_update': 'bi-receipt', 'approval_needed': 'bi-check-circle',
    'compliance_alert': 'bi-shield-exclamation', 'warranty_alert': 'bi-award',
    'callback_alert': 'bi-telephone-x', 'expense_update': 'bi-cash-coin',
    'communication_follow_up': 'bi-chat-dots', 'contract_alert': 'bi-file-earmark-ruled',
    'time_tracking': 'bi-clock', 'system': 'bi-gear', 'other': 'bi-bell',
}


class Notification(Base):
    __tablename__ = 'notifications'

    id = Column(Integer, primary_key=True)
    recipient_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(String(20), nullable=False, default='info')
    category = Column(String(50), nullable=False, default='other')
    priority = Column(String(10), nullable=False, default='normal')

    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Integer, nullable=True)
    action_url = Column(String(500), nullable=True)

    is_read = Column(Boolean, default=False, nullable=False)
    read_at = Column(DateTime, nullable=True)
    is_dismissed = Column(Boolean, default=False, nullable=False)
    dismissed_at = Column(DateTime, nullable=True)
    is_actionable = Column(Boolean, default=False, nullable=False)
    action_completed = Column(Boolean, default=False, nullable=False)

    triggered_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    recipient = relationship('User', foreign_keys=[recipient_id], backref='staff_notifications')
    triggerer = relationship('User', foreign_keys=[triggered_by])

    __table_args__ = (
        Index('ix_notif_unread', 'recipient_id', 'is_read', 'is_dismissed'),
    )

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.now(timezone.utc)

    def dismiss(self):
        self.is_dismissed = True
        self.dismissed_at = datetime.now(timezone.utc)
        self.mark_read()

    @property
    def time_ago(self):
        delta = datetime.now(timezone.utc) - self.created_at
        secs = int(delta.total_seconds())
        if secs < 60: return 'just now'
        if secs < 3600: m = secs // 60; return f'{m}m ago'
        if secs < 86400: h = secs // 3600; return f'{h}h ago'
        d = secs // 86400; return f'{d}d ago'

    @property
    def category_icon(self):
        return CATEGORY_ICONS.get(self.category, 'bi-bell')

    @property
    def type_color(self):
        return TYPE_COLORS.get(self.notification_type, 'secondary')

    def to_dict(self):
        return {
            'id': self.id, 'title': self.title, 'message': self.message,
            'notification_type': self.notification_type, 'category': self.category,
            'priority': self.priority, 'entity_type': self.entity_type,
            'entity_id': self.entity_id, 'action_url': self.action_url,
            'is_read': self.is_read, 'is_dismissed': self.is_dismissed,
            'is_actionable': self.is_actionable, 'time_ago': self.time_ago,
            'category_icon': self.category_icon, 'type_color': self.type_color,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class NotificationPreference(Base):
    __tablename__ = 'notification_preferences'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    category = Column(String(50), nullable=False)
    in_app = Column(Boolean, default=True, nullable=False)
    email = Column(Boolean, default=False, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship('User', backref='notif_preferences')


class ClientNotificationTemplate(Base):
    __tablename__ = 'client_notification_templates'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    trigger_event = Column(String(60), nullable=False)
    channel = Column(String(10), nullable=False, default='email')
    subject_template = Column(String(500), nullable=True)
    body_template = Column(Text, nullable=False)
    sms_template = Column(String(160), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    send_delay_minutes = Column(Integer, default=0, nullable=False)
    conditions = Column(JSON, nullable=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = relationship('User', foreign_keys=[created_by])


class NotificationLog(Base):
    __tablename__ = 'notification_logs'

    id = Column(Integer, primary_key=True)
    notification_id = Column(Integer, ForeignKey('notifications.id', ondelete='SET NULL'), nullable=True)
    channel = Column(String(10), nullable=False)
    recipient_type = Column(String(20), nullable=False)
    recipient_id = Column(Integer, nullable=True)
    recipient_email = Column(String(255), nullable=True)
    recipient_phone = Column(String(50), nullable=True)
    template_id = Column(Integer, ForeignKey('client_notification_templates.id', ondelete='SET NULL'), nullable=True)
    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='sent')
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    opened_at = Column(DateTime, nullable=True)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Integer, nullable=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    notification = relationship('Notification', foreign_keys=[notification_id])
    template = relationship('ClientNotificationTemplate', foreign_keys=[template_id])
