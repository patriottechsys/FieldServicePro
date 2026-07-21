"""
Phase status transition logic, job status derivation, and inspection workflow.
"""
from datetime import timezone, datetime, date

# Valid status transitions
ALLOWED_TRANSITIONS = {
    'not_started': ['scheduled', 'skipped'],
    'scheduled':   ['in_progress', 'on_hold', 'skipped', 'not_started'],
    'in_progress': ['on_hold', 'completed', 'skipped'],
    'on_hold':     ['in_progress', 'scheduled', 'skipped'],
    'completed':   ['in_progress'],  # allow re-open
    'skipped':     ['not_started'],
}


def can_transition(phase, new_status):
    """Returns (allowed: bool, reason: str)."""
    allowed = ALLOWED_TRANSITIONS.get(phase.status, [])
    if new_status not in allowed:
        return False, f"Cannot move from '{phase.status}' to '{new_status}'"

    if new_status == 'completed' and phase.requires_inspection:
        if phase.inspection_status != 'passed':
            return False, "This phase requires a passing inspection before it can be marked complete."

    return True, "ok"


def transition_phase_status(phase, new_status, actor_note=None):
    """
    Apply a status transition. Returns (success, message).
    Does NOT commit — caller must commit.
    """
    allowed, reason = can_transition(phase, new_status)
    if not allowed:
        return False, reason

    old_status = phase.status
    phase.status = new_status

    now = datetime.now(timezone.utc)
    today = date.today()

    if new_status == 'in_progress' and not phase.actual_start_date:
        phase.actual_start_date = today

    if new_status == 'completed':
        phase.actual_end_date = today
        if phase.requires_inspection and phase.inspection_status == 'not_required':
            phase.inspection_status = 'pending'

    if new_status == 'on_hold' and actor_note:
        existing = phase.notes or ''
        phase.notes = f"{existing}\n[ON HOLD {now:%Y-%m-%d}]: {actor_note}".strip()

    phase.updated_at = now
    return True, f"Phase moved from '{old_status}' to '{new_status}'"


def sync_job_status_from_phases(job):
    """Derive and update job status from phase statuses. Only for multi-phase jobs."""
    if not job.is_multi_phase or not job.phases:
        return

    derived = job.derived_status_from_phases
    if derived:
        status_map = {
            'in_progress': 'in_progress',
            'completed': 'completed',
            'on_hold': 'in_progress',
            'scheduled': 'scheduled',
        }
        new_job_status = status_map.get(derived)
        if new_job_status and job.status != new_job_status:
            job.status = new_job_status


def record_inspection(phase, passed, inspector_notes=None, inspection_date=None):
    """Record inspection result. Returns (success, message)."""
    if not phase.requires_inspection:
        return False, "This phase does not require inspection."

    phase.inspection_status = 'passed' if passed else 'failed'
    phase.inspection_date = inspection_date or datetime.now(timezone.utc)
    phase.inspection_notes = inspector_notes
    phase.updated_at = datetime.now(timezone.utc)

    if not passed and phase.status == 'completed':
        phase.status = 'in_progress'

    return True, "Inspection recorded."


def get_phase_status_summary(job):
    """Return summary dict for progress display."""
    phases = sorted(job.phases, key=lambda p: p.sort_order)
    return {
        'total': len(phases),
        'completed': sum(1 for p in phases if p.is_complete),
        'in_progress': sum(1 for p in phases if p.status == 'in_progress'),
        'on_hold': sum(1 for p in phases if p.status == 'on_hold'),
        'not_started': sum(1 for p in phases if p.status == 'not_started'),
        'scheduled': sum(1 for p in phases if p.status == 'scheduled'),
        'percent': job.percent_complete,
        'has_inspection_pending': any(p.inspection_required_and_pending for p in phases),
    }
