"""Job / Work Order model."""

import builtins
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, Float
from sqlalchemy.orm import relationship
import enum
from .database import Base


class JobStatus(enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    INVOICED = "invoiced"
    CANCELLED = "cancelled"


class Job(Base):
    __tablename__ = 'jobs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey('organizations.id'), nullable=False)
    division_id = Column(Integer, ForeignKey('divisions.id'), nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False)
    property_id = Column(Integer, ForeignKey('properties.id'))
    quote_id = Column(Integer, ForeignKey('quotes.id'))
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=True, index=True)
    project_id  = Column(Integer, ForeignKey('projects.id'), nullable=True, index=True)

    # Job details
    job_number = Column(String(50), unique=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    status = Column(String(20), default=JobStatus.DRAFT.value, index=True)
    priority = Column(String(20), default='normal')  # low, normal, high, urgent

    # Scheduling
    scheduled_date = Column(DateTime)
    scheduled_end = Column(DateTime)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # Assignment
    assigned_technician_id = Column(Integer, ForeignKey('technicians.id'))

    # Financial
    estimated_amount = Column(Float, default=0)
    actual_amount = Column(Float, default=0)

    # Job type
    job_type = Column(String(50))  # service_call, maintenance, installation, repair, inspection, emergency

    # Multi-phase support
    is_multi_phase         = Column(Boolean, default=False, nullable=False)
    original_estimated_cost = Column(Float, nullable=True)
    adjusted_estimated_cost = Column(Float, nullable=True)
    project_manager_notes  = Column(Text, nullable=True)

    # SLA tracking
    sla_id                  = Column(Integer, ForeignKey('slas.id'), nullable=True)
    sla_response_deadline   = Column(DateTime, nullable=True)
    sla_resolution_deadline = Column(DateTime, nullable=True)
    actual_response_time    = Column(DateTime, nullable=True)   # when status -> in_progress
    actual_resolution_time  = Column(DateTime, nullable=True)   # when status -> completed
    sla_response_met        = Column(Boolean, nullable=True)
    sla_resolution_met      = Column(Boolean, nullable=True)

    # Portal / source tracking
    source                   = Column(String(30), nullable=True)  # portal_request, internal, phone, etc.
    portal_contact_name      = Column(String(200), nullable=True)
    portal_contact_phone     = Column(String(30), nullable=True)
    portal_access_instructions = Column(Text, nullable=True)

    # Tracking
    created_by_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    division = relationship("Division", back_populates="jobs")
    client = relationship("Client", back_populates="jobs")
    property = relationship("Property", back_populates="jobs")
    quote = relationship("Quote", foreign_keys=[quote_id])
    technician = relationship("Technician", back_populates="jobs")
    notes = relationship("JobNote", back_populates="job", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="job")
    contract = relationship("Contract", back_populates="jobs", lazy='select')
    project = relationship("Project", backref="jobs", foreign_keys=[project_id], lazy='select')
    sla = relationship("SLA", lazy='select')
    phases = relationship("JobPhase", back_populates="job", cascade="all, delete-orphan",
                          order_by="JobPhase.sort_order, JobPhase.phase_number", lazy='select')
    change_orders = relationship("ChangeOrder", back_populates="job", cascade="all, delete-orphan",
                                  order_by="ChangeOrder.created_at", lazy='select')
    materials = relationship("JobMaterial", back_populates="job", cascade="all, delete-orphan", lazy='select')

    # Warranty / Callback tracking
    is_callback = Column(Boolean, default=False, nullable=False)
    is_warranty_work = Column(Boolean, default=False, nullable=False)
    original_job_id = Column(Integer, ForeignKey('jobs.id'), nullable=True)

    warranties = relationship("Warranty", foreign_keys="Warranty.job_id", back_populates="job", lazy='select')
    warranty_claims = relationship("WarrantyClaim", foreign_keys="WarrantyClaim.job_id", lazy='select')
    originated_callbacks = relationship("Callback", foreign_keys="Callback.original_job_id", back_populates="original_job", lazy='select')
    callback_record = relationship("Callback", foreign_keys="Callback.callback_job_id", back_populates="callback_job", uselist=False, lazy='select')
    expenses = relationship("Expense", back_populates="job", foreign_keys="Expense.job_id", lazy='select')
    original_job = relationship("Job", foreign_keys=[original_job_id], remote_side='Job.id', backref="callback_jobs", lazy='select')
    feedback_surveys = relationship("FeedbackSurvey", back_populates="job", cascade="all, delete-orphan", lazy='select')

    # -- Phase helper properties --

    @builtins.property
    def phase_count(self):
        return len(self.phases)

    @builtins.property
    def completed_phase_count(self):
        return sum(1 for p in self.phases if p.is_complete)

    @builtins.property
    def percent_complete(self):
        if not self.phases or self.phase_count == 0:
            return 0
        return round((self.completed_phase_count / self.phase_count) * 100)

    @builtins.property
    def phase_progress(self):
        """Returns (completed_count, total_count, percentage)."""
        return self.completed_phase_count, self.phase_count, self.percent_complete

    @builtins.property
    def total_change_orders(self):
        return sum(1 for co in self.change_orders if co.status == 'approved')

    @builtins.property
    def total_change_order_value(self):
        return sum(co.cost_difference for co in self.change_orders if co.status == 'approved')

    @builtins.property
    def pending_change_orders_count(self):
        return sum(1 for co in self.change_orders if co.status in ('submitted', 'pending_approval'))

    @builtins.property
    def derived_status_from_phases(self):
        """Derive job status from phase statuses. Returns None if not multi-phase."""
        if not self.is_multi_phase or not self.phases:
            return None
        statuses = {p.status for p in self.phases}
        if 'in_progress' in statuses:
            return 'in_progress'
        if all(s in ('completed', 'skipped') for s in statuses):
            return 'completed'
        if 'on_hold' in statuses:
            return 'on_hold'
        if 'scheduled' in statuses:
            return 'scheduled'
        return 'scheduled'

    @builtins.property
    def has_on_hold_phase(self):
        return any(p.status == 'on_hold' for p in self.phases)

    @builtins.property
    def current_contract_value(self):
        """Original cost + approved change order deltas."""
        base = float(self.original_estimated_cost or self.estimated_amount or 0)
        return base + self.total_change_order_value

    # -- SLA helper properties --

    @builtins.property
    def sla_response_at_risk(self):
        """Response deadline within 80% consumed but not yet met."""
        if not self.sla_response_deadline or self.actual_response_time:
            return False
        now = datetime.now(timezone.utc)
        if now >= self.sla_response_deadline:
            return False
        total = (self.sla_response_deadline - self.created_at).total_seconds()
        elapsed = (now - self.created_at).total_seconds()
        return total > 0 and (elapsed / total) >= 0.80

    @builtins.property
    def sla_response_breached(self):
        if not self.sla_response_deadline:
            return False
        if self.actual_response_time:
            return self.actual_response_time > self.sla_response_deadline
        return datetime.now(timezone.utc) > self.sla_response_deadline

    @builtins.property
    def sla_resolution_at_risk(self):
        if not self.sla_resolution_deadline or self.actual_resolution_time:
            return False
        now = datetime.now(timezone.utc)
        if now >= self.sla_resolution_deadline:
            return False
        total = (self.sla_resolution_deadline - self.created_at).total_seconds()
        elapsed = (now - self.created_at).total_seconds()
        return total > 0 and (elapsed / total) >= 0.80

    @builtins.property
    def sla_resolution_breached(self):
        if not self.sla_resolution_deadline:
            return False
        if self.actual_resolution_time:
            return self.actual_resolution_time > self.sla_resolution_deadline
        return datetime.now(timezone.utc) > self.sla_resolution_deadline

    @builtins.property
    def sla_status(self):
        """Returns: 'breached', 'at_risk', 'on_track', 'met', or None"""
        if not self.sla_id:
            return None
        if self.sla_resolution_breached or self.sla_response_breached:
            return 'breached'
        if self.sla_resolution_at_risk or self.sla_response_at_risk:
            return 'at_risk'
        if self.actual_resolution_time:
            return 'met'
        return 'on_track'

    def to_dict(self):
        return {
            'id': self.id,
            'job_number': self.job_number,
            'title': self.title,
            'description': self.description,
            'status': self.status,
            'priority': self.priority,
            'division_id': self.division_id,
            'client_id': self.client_id,
            'property_id': self.property_id,
            'job_type': self.job_type,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'scheduled_end': self.scheduled_end.isoformat() if self.scheduled_end else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'assigned_technician_id': self.assigned_technician_id,
            'estimated_amount': self.estimated_amount,
            'actual_amount': self.actual_amount,
            'contract_id': self.contract_id,
            'sla_id': self.sla_id,
            'sla_response_deadline': self.sla_response_deadline.isoformat() if self.sla_response_deadline else None,
            'sla_resolution_deadline': self.sla_resolution_deadline.isoformat() if self.sla_resolution_deadline else None,
            'actual_response_time': self.actual_response_time.isoformat() if self.actual_response_time else None,
            'actual_resolution_time': self.actual_resolution_time.isoformat() if self.actual_resolution_time else None,
            'sla_response_met': self.sla_response_met,
            'sla_resolution_met': self.sla_resolution_met,
            'sla_status': self.sla_status,
            'is_multi_phase': self.is_multi_phase,
            'phase_count': self.phase_count,
            'completed_phase_count': self.completed_phase_count,
            'percent_complete': self.percent_complete,
            'total_change_orders': self.total_change_orders,
            'total_change_order_value': self.total_change_order_value,
            'pending_change_orders_count': self.pending_change_orders_count,
            'current_contract_value': self.current_contract_value,
            'original_estimated_cost': float(self.original_estimated_cost or 0),
            'source': self.source,
            'portal_contact_name': self.portal_contact_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class JobNote(Base):
    __tablename__ = 'job_notes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey('jobs.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))
    content = Column(Text, nullable=False)
    note_type = Column(String(20), default='note')  # note, status_change, photo, internal
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    job = relationship("Job", back_populates="notes")
    author = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            'id': self.id,
            'job_id': self.job_id,
            'content': self.content,
            'note_type': self.note_type,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'author_name': self.author.full_name if self.author else 'System',
            'author_initials': (
                (self.author.first_name[0] + (self.author.last_name[0] if self.author.last_name else ''))
                if self.author and self.author.first_name else '?'
            ).upper(),
        }
