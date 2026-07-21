"""
Phase management utilities — create, update, reorder, delete, cost sync.
All functions take an open db session. Caller must commit.
"""
from datetime import timezone, datetime
from sqlalchemy import func
from models.job_phase import JobPhase
from models.job import Job


def get_next_phase_number(db, job_id):
    last = db.query(func.max(JobPhase.phase_number)).filter_by(job_id=job_id).scalar()
    return (last or 0) + 1


def get_next_sort_order(db, job_id):
    last = db.query(func.max(JobPhase.sort_order)).filter_by(job_id=job_id).scalar()
    return (last or 0) + 10


def create_phase(db, job, form_data):
    """Create a new JobPhase for the given job."""
    phase_number = get_next_phase_number(db, job.id)
    sort_order = get_next_sort_order(db, job.id)

    phase = JobPhase(
        job_id=job.id,
        phase_number=phase_number,
        sort_order=sort_order,
        title=form_data.get('title', f'Phase {phase_number}'),
        description=form_data.get('description'),
        scheduled_start_date=_parse_date(form_data.get('scheduled_start_date')),
        scheduled_end_date=_parse_date(form_data.get('scheduled_end_date')),
        assigned_technician_id=_int_or_none(form_data.get('assigned_technician_id')),
        estimated_hours=_float_or_zero(form_data.get('estimated_hours')),
        estimated_cost=_float_or_zero(form_data.get('estimated_cost')),
        materials=form_data.get('materials'),
        notes=form_data.get('notes'),
        requires_inspection='requires_inspection' in form_data,
    )

    if not job.is_multi_phase:
        job.is_multi_phase = True
        if job.original_estimated_cost is None:
            job.original_estimated_cost = job.estimated_amount

    db.add(phase)
    db.flush()
    return phase


def update_phase(db, phase, form_data):
    """Update an existing phase from form data."""
    phase.title = form_data.get('title', phase.title)
    phase.description = form_data.get('description', phase.description)
    phase.scheduled_start_date = _parse_date(form_data.get('scheduled_start_date')) or phase.scheduled_start_date
    phase.scheduled_end_date = _parse_date(form_data.get('scheduled_end_date')) or phase.scheduled_end_date
    phase.assigned_technician_id = _int_or_none(form_data.get('assigned_technician_id')) or phase.assigned_technician_id
    phase.estimated_hours = _float_or_zero(form_data.get('estimated_hours')) or phase.estimated_hours
    phase.estimated_cost = _float_or_zero(form_data.get('estimated_cost')) or phase.estimated_cost
    phase.actual_hours = _float_or_zero(form_data.get('actual_hours')) or phase.actual_hours
    phase.actual_cost = _float_or_zero(form_data.get('actual_cost')) or phase.actual_cost
    if form_data.get('actual_start_date'):
        phase.actual_start_date = _parse_date(form_data.get('actual_start_date'))
    phase.materials = form_data.get('materials', phase.materials)
    phase.notes = form_data.get('notes', phase.notes)
    phase.completion_notes = form_data.get('completion_notes', phase.completion_notes)
    phase.requires_inspection = 'requires_inspection' in form_data
    phase.updated_at = datetime.now(timezone.utc)
    return phase


def reorder_phases(db, job_id, ordered_phase_ids):
    """Given ordered list of phase IDs, update sort_order."""
    phases = {p.id: p for p in db.query(JobPhase).filter_by(job_id=job_id).all()}
    for idx, phase_id in enumerate(ordered_phase_ids):
        pid = int(phase_id)
        if pid in phases:
            phases[pid].sort_order = idx * 10
    return True


def delete_phase(db, phase):
    """Soft-delete (skip) if has activity, hard-delete otherwise."""
    has_activity = (
        (phase.actual_hours and float(phase.actual_hours) > 0) or
        (phase.actual_cost and float(phase.actual_cost) > 0) or
        phase.actual_start_date
    )

    if has_activity:
        phase.status = 'skipped'
    else:
        db.delete(phase)
        db.flush()

    # Renumber remaining phases
    remaining = db.query(JobPhase).filter_by(job_id=phase.job_id)\
                  .order_by(JobPhase.sort_order, JobPhase.phase_number).all()
    for idx, p in enumerate(remaining, start=1):
        p.phase_number = idx

    return True


def sync_job_cost_from_phases(db, job):
    """Recalculate job's adjusted_estimated_cost from phases + approved COs."""
    phase_total = sum(float(p.estimated_cost or 0) for p in job.phases)
    if job.original_estimated_cost is None:
        job.original_estimated_cost = phase_total

    co_delta = sum(
        co.cost_difference for co in job.change_orders
        if co.status == 'approved'
    )
    job.adjusted_estimated_cost = float(job.original_estimated_cost or 0) + co_delta


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            return None
    return value


def _int_or_none(value):
    try:
        v = int(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def create_phases_from_quote(db, job, phase_definitions):
    """
    Create multiple phases on a job from a list of phase definitions.
    Used when converting a quote to a multi-phase job.
    phase_definitions: list of dicts with 'title', 'description', 'estimated_cost'
    """
    job.is_multi_phase = True
    if job.original_estimated_cost is None:
        job.original_estimated_cost = job.estimated_amount

    for pdef in phase_definitions:
        if not pdef.get('title', '').strip():
            continue
        create_phase(db, job, pdef)


def _float_or_zero(value):
    try:
        return float(value) if value else 0
    except (TypeError, ValueError):
        return 0
