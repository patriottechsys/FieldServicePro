"""
SLA detection and deadline calculation utilities.
Called from job creation, job edit, and job status-change routes.
"""

from datetime import timezone, datetime
from models.contract import Contract, ContractStatus
from models.sla import SLA, PriorityLevel


# Map job priority strings to SLA PriorityLevel
PRIORITY_MAP = {
    'emergency': PriorityLevel.emergency,
    'urgent':    PriorityLevel.high,
    'high':      PriorityLevel.high,
    'medium':    PriorityLevel.medium,
    'normal':    PriorityLevel.medium,
    'low':       PriorityLevel.low,
}


def detect_contract_for_job(db, client_id, property_id=None):
    """
    Return the best active contract for a given client/property combo.
    Preference: property-specific contract > client-wide contract.
    """
    query = (db.query(Contract)
               .filter_by(client_id=client_id, status=ContractStatus.active))
    active_contracts = query.all()

    if not active_contracts:
        return None

    if property_id:
        # Try property-specific first
        for c in active_contracts:
            prop_ids = {p.id for p in c.properties}
            if property_id in prop_ids:
                return c

    # Fall back to first active contract (or one with no property restriction)
    for c in active_contracts:
        if not c.properties:
            return c

    return active_contracts[0] if active_contracts else None


def detect_sla_for_job(contract, job_priority):
    """
    Given a contract and job priority string, return the best matching SLA.
    """
    if not contract or not contract.slas:
        return None

    target_level = PRIORITY_MAP.get((job_priority or 'medium').lower(),
                                     PriorityLevel.medium)

    # Exact priority match
    for sla in contract.slas:
        if sla.priority_level == target_level and sla.is_active:
            return sla

    # Fallback: highest-priority active SLA on the contract
    priority_order = [PriorityLevel.emergency, PriorityLevel.high,
                      PriorityLevel.medium, PriorityLevel.low]
    for level in priority_order:
        for sla in contract.slas:
            if sla.priority_level == level and sla.is_active:
                return sla

    return None


def apply_sla_to_job(job, contract, sla, created_at=None):
    """
    Set contract_id, sla_id, and calculate deadlines on the job object.
    Does NOT commit — caller is responsible.
    """
    if not sla:
        return

    job.contract_id = contract.id if contract else None
    job.sla_id      = sla.id

    base_dt = created_at or job.created_at or datetime.now(timezone.utc)

    job.sla_response_deadline = sla.calculate_deadline(
        base_dt, sla.response_time_hours
    )

    if sla.resolution_time_hours:
        job.sla_resolution_deadline = sla.calculate_deadline(
            base_dt, sla.resolution_time_hours
        )
    else:
        job.sla_resolution_deadline = None


def record_response_time(job):
    """
    Call when job moves to 'in_progress'.
    Sets actual_response_time and sla_response_met.
    """
    now = datetime.now(timezone.utc)
    job.actual_response_time = now
    if job.sla_response_deadline:
        job.sla_response_met = now <= job.sla_response_deadline
    else:
        job.sla_response_met = None


def record_resolution_time(job):
    """
    Call when job moves to 'completed'.
    Sets actual_resolution_time and sla_resolution_met.
    """
    now = datetime.now(timezone.utc)
    job.actual_resolution_time = now
    if job.sla_resolution_deadline:
        job.sla_resolution_met = now <= job.sla_resolution_deadline
    else:
        job.sla_resolution_met = None


def handle_job_status_change(job, new_status):
    """
    Hook SLA tracking into job status transitions.
    Call this before committing new status.
    """
    old_status = job.status

    IN_PROGRESS_STATUSES = {'in_progress', 'on_site', 'started', 'en_route'}
    COMPLETED_STATUSES   = {'completed', 'done', 'closed', 'resolved'}

    if (old_status not in IN_PROGRESS_STATUSES and
            new_status in IN_PROGRESS_STATUSES and
            not job.actual_response_time):
        record_response_time(job)

    if (old_status not in COMPLETED_STATUSES and
            new_status in COMPLETED_STATUSES and
            not job.actual_resolution_time):
        record_resolution_time(job)

    job.status = new_status


def get_sla_alert_jobs(db, limit=50):
    """
    Return jobs that are at-risk or breached, ordered by urgency.
    Used for dashboard widgets and notification checks.
    """
    from models.job import Job
    from sqlalchemy import or_

    now = datetime.now(timezone.utc)

    jobs = (db.query(Job)
              .filter(Job.sla_id.isnot(None))
              .filter(Job.actual_resolution_time.is_(None))
              .filter(or_(
                  Job.sla_response_deadline <= now,
                  Job.sla_resolution_deadline <= now,
              ))
              .order_by(Job.sla_resolution_deadline.asc().nullslast())
              .limit(limit)
              .all())
    return jobs
