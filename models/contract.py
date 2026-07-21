"""Contract, ContractLineItem, ContractActivityLog, ContractAttachment models."""

from datetime import timezone, datetime, date
import enum
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Float, Date, DateTime,
    ForeignKey, Enum as SAEnum, Table
)
from sqlalchemy.orm import relationship
from .database import Base


# -- Many-to-many: Contract <-> Property --
contract_property = Table(
    'contract_property',
    Base.metadata,
    Column('contract_id', Integer, ForeignKey('contracts.id'), primary_key=True),
    Column('property_id', Integer, ForeignKey('properties.id'), primary_key=True)
)

# -- Many-to-many: Contract <-> SLA --
contract_sla = Table(
    'contract_sla',
    Base.metadata,
    Column('contract_id', Integer, ForeignKey('contracts.id'), primary_key=True),
    Column('sla_id', Integer, ForeignKey('slas.id'), primary_key=True)
)


class ContractType(str, enum.Enum):
    preventive_maintenance = "preventive_maintenance"
    full_service           = "full_service"
    on_demand              = "on_demand"
    custom                 = "custom"


class ContractStatus(str, enum.Enum):
    draft            = "draft"
    pending_approval = "pending_approval"
    active           = "active"
    suspended        = "suspended"
    expired          = "expired"
    cancelled        = "cancelled"
    renewed          = "renewed"


class BillingFrequency(str, enum.Enum):
    monthly     = "monthly"
    quarterly   = "quarterly"
    semi_annual = "semi_annual"
    annual      = "annual"
    per_service = "per_service"


class ServiceFrequency(str, enum.Enum):
    one_time    = "one_time"
    weekly      = "weekly"
    biweekly    = "biweekly"
    monthly     = "monthly"
    quarterly   = "quarterly"
    semi_annual = "semi_annual"
    annual      = "annual"


