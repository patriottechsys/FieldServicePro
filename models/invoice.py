"""Invoice and Payment models."""

from datetime import timezone, datetime, date, timedelta
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Text, Float, Boolean
from sqlalchemy.orm import relationship
import enum
from .database import Base


class InvoiceStatus(enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    VIEWED = "viewed"
    PARTIAL = "partial"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class ApprovalStatus(str, enum.Enum):
    not_required = "not_required"
    pending      = "pending"
    approved     = "approved"
    rejected     = "rejected"


class Invoice(Base):
    __tablename__ = 'invoices'

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey('organizations.id'), nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False)
    job_id = Column(Integer, ForeignKey('jobs.id'))
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True, index=True)

    invoice_number = Column(String(50), unique=True, index=True)
    status = Column(String(20), default=InvoiceStatus.DRAFT.value, index=True)

    # Financial
    subtotal = Column(Float, default=0)
    tax_rate = Column(Float, default=13.0)
    tax_amount = Column(Float, default=0)
    total = Column(Float, default=0)
    amount_paid = Column(Float, default=0)
    balance_due = Column(Float, default=0)

    # Dates
    issued_date = Column(DateTime)
    due_date = Column(DateTime)
    paid_date = Column(DateTime)

    notes = Column(Text)
    created_by_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Commercial billing fields
    po_id              = Column(Integer, ForeignKey('purchase_orders.id'), nullable=True, index=True)
    po_number_display  = Column(String(100), nullable=True)
    payment_terms      = Column(String(20), nullable=True)
    cost_code          = Column(String(100), nullable=True)
    department         = Column(String(100), nullable=True)
    billing_contact    = Column(String(200), nullable=True)

    # Approval workflow
    approval_status    = Column(String(20), nullable=False, default=ApprovalStatus.not_required.value, index=True)
    approved_by        = Column(Integer, ForeignKey('users.id'), nullable=True)
    approved_at        = Column(DateTime, nullable=True)
    rejection_reason   = Column(Text, nullable=True)

    # Late fees
    late_fee_rate      = Column(Float, nullable=True)
    late_fee_applied   = Column(Float, nullable=True, default=0)
    late_fee_date      = Column(Date, nullable=True)

    # Relationships
    client = relationship("Client", back_populates="invoices")
    job = relationship("Job", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")
    purchase_order = relationship("PurchaseOrder", back_populates="invoices")
    project = relationship("Project", backref="invoices", foreign_keys=[project_id])
    approver = relationship("User", foreign_keys=[approved_by])

    @property
    def is_overdue(self):
        if self.status in ('paid', 'void'):
            return False
        if self.due_date:
            due = self.due_date.date() if hasattr(self.due_date, 'date') else self.due_date
            return date.today() > due
        return False

    @property
    def is_commercial(self):
        return self.client and self.client.client_type == 'commercial'

    @property
    def days_outstanding(self):
        """Days since invoice was issued."""
        if not self.issued_date:
            return 0
        ref = self.issued_date.date() if hasattr(self.issued_date, 'date') else self.issued_date
        return (date.today() - ref).days

    @property
    def days_overdue(self):
        """Days past due_date. Negative means not yet due."""
        if not self.due_date:
            return 0
        due = self.due_date.date() if hasattr(self.due_date, 'date') else self.due_date
        return (date.today() - due).days

    @property
    def aging_bucket(self):
        """Returns string bucket for aging reports."""
        days = self.days_overdue
        if days <= 0:
            return 'current'
        elif days <= 30:
            return '1_30'
        elif days <= 60:
            return '31_60'
        elif days <= 90:
            return '61_90'
        else:
            return '90_plus'

    def calculate_due_date(self):
        """Calculate due_date from issued_date and payment_terms."""
        terms = self.payment_terms
        ref_date = self.issued_date
        if ref_date is None:
            ref_date = datetime.now(timezone.utc)
        if hasattr(ref_date, 'date'):
            ref_date = ref_date.date()

        days_map = {
            'due_on_receipt': 0, 'net_15': 15, 'net_30': 30,
            'net_45': 45, 'net_60': 60, 'net_90': 90,
        }
        if terms in days_map:
            self.due_date = ref_date + timedelta(days=days_map[terms])
        elif terms == 'custom' and self.client and self.client.custom_payment_days:
            self.due_date = ref_date + timedelta(days=self.client.custom_payment_days)
        elif not self.due_date:
            self.due_date = ref_date + timedelta(days=30)

    def to_dict(self):
        return {
            'id': self.id,
            'invoice_number': self.invoice_number,
            'status': self.status,
            'client_id': self.client_id,
            'job_id': self.job_id,
            'subtotal': self.subtotal,
            'tax_rate': self.tax_rate,
            'tax_amount': self.tax_amount,
            'total': self.total,
            'amount_paid': self.amount_paid,
            'balance_due': self.balance_due,
            'issued_date': self.issued_date.isoformat() if self.issued_date else None,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'is_overdue': self.is_overdue,
            'po_id': self.po_id,
            'po_number_display': self.po_number_display,
            'payment_terms': self.payment_terms,
            'cost_code': self.cost_code,
            'department': self.department,
            'billing_contact': self.billing_contact,
            'approval_status': self.approval_status,
            'late_fee_applied': self.late_fee_applied,
            'days_overdue': self.days_overdue,
            'aging_bucket': self.aging_bucket,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class InvoiceItem(Base):
    __tablename__ = 'invoice_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey('invoices.id'), nullable=False)
    description = Column(String(500), nullable=False)
    quantity = Column(Float, default=1)
    unit_price = Column(Float, default=0)
    total = Column(Float, default=0)
    sort_order = Column(Integer, default=0)

    invoice = relationship("Invoice", back_populates="items")

    def to_dict(self):
        return {
            'id': self.id,
            'description': self.description,
            'quantity': self.quantity,
            'unit_price': self.unit_price,
            'total': self.total
        }


class Payment(Base):
    __tablename__ = 'payments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey('invoices.id'), nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(String(50))  # cash, cheque, e-transfer, credit_card
    reference_number = Column(String(100))
    notes = Column(Text)
    payment_date = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    invoice = relationship("Invoice", back_populates="payments")

    def to_dict(self):
        return {
            'id': self.id,
            'amount': self.amount,
            'payment_method': self.payment_method,
            'reference_number': self.reference_number,
            'payment_date': self.payment_date.isoformat() if self.payment_date else None
        }
