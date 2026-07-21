"""Permit management utilities."""

from datetime import timezone, datetime, date
from models.permit import Permit


def create_permit(db, form_data, created_by_id):
    """Create a permit from form data. Caller must commit."""
    permit = Permit(
        job_id=int(form_data['job_id']),
        phase_id=int(form_data['phase_id']) if form_data.get('phase_id') else None,
        permit_type=form_data.get('permit_type', 'other'),
        permit_number=form_data.get('permit_number', '').strip() or None,
        description=form_data.get('description', '').strip() or None,
        issuing_authority=form_data.get('issuing_authority', '').strip() or None,
        status=form_data.get('status', 'not_applied'),
        application_date=_parse_date(form_data.get('application_date')),
        issue_date=_parse_date(form_data.get('issue_date')),
        expiry_date=_parse_date(form_data.get('expiry_date')),
        cost=float(form_data['cost']) if form_data.get('cost') else None,
        conditions=form_data.get('conditions', '').strip() or None,
        inspector_name=form_data.get('inspector_name', '').strip() or None,
        inspector_phone=form_data.get('inspector_phone', '').strip() or None,
        notes=form_data.get('notes', '').strip() or None,
        created_by=created_by_id,
    )
    db.add(permit)
    db.flush()
    return permit


def update_permit(db, permit, form_data):
    """Update permit from form data."""
    permit.permit_number = form_data.get('permit_number', '').strip() or permit.permit_number
    permit.permit_type = form_data.get('permit_type', permit.permit_type)
    permit.description = form_data.get('description', '').strip() or permit.description
    permit.issuing_authority = form_data.get('issuing_authority', '').strip() or permit.issuing_authority
    permit.status = form_data.get('status', permit.status)
    permit.application_date = _parse_date(form_data.get('application_date')) or permit.application_date
    permit.issue_date = _parse_date(form_data.get('issue_date')) or permit.issue_date
    permit.expiry_date = _parse_date(form_data.get('expiry_date')) or permit.expiry_date
    if form_data.get('cost'):
        permit.cost = float(form_data['cost'])
    permit.conditions = form_data.get('conditions', '').strip() or permit.conditions
    permit.inspector_name = form_data.get('inspector_name', '').strip() or permit.inspector_name
    permit.inspector_phone = form_data.get('inspector_phone', '').strip() or permit.inspector_phone
    permit.notes = form_data.get('notes', '').strip() or permit.notes
    if form_data.get('phase_id'):
        permit.phase_id = int(form_data['phase_id'])
    permit.updated_at = datetime.now(timezone.utc)
    return permit


def get_blocking_permits(db, job_id):
    """Get permits that are blocking job/phase completion."""
    return db.query(Permit).filter(
        Permit.job_id == job_id,
        Permit.status.in_(Permit.BLOCKING_STATUSES),
    ).all()


def get_expiring_permits(db, days=30):
    """Get permits expiring within N days."""
    cutoff = date.today()
    from datetime import timezone, timedelta
    end = cutoff + timedelta(days=days)
    return db.query(Permit).filter(
        Permit.expiry_date.isnot(None),
        Permit.expiry_date >= cutoff,
        Permit.expiry_date <= end,
    ).order_by(Permit.expiry_date).all()


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except ValueError:
        return None
