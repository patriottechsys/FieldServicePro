"""Portal user model for client-facing authentication and access control."""
from datetime import timezone, datetime, timedelta
import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship
from .database import Base


# Association table for portal user <-> property access restrictions
portal_user_properties = Table(
    'portal_user_properties', Base.metadata,
    Column('portal_user_id', Integer, ForeignKey('portal_users.id'), primary_key=True),
    Column('property_id', Integer, ForeignKey('properties.id'), primary_key=True),
)


class PortalUser(Base):
    __tablename__ = 'portal_users'

    id                   = Column(Integer, primary_key=True)
    email                = Column(String(255), unique=True, nullable=False, index=True)
    password_hash        = Column(String(255), nullable=True)  # Null until password is set
    first_name           = Column(String(100), nullable=False)
    last_name            = Column(String(100), nullable=False)
    phone                = Column(String(30), nullable=True)

    client_id            = Column(Integer, ForeignKey('clients.id'), nullable=False, index=True)
    role                 = Column(String(20), nullable=False, default='standard')
    # Roles: primary, manager, standard, billing_only, view_only

    is_active            = Column(Boolean, default=True, nullable=False)
    last_login           = Column(DateTime, nullable=True)
    login_attempts       = Column(Integer, default=0, nullable=False)
    locked_until         = Column(DateTime, nullable=True)

    password_reset_token  = Column(String(255), nullable=True, index=True)
    password_reset_expiry = Column(DateTime, nullable=True)

    invitation_token     = Column(String(255), nullable=True, index=True)
    invitation_expiry    = Column(DateTime, nullable=True)
    invitation_accepted  = Column(Boolean, default=False, nullable=False)

    created_by           = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at           = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at           = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    client = relationship('Client', backref='portal_users')
    creator = relationship('User', foreign_keys=[created_by])
    accessible_properties = relationship(
        'Property',
        secondary=portal_user_properties,
        backref='restricted_portal_users',
        lazy='select',
    )

    VALID_ROLES = ['primary', 'manager', 'standard', 'billing_only', 'view_only']

    ROLE_LABELS = {
        'primary': 'Primary Contact',
        'manager': 'Manager',
        'standard': 'Standard User',
        'billing_only': 'Billing Only',
        'view_only': 'View Only',
    }

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def role_label(self):
        return self.ROLE_LABELS.get(self.role, self.role)

    # --- Authentication helpers ---

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def generate_reset_token(self):
        self.password_reset_token = secrets.token_urlsafe(48)
        self.password_reset_expiry = datetime.now(timezone.utc) + timedelta(hours=24)
        return self.password_reset_token

    def generate_invitation_token(self):
        self.invitation_token = secrets.token_urlsafe(48)
        self.invitation_expiry = datetime.now(timezone.utc) + timedelta(days=7)
        return self.invitation_token

    def validate_reset_token(self, token):
        if self.password_reset_token != token or not self.password_reset_expiry:
            return False
        expiry = self.password_reset_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry > datetime.now(timezone.utc)

    def validate_invitation_token(self, token):
        if self.invitation_token != token or not self.invitation_expiry:
            return False
        expiry = self.invitation_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry > datetime.now(timezone.utc)

    def record_login(self):
        self.last_login = datetime.now(timezone.utc)
        self.login_attempts = 0
        self.locked_until = None

    def record_failed_login(self):
        self.login_attempts += 1
        if self.login_attempts >= 5:
            self.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)

    @property
    def is_locked(self):
        if self.locked_until and self.locked_until > datetime.now(timezone.utc):
            return True
        return False

    # --- Permission helpers ---

    def can_view_dashboard(self):
        return self.role in ('primary', 'manager', 'standard')

    def can_view_properties(self):
        return self.role in ('primary', 'manager', 'standard', 'view_only')

    def can_create_service_requests(self):
        return self.role in ('primary', 'manager', 'standard')

    def can_view_jobs(self):
        return self.role in ('primary', 'manager', 'standard', 'view_only')

    def can_view_quotes(self):
        return self.role in ('primary', 'manager')

    def can_approve_quotes(self):
        return self.role in ('primary', 'manager')

    def can_approve_change_orders(self):
        return self.role in ('primary', 'manager')

    def can_view_invoices(self):
        return self.role in ('primary', 'manager', 'billing_only')

    def can_view_documents(self):
        return self.role in ('primary', 'manager', 'standard', 'view_only')

    def can_upload_documents(self):
        return self.role in ('primary', 'manager', 'standard')

    def can_view_reports(self):
        return self.role in ('primary', 'manager')

    def can_send_messages(self):
        return self.role in ('primary', 'manager', 'standard')

    def can_manage_portal_users(self):
        return self.role == 'primary'

    def can_view_financials(self):
        return self.role in ('primary', 'manager', 'billing_only')

    def get_property_ids(self):
        """Return list of property IDs this user can access, or None for all."""
        if self.accessible_properties:
            return [p.id for p in self.accessible_properties]
        return None

    def to_dict(self):
        return {
            'id': self.id, 'email': self.email,
            'first_name': self.first_name, 'last_name': self.last_name,
            'full_name': self.full_name, 'phone': self.phone,
            'client_id': self.client_id, 'role': self.role,
            'role_label': self.role_label, 'is_active': self.is_active,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'invitation_accepted': self.invitation_accepted,
        }

    def __repr__(self):
        return f'<PortalUser {self.email} ({self.role}) client={self.client_id}>'
