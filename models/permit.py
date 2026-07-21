"""Permit tracking model."""
import json
from datetime import timezone, datetime, date, timedelta
from sqlalchemy import Column, Integer, String, Text, Float, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base


class Permit(Base):
    __tablename__ = 'permits'

    id                = Column(Integer, primary_key=True)
    permit_number     = Column(String(100), nullable=True)
    job_id            = Column(Integer, ForeignKey('jobs.id'), nullable=False, index=True)
    project_id        = Column(Integer, ForeignKey('projects.id'), nullable=True, index=True)
    phase_id          = Column(Integer, ForeignKey('job_phases.id'), nullable=True)

    permit_type       = Column(String(50), nullable=False, default='other')
    description       = Column(Text, nullable=True)
    issuing_authority = Column(String(200), nullable=True)

    status            = Column(String(50), nullable=False, default='not_applied')

    application_date  = Column(Date, nullable=True)
    issue_date        = Column(Date, nullable=True)
    expiry_date       = Column(Date, nullable=True)
    cost              = Column(Float, nullable=True)

    conditions        = Column(Text, nullable=True)
    inspector_name    = Column(String(200), nullable=True)
    inspector_phone   = Column(String(50), nullable=True)
    inspection_dates  = Column(Text, nullable=True)  # JSON
    notes             = Column(Text, nullable=True)

    created_by        = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at        = Column(DateTime, default=datetime.utcnow)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    job     = relationship('Job', backref='permits')
    phase   = relationship('JobPhase', backref='permits', foreign_keys=[phase_id])
    creator = relationship('User', foreign_keys=[created_by])

    PERMIT_TYPES = [
        ('building', 'Building'), ('electrical', 'Electrical'),
        ('plumbing', 'Plumbing'), ('mechanical', 'Mechanical'),
        ('fire', 'Fire'), ('excavation', 'Excavation'),
        ('environmental', 'Environmental'), ('occupancy', 'Occupancy'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('not_applied', 'Not Applied'), ('application_submitted', 'Application Submitted'),
        ('approved', 'Approved'), ('active', 'Active'),
        ('inspection_required', 'Inspection Required'),
        ('inspection_passed', 'Inspection Passed'),
        ('inspection_failed', 'Inspection Failed'),
        ('expired', 'Expired'), ('revoked', 'Revoked'),
    ]

    STATUS_COLORS = {
        'not_applied': 'secondary', 'application_submitted': 'active',
        'approved': 'primary', 'active': 'success',
        'inspection_required': 'warning', 'inspection_passed': 'success',
        'inspection_failed': 'danger', 'expired': 'draft', 'revoked': 'danger',
    }

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, 'secondary')

    @property
    def status_display(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    @property
    def type_display(self):
        return dict(self.PERMIT_TYPES).get(self.permit_type, self.permit_type)

    @property
    def is_expired(self):
        if not self.expiry_date:
            return False
        return self.expiry_date < date.today()

    @property
    def is_expiring_soon(self):
        if not self.expiry_date:
            return False
        return date.today() <= self.expiry_date <= date.today() + timedelta(days=14)

    @property
    def blocks_completion(self):
        return self.status in ('inspection_required', 'inspection_failed')

    @property
    def inspection_history(self):
        if not self.inspection_dates:
            return []
        try:
            return json.loads(self.inspection_dates)
        except (json.JSONDecodeError, TypeError):
            return []

    def add_inspection(self, inspection_date, result, inspector=None, notes=None):
        history = self.inspection_history
        history.append({
            'date': inspection_date if isinstance(inspection_date, str) else inspection_date.isoformat(),
            'result': result,
            'inspector': inspector or self.inspector_name,
            'notes': notes,
            'recorded_at': datetime.now(timezone.utc).isoformat(),
        })
        self.inspection_dates = json.dumps(history)
        if result == 'passed':
            self.status = 'inspection_passed'
        elif result == 'failed':
            self.status = 'inspection_failed'

    @staticmethod
    def get_expiring_soon(db, days=14):
        threshold = date.today() + timedelta(days=days)
        return db.query(Permit).filter(
            Permit.expiry_date.isnot(None),
            Permit.expiry_date <= threshold,
            Permit.expiry_date >= date.today(),
            Permit.status.notin_(['expired', 'revoked', 'inspection_passed']),
        ).all()

    @staticmethod
    def get_needing_inspection(db):
        return db.query(Permit).filter(
            Permit.status.in_(['inspection_required', 'inspection_failed'])
        ).all()

    @staticmethod
    def get_blocking_permits(db, job_id):
        return db.query(Permit).filter_by(job_id=job_id).filter(
            Permit.status.in_(['inspection_required', 'inspection_failed'])
        ).all()

    def to_dict(self):
        return {
            'id': self.id, 'permit_number': self.permit_number,
            'job_id': self.job_id, 'phase_id': self.phase_id,
            'permit_type': self.permit_type, 'type_display': self.type_display,
            'status': self.status, 'status_display': self.status_display,
            'status_color': self.status_color,
            'issuing_authority': self.issuing_authority,
            'application_date': self.application_date.isoformat() if self.application_date else None,
            'issue_date': self.issue_date.isoformat() if self.issue_date else None,
            'expiry_date': self.expiry_date.isoformat() if self.expiry_date else None,
            'cost': float(self.cost or 0),
            'blocks_completion': self.blocks_completion,
            'is_expired': self.is_expired,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<Permit {self.id}: {self.permit_type} - {self.status}>'