class Contract(Base):
    __tablename__ = 'contracts'

    id                    = Column(Integer, primary_key=True)
    organization_id       = Column(Integer, ForeignKey('organizations.id'), nullable=False)
    contract_number       = Column(String(20), unique=True, nullable=False, index=True)
    client_id             = Column(Integer, ForeignKey('clients.id'), nullable=False)
    division_id           = Column(Integer, ForeignKey('divisions.id'), nullable=True)
    title                 = Column(String(255), nullable=False)
    description           = Column(Text, nullable=True)
    contract_type         = Column(SAEnum(ContractType), nullable=False,
                                   default=ContractType.preventive_maintenance)
    status                = Column(SAEnum(ContractStatus), nullable=False,
                                   default=ContractStatus.draft)
    start_date            = Column(Date, nullable=False)
    end_date              = Column(Date, nullable=False)
    value                 = Column(Float, nullable=False, default=0.0)
    billing_frequency     = Column(SAEnum(BillingFrequency), nullable=False,
                                   default=BillingFrequency.monthly)
    auto_renew            = Column(Boolean, default=False, nullable=False)
    renewal_terms         = Column(Text, nullable=True)
    renewal_reminder_days = Column(Integer, default=30, nullable=False)
    terms_and_conditions  = Column(Text, nullable=True)
    internal_notes        = Column(Text, nullable=True)
    created_by            = Column(Integer, ForeignKey('users.id'), nullable=True)
    updated_by            = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at            = Column(DateTime, default=datetime.utcnow,
                                   onupdate=datetime.utcnow, nullable=False)

    # -- Relationships --
    client        = relationship('Client',    back_populates='contracts', lazy='select')
    division      = relationship('Division',  back_populates='contracts', lazy='select')
    creator       = relationship('User', foreign_keys=[created_by], lazy='select')
    updater       = relationship('User', foreign_keys=[updated_by], lazy='select')
    properties    = relationship('Property', secondary=contract_property,
                                  back_populates='contracts', lazy='select')
    slas          = relationship('SLA', secondary=contract_sla,
                                  back_populates='contracts', lazy='select')
    line_items    = relationship('ContractLineItem', back_populates='contract',
                                  cascade='all, delete-orphan', lazy='select')
    jobs          = relationship('Job', back_populates='contract', lazy='select')
    activity_logs = relationship('ContractActivityLog', back_populates='contract',
                                  cascade='all, delete-orphan', lazy='select',
                                  order_by='ContractActivityLog.created_at.desc()')
    attachments   = relationship('ContractAttachment', back_populates='contract',
                                  cascade='all, delete-orphan', lazy='select')

    # -- Helper properties --
    @property
    def is_expiring_soon(self):
        if not isinstance(self.status, ContractStatus):
            return False
        if self.status != ContractStatus.active:
            return False
        days_left = (self.end_date - date.today()).days
        return 0 <= days_left <= self.renewal_reminder_days

    @property
    def days_until_expiry(self):
        return (self.end_date - date.today()).days

    @property
    def total_line_item_value(self):
        return sum(li.quantity * li.unit_price for li in self.line_items)

    @property
    def status_value(self):
        """Return status as string regardless of whether it's an enum or string."""
        if isinstance(self.status, ContractStatus):
            return self.status.value
        return self.status

    @property
    def contract_type_value(self):
        if isinstance(self.contract_type, ContractType):
            return self.contract_type.value
        return self.contract_type

    @property
    def billing_frequency_value(self):
        if isinstance(self.billing_frequency, BillingFrequency):
            return self.billing_frequency.value
        return self.billing_frequency

    @staticmethod
    def generate_contract_number(db_session):
        """Generate next sequential contract number: CTR-YYYY-XXXX"""
        year = datetime.now(timezone.utc).year
        prefix = f"CTR-{year}-"
        last = (db_session.query(Contract)
                .filter(Contract.contract_number.like(f"{prefix}%"))
                .order_by(Contract.id.desc())
                .first())
        if last:
            seq = int(last.contract_number.split('-')[-1]) + 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"

    def log_activity(self, db_session, user_id, action, detail=None):
        log = ContractActivityLog(
            contract_id=self.id,
            user_id=user_id,
            action=action,
            detail=detail
        )
        db_session.add(log)

    def to_dict(self):
        return {
            'id': self.id,
            'organization_id': self.organization_id,
            'contract_number': self.contract_number,
            'client_id': self.client_id,
            'division_id': self.division_id,
            'title': self.title,
            'description': self.description,
            'contract_type': self.contract_type_value,
            'status': self.status_value,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'value': self.value,
            'billing_frequency': self.billing_frequency_value,
            'auto_renew': self.auto_renew,
            'renewal_terms': self.renewal_terms,
            'renewal_reminder_days': self.renewal_reminder_days,
            'terms_and_conditions': self.terms_and_conditions,
            'internal_notes': self.internal_notes,
            'total_line_item_value': self.total_line_item_value,
            'days_until_expiry': self.days_until_expiry,
            'is_expiring_soon': self.is_expiring_soon,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Contract {self.contract_number}: {self.title}>'


class ContractLineItem(Base):
    __tablename__ = 'contract_line_items'

    id                        = Column(Integer, primary_key=True)
    contract_id               = Column(Integer, ForeignKey('contracts.id'), nullable=False)
    service_type              = Column(String(255), nullable=False)
    description               = Column(Text, nullable=True)
    frequency                 = Column(SAEnum(ServiceFrequency), nullable=False,
                                       default=ServiceFrequency.annual)
    quantity                  = Column(Float, nullable=False, default=1.0)
    unit_price                = Column(Float, nullable=False, default=0.0)
    estimated_hours_per_visit = Column(Float, nullable=True)
    next_scheduled_date       = Column(Date, nullable=True)
    is_included               = Column(Boolean, default=True, nullable=False)
    sort_order                = Column(Integer, default=0, nullable=False)

    contract = relationship('Contract', back_populates='line_items')

    @property
    def line_total(self):
        return self.quantity * self.unit_price

    @property
    def frequency_value(self):
        if isinstance(self.frequency, ServiceFrequency):
            return self.frequency.value
        return self.frequency

    def calculate_next_scheduled_date(self, from_date=None):
        """Calculate next_scheduled_date based on frequency."""
        from dateutil.relativedelta import relativedelta
        base = from_date or self.next_scheduled_date or date.today()
        freq_map = {
            ServiceFrequency.weekly:      relativedelta(weeks=1),
            ServiceFrequency.biweekly:    relativedelta(weeks=2),
            ServiceFrequency.monthly:     relativedelta(months=1),
            ServiceFrequency.quarterly:   relativedelta(months=3),
            ServiceFrequency.semi_annual: relativedelta(months=6),
            ServiceFrequency.annual:      relativedelta(years=1),
            ServiceFrequency.one_time:    None,
        }
        delta = freq_map.get(self.frequency)
        if delta:
            return base + delta
        return None

    def to_dict(self):
        return {
            'id': self.id,
            'contract_id': self.contract_id,
            'service_type': self.service_type,
            'description': self.description,
            'frequency': self.frequency_value,
            'quantity': self.quantity,
            'unit_price': self.unit_price,
            'line_total': self.line_total,
            'estimated_hours_per_visit': self.estimated_hours_per_visit,
            'next_scheduled_date': self.next_scheduled_date.isoformat() if self.next_scheduled_date else None,
            'is_included': self.is_included,
            'sort_order': self.sort_order,
        }

    def __repr__(self):
        return f'<ContractLineItem {self.service_type} ({self.frequency})>'


class ContractActivityLog(Base):
    __tablename__ = 'contract_activity_logs'

    id          = Column(Integer, primary_key=True)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=False)
    user_id     = Column(Integer, ForeignKey('users.id'), nullable=True)
    action      = Column(String(255), nullable=False)
    detail      = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)

    contract = relationship('Contract', back_populates='activity_logs')
    user     = relationship('User', lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'contract_id': self.contract_id,
            'user_id': self.user_id,
            'action': self.action,
            'detail': self.detail,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<ContractActivityLog {self.action} @ {self.created_at}>'


class ContractAttachment(Base):
    __tablename__ = 'contract_attachments'

    id            = Column(Integer, primary_key=True)
    contract_id   = Column(Integer, ForeignKey('contracts.id'), nullable=False)
    filename      = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    file_size     = Column(Integer, nullable=True)
    mime_type     = Column(String(100), nullable=True)
    uploaded_by   = Column(Integer, ForeignKey('users.id'), nullable=True)
    uploaded_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    contract  = relationship('Contract', back_populates='attachments')
    uploader  = relationship('User', lazy='select')

    def to_dict(self):
        return {
            'id': self.id,
            'contract_id': self.contract_id,
            'filename': self.filename,
            'original_name': self.original_name,
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }

    def __repr__(self):
        return f'<ContractAttachment {self.original_name}>'
