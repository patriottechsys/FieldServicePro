"""Time Tracking models: TimeEntry and ActiveClock."""
from datetime import timezone, datetime, timedelta
from sqlalchemy import (
    Column, Integer, String, Text, Date, Time, DateTime,
    Boolean, Float, ForeignKey, Index
)
from sqlalchemy.orm import relationship
from .database import Base


class TimeEntry(Base):
    __tablename__ = 'time_entries'

    id              = Column(Integer, primary_key=True)
    technician_id   = Column(Integer, ForeignKey('technicians.id'), nullable=False, index=True)
    job_id          = Column(Integer, ForeignKey('jobs.id'), nullable=False, index=True)
    phase_id        = Column(Integer, ForeignKey('job_phases.id'), nullable=True)
    project_id      = Column(Integer, ForeignKey('projects.id'), nullable=True, index=True)

    # Time data
    entry_type      = Column(String(30), nullable=False, default='regular')
    # Types: regular, overtime, double_time, travel, break, callback, warranty
    date            = Column(Date, nullable=False, index=True)
    start_time      = Column(Time, nullable=True)
    end_time        = Column(Time, nullable=True)
    duration_hours  = Column(Float, nullable=False, default=0)

    # Billing
    billable        = Column(Boolean, nullable=False, default=True)
    hourly_rate     = Column(Float, nullable=False, default=0)
    labor_cost      = Column(Float, nullable=False, default=0)
    billable_rate   = Column(Float, nullable=True)
    billable_amount = Column(Float, nullable=True)

    # Details
    description     = Column(Text, nullable=True)

    # Workflow
    status          = Column(String(20), nullable=False, default='draft', index=True)
    # Statuses: draft, submitted, approved, rejected, exported
    approved_by     = Column(Integer, ForeignKey('users.id'), nullable=True)
    approved_at     = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    exported_at     = Column(DateTime, nullable=True)

    # Metadata
    source          = Column(String(20), nullable=False, default='manual')
    # Sources: manual, clock_in_out, system
    created_by      = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at      = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at      = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    technician = relationship('Technician', backref='time_entries')
    job        = relationship('Job', backref='time_entries')
    phase      = relationship('JobPhase', backref='time_entries')
    project    = relationship('Project', backref='time_entries')
    approver   = relationship('User', foreign_keys=[approved_by])
    creator    = relationship('User', foreign_keys=[created_by])

    ENTRY_TYPES = [
        ('regular', 'Regular'), ('overtime', 'Overtime'), ('double_time', 'Double Time'),
        ('travel', 'Travel'), ('break', 'Break'), ('callback', 'Callback'), ('warranty', 'Warranty'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved'),
        ('rejected', 'Rejected'), ('exported', 'Exported'),
    ]

    STATUS_COLORS = {
        'draft': 'secondary', 'submitted': 'info', 'approved': 'success',
        'rejected': 'danger', 'exported': 'accent',
    }

    @property
    def type_display(self):
        return dict(self.ENTRY_TYPES).get(self.entry_type, self.entry_type)

    @property
    def status_display(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, 'secondary')

    @property
    def is_editable(self):
        return self.status in ('draft', 'rejected')

    def compute_costs(self):
        """Recompute labor_cost and billable_amount."""
        dur = float(self.duration_hours or 0)
        self.labor_cost = round(dur * float(self.hourly_rate or 0), 2)
        if self.billable and self.billable_rate:
            self.billable_amount = round(dur * float(self.billable_rate), 2)
        else:
            self.billable_amount = 0

    def to_dict(self):
        return {
            'id': self.id, 'technician_id': self.technician_id,
            'job_id': self.job_id, 'date': self.date.isoformat() if self.date else None,
            'entry_type': self.entry_type, 'duration_hours': self.duration_hours,
            'labor_cost': self.labor_cost, 'billable_amount': self.billable_amount,
            'status': self.status, 'description': self.description,
        }


class ActiveClock(Base):
    __tablename__ = 'active_clocks'

    id              = Column(Integer, primary_key=True)
    technician_id   = Column(Integer, ForeignKey('technicians.id'), nullable=False, unique=True, index=True)
    job_id          = Column(Integer, ForeignKey('jobs.id'), nullable=False)
    phase_id        = Column(Integer, ForeignKey('job_phases.id'), nullable=True)
    clock_in_time   = Column(DateTime, nullable=False, default=datetime.utcnow)
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime, nullable=False, default=datetime.utcnow)

    technician = relationship('Technician', backref='active_clock')
    job        = relationship('Job', backref='active_clocks')
    phase      = relationship('JobPhase')

    def elapsed_seconds(self):
        return (datetime.now(timezone.utc) - self.clock_in_time).total_seconds()

    def elapsed_display(self):
        secs = int(self.elapsed_seconds())
        h, remainder = divmod(secs, 3600)
        m, _ = divmod(remainder, 60)
        return f"{h}h {m:02d}m"
