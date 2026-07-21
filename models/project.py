"""Project model — top-level container for complex commercial work."""
import enum
from datetime import timezone, datetime, date
from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, Float,
    ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from .database import Base


class ProjectStatus(str, enum.Enum):
    planning   = "planning"
    approved   = "approved"
    active     = "active"
    on_hold    = "on_hold"
    completed  = "completed"
    closed     = "closed"
    cancelled  = "cancelled"


class ProjectPriority(str, enum.Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


class Project(Base):
    __tablename__ = 'projects'

    id                    = Column(Integer, primary_key=True)
    organization_id       = Column(Integer, ForeignKey('organizations.id'), nullable=False)
    project_number        = Column(String(20), unique=True, nullable=False, index=True)
    title                 = Column(String(200), nullable=False)
    description           = Column(Text, nullable=True)

    # Client & Location
    client_id             = Column(Integer, ForeignKey('clients.id'), nullable=False, index=True)
    property_id           = Column(Integer, ForeignKey('properties.id'), nullable=True)

    # Status & Priority
    status                = Column(String(20), nullable=False, default=ProjectStatus.planning.value, index=True)
    priority              = Column(String(20), nullable=False, default=ProjectPriority.medium.value)

    # Division
    division_id           = Column(Integer, ForeignKey('divisions.id'), nullable=True)

    # Timeline
    estimated_start_date  = Column(Date, nullable=True)
    estimated_end_date    = Column(Date, nullable=True)
    actual_start_date     = Column(Date, nullable=True)
    actual_end_date       = Column(Date, nullable=True)
    percent_complete      = Column(Integer, nullable=False, default=0)

    # Budget
    estimated_budget      = Column(Float, nullable=True, default=0)
    approved_budget       = Column(Float, nullable=True, default=0)

    # People
    project_manager_id    = Column(Integer, ForeignKey('users.id'), nullable=True)
    site_supervisor_id    = Column(Integer, ForeignKey('technicians.id'), nullable=True)
    client_contact_name   = Column(String(100), nullable=True)
    client_contact_phone  = Column(String(30), nullable=True)
    client_contact_email  = Column(String(150), nullable=True)

    # References
    contract_id           = Column(Integer, ForeignKey('contracts.id'), nullable=True)
    notes                 = Column(Text, nullable=True)

    # Audit
    created_by            = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at            = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at            = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    client           = relationship('Client', backref='projects', foreign_keys=[client_id])
    site_property    = relationship('Property', backref='projects', foreign_keys=[property_id])
    division         = relationship('Division', backref='projects', foreign_keys=[division_id])
    project_manager  = relationship('User', foreign_keys=[project_manager_id])
    site_supervisor  = relationship('Technician', foreign_keys=[site_supervisor_id])
    contract         = relationship('Contract', backref='projects', foreign_keys=[contract_id])
    creator          = relationship('User', foreign_keys=[created_by])
    expenses         = relationship('Expense', back_populates='project', foreign_keys='Expense.project_id', lazy='select')

    STATUS_LABELS = {
        'planning': 'Planning', 'approved': 'Approved', 'active': 'Active',
        'on_hold': 'On Hold', 'completed': 'Completed', 'closed': 'Closed',
        'cancelled': 'Cancelled',
    }

    STATUS_COLORS = {
        'planning': 'secondary', 'approved': 'info', 'active': 'accent',
        'on_hold': 'warning', 'completed': 'success', 'closed': 'secondary',
        'cancelled': 'danger',
    }

    PRIORITY_COLORS = {
        'low': 'secondary', 'medium': 'info', 'high': 'warning', 'critical': 'danger',
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, 'secondary')

    @property
    def priority_label(self):
        return (self.priority or 'medium').replace('_', ' ').title()

    @property
    def priority_color(self):
        return self.PRIORITY_COLORS.get(self.priority, 'secondary')

    @property
    def is_behind_schedule(self):
        if self.estimated_end_date and self.status in ('active', 'on_hold'):
            if date.today() > self.estimated_end_date:
                return True
            if self.estimated_start_date and self.estimated_end_date:
                total_days = (self.estimated_end_date - self.estimated_start_date).days
                if total_days > 0:
                    elapsed = (date.today() - self.estimated_start_date).days
                    expected_pct = min(100, int(elapsed / total_days * 100))
                    if self.percent_complete < expected_pct - 15:
                        return True
        return False

    @property
    def days_remaining(self):
        if self.estimated_end_date:
            return (self.estimated_end_date - date.today()).days
        return None

    @staticmethod
    def generate_project_number(db):
        """Generate next project number: PRJ-YYYY-XXXX."""
        year = datetime.now(timezone.utc).year
        prefix = f"PRJ-{year}-"
        last = db.query(Project).filter(
            Project.project_number.like(f"{prefix}%")
        ).order_by(Project.project_number.desc()).first()
        seq = 1
        if last:
            try:
                seq = int(last.project_number.split('-')[-1]) + 1
            except (ValueError, IndexError):
                pass
        return f"{prefix}{seq:04d}"

    def to_dict(self):
        return {
            'id': self.id,
            'project_number': self.project_number,
            'title': self.title,
            'status': self.status,
            'priority': self.priority,
            'percent_complete': self.percent_complete,
            'estimated_budget': float(self.estimated_budget or 0),
            'approved_budget': float(self.approved_budget or 0),
            'client_id': self.client_id,
            'division_id': self.division_id,
            'estimated_start_date': self.estimated_start_date.isoformat() if self.estimated_start_date else None,
            'estimated_end_date': self.estimated_end_date.isoformat() if self.estimated_end_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ProjectNote(Base):
    __tablename__ = 'project_notes'

    id         = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False, index=True)
    content    = Column(Text, nullable=False)
    note_type  = Column(String(30), nullable=False, default='general')
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    project = relationship('Project', backref='project_notes')
    author  = relationship('User', foreign_keys=[created_by])
