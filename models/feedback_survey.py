"""Feedback Survey models — customer satisfaction tracking."""
import secrets
from datetime import datetime, timezone, timedelta
from sqlalchemy import (Column, Integer, String, Text, Boolean,
                        DateTime, Float, ForeignKey, Index)
from sqlalchemy.orm import relationship
from .database import Base


def _generate_token():
    return secrets.token_urlsafe(32)


class SurveyTemplate(Base):
    __tablename__ = 'survey_templates'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # Question toggles
    include_quality = Column(Boolean, default=True, nullable=False)
    include_punctuality = Column(Boolean, default=True, nullable=False)
    include_communication = Column(Boolean, default=True, nullable=False)
    include_professionalism = Column(Boolean, default=True, nullable=False)
    include_value = Column(Boolean, default=True, nullable=False)
    include_nps = Column(Boolean, default=True, nullable=False)
    include_recommend = Column(Boolean, default=True, nullable=False)
    include_comments = Column(Boolean, default=True, nullable=False)
    include_what_went_well = Column(Boolean, default=True, nullable=False)
    include_what_could_improve = Column(Boolean, default=True, nullable=False)
    custom_questions = Column(Text, nullable=True)  # JSON string: [{label, type, required}]

    is_default = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    surveys = relationship('FeedbackSurvey', back_populates='template',
                           foreign_keys='FeedbackSurvey.template_id')
    creator = relationship('User', foreign_keys=[created_by])

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class FeedbackSurvey(Base):
    __tablename__ = 'feedback_surveys'

    id = Column(Integer, primary_key=True)
    survey_number = Column(String(20), unique=True, nullable=False)

    # Core FKs
    job_id = Column(Integer, ForeignKey('jobs.id'), nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False)
    technician_id = Column(Integer, ForeignKey('technicians.id'), nullable=True)
    template_id = Column(Integer, ForeignKey('survey_templates.id'), nullable=True)

    # Ratings 1-5
    overall_rating = Column(Integer, nullable=True)
    quality_rating = Column(Integer, nullable=True)
    punctuality_rating = Column(Integer, nullable=True)
    communication_rating = Column(Integer, nullable=True)
    professionalism_rating = Column(Integer, nullable=True)
    value_rating = Column(Integer, nullable=True)

    # Feedback
    comments = Column(Text, nullable=True)
    would_recommend = Column(Boolean, nullable=True)
    what_went_well = Column(Text, nullable=True)
    what_could_improve = Column(Text, nullable=True)

    # NPS 0-10
    nps_score = Column(Integer, nullable=True)

    # Status lifecycle: sent | opened | completed | expired | cancelled
    status = Column(String(20), default='sent', nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)
    opened_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    token = Column(String(64), unique=True, nullable=False, default=_generate_token)
    expires_at = Column(DateTime, nullable=True)

    # Reminder
    reminder_sent = Column(Boolean, default=False)
    reminder_sent_at = Column(DateTime, nullable=True)

    # Response metadata
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    # Admin fields
    is_public = Column(Boolean, default=False)
    internal_notes = Column(Text, nullable=True)
    follow_up_required = Column(Boolean, default=False)
    follow_up_notes = Column(Text, nullable=True)
    follow_up_completed = Column(Boolean, default=False)

    # Google review tracking
    google_review_link_clicked = Column(Boolean, default=False)
    google_review_clicked_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    job = relationship('Job', back_populates='feedback_surveys')
    client = relationship('Client', back_populates='feedback_surveys')
    technician = relationship('Technician', back_populates='feedback_surveys')
    template = relationship('SurveyTemplate', back_populates='surveys',
                            foreign_keys=[template_id])

    # Indexes
    __table_args__ = (
        Index('ix_feedback_surveys_job_id', 'job_id'),
        Index('ix_feedback_surveys_client_id', 'client_id'),
        Index('ix_feedback_surveys_token', 'token'),
        Index('ix_feedback_surveys_status', 'status'),
    )

    @property
    def nps_category(self):
        if self.nps_score is None:
            return None
        if self.nps_score <= 6:
            return 'detractor'
        elif self.nps_score <= 8:
            return 'passive'
        return 'promoter'

    @property
    def response_time_hours(self):
        if self.completed_at and self.sent_at:
            return round((self.completed_at - self.sent_at).total_seconds() / 3600, 1)
        return None

    @property
    def is_expired(self):
        if self.expires_at:
            now = datetime.now(timezone.utc)
            expires = self.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return now > expires
        return False

    @property
    def avg_category_rating(self):
        vals = [v for v in [
            self.quality_rating, self.punctuality_rating,
            self.communication_rating, self.professionalism_rating,
            self.value_rating,
        ] if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    @property
    def star_display(self):
        r = self.overall_rating or 0
        return '\u2605' * r + '\u2606' * (5 - r)

    @classmethod
    def generate_number(cls, session):
        from datetime import date
        year = date.today().year
        count = session.query(cls).filter(
            cls.survey_number.like(f'FB-{year}-%')
        ).count() + 1
        return f'FB-{year}-{count:04d}'

    def to_dict(self):
        return {
            'id': self.id, 'survey_number': self.survey_number,
            'job_id': self.job_id, 'client_id': self.client_id,
            'overall_rating': self.overall_rating,
            'nps_score': self.nps_score, 'nps_category': self.nps_category,
            'status': self.status, 'star_display': self.star_display,
            'avg_category_rating': self.avg_category_rating,
            'would_recommend': self.would_recommend,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }
