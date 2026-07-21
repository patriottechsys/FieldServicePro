"""Time tracking utilities: clock in/out, validation, cost computation, summaries."""
from datetime import timezone, datetime, date, timedelta
from sqlalchemy import func
from models.database import get_session
from models.time_entry import TimeEntry, ActiveClock
from models.job import Job
from models.job_phase import JobPhase
from models.technician import Technician


# ---------------------------------------------------------------------------
# Clock In / Out
# ---------------------------------------------------------------------------

def clock_in(technician_id, job_id, phase_id=None, notes=None):
    """Clock a technician into a job. Returns (ActiveClock, error_message)."""
    db = get_session()
    try:
        existing = db.query(ActiveClock).filter_by(technician_id=technician_id).first()
        if existing:
            job_num = existing.job.job_number if existing.job else existing.job_id
            return None, f"Already clocked into Job #{job_num}. Clock out first."

        job = db.query(Job).filter_by(id=job_id).first()
        if not job:
            return None, "Job not found."
        if job.status in ('completed', 'cancelled'):
            return None, f"Cannot clock into a {job.status} job."

        if phase_id:
            phase = db.query(JobPhase).filter_by(id=phase_id, job_id=job_id).first()
            if not phase:
                return None, "Invalid phase for this job."

        clock = ActiveClock(
            technician_id=technician_id,
            job_id=job_id,
            phase_id=phase_id,
            clock_in_time=datetime.now(timezone.utc),
            notes=notes,
        )
        db.add(clock)

        # Auto-start job if scheduled
        if job.status == 'scheduled':
            job.status = 'in_progress'
            if not job.started_at:
                job.started_at = datetime.now(timezone.utc)

        db.commit()
        return clock, None
    except Exception as e:
        db.rollback()
        return None, str(e)
    finally:
        db.close()


def clock_out(technician_id, description=None, entry_type='regular'):
    """Clock out a technician. Creates a TimeEntry. Returns (TimeEntry, error_message)."""
    db = get_session()
    try:
        clock = db.query(ActiveClock).filter_by(technician_id=technician_id).first()
        if not clock:
            return None, "Not currently clocked in."

        now = datetime.now(timezone.utc)
        elapsed = (now - clock.clock_in_time).total_seconds()
        duration = min(round(elapsed / 3600, 2), 16)  # Cap at 16 hours

        tech = db.query(Technician).filter_by(id=technician_id).first()
        hourly_rate = float(tech.hourly_rate or 55) if tech else 55.0
        billable_rate = float(getattr(tech, 'billable_rate', 95) or 95)

        billable = entry_type not in ('break', 'callback', 'warranty')

        job = db.query(Job).filter_by(id=clock.job_id).first()
        project_id = job.project_id if job else None

        entry = TimeEntry(
            technician_id=technician_id,
            job_id=clock.job_id,
            phase_id=clock.phase_id,
            project_id=project_id,
            entry_type=entry_type,
            date=clock.clock_in_time.date(),
            start_time=clock.clock_in_time.time(),
            end_time=now.time(),
            duration_hours=duration,
            billable=billable,
            hourly_rate=hourly_rate,
            billable_rate=billable_rate if billable else None,
            description=description or clock.notes,
            status='submitted',
            source='clock_in_out',
            created_by=getattr(tech, 'user_id', None) or 1,
        )
        entry.compute_costs()

        db.add(entry)
        db.delete(clock)
        db.commit()
        return entry, None
    except Exception as e:
        db.rollback()
        return None, str(e)
    finally:
        db.close()


def switch_job(technician_id, new_job_id, new_phase_id=None, description=None):
    """Clock out of current job and immediately clock into a new one."""
    entry, err = clock_out(technician_id, description=description)
    if err:
        return None, None, err
    clock, err2 = clock_in(technician_id, new_job_id, phase_id=new_phase_id)
    if err2:
        return None, entry, err2
    return clock, entry, None


def get_active_clock(technician_id):
    db = get_session()
    try:
        return db.query(ActiveClock).filter_by(technician_id=technician_id).first()
    finally:
        db.close()


def get_all_active_clocks():
    db = get_session()
    try:
        return db.query(ActiveClock).all()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Approval helpers
# ---------------------------------------------------------------------------

def submit_entries(entry_ids, technician_id=None):
    db = get_session()
    try:
        q = db.query(TimeEntry).filter(TimeEntry.id.in_(entry_ids), TimeEntry.status == 'draft')
        if technician_id:
            q = q.filter(TimeEntry.technician_id == technician_id)
        count = 0
        for e in q.all():
            e.status = 'submitted'
            count += 1
        db.commit()
        return count
    finally:
        db.close()


def approve_entries(entry_ids, approved_by_user_id):
    db = get_session()
    try:
        entries = db.query(TimeEntry).filter(
            TimeEntry.id.in_(entry_ids), TimeEntry.status == 'submitted'
        ).all()
        now = datetime.now(timezone.utc)
        count = 0
        for e in entries:
            e.status = 'approved'
            e.approved_by = approved_by_user_id
            e.approved_at = now
            count += 1
        db.commit()
        return count
    finally:
        db.close()


def reject_entries(entry_ids, rejected_by_user_id, reason):
    db = get_session()
    try:
        entries = db.query(TimeEntry).filter(
            TimeEntry.id.in_(entry_ids), TimeEntry.status == 'submitted'
        ).all()
        now = datetime.now(timezone.utc)
        count = 0
        for e in entries:
            e.status = 'rejected'
            e.approved_by = rejected_by_user_id
            e.approved_at = now
            e.rejection_reason = reason
            count += 1
        db.commit()
        return count
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_tech_hours_for_date(db, technician_id, entry_date):
    result = db.query(func.coalesce(func.sum(TimeEntry.duration_hours), 0)).filter(
        TimeEntry.technician_id == technician_id,
        TimeEntry.date == entry_date,
        TimeEntry.status != 'rejected',
    ).scalar()
    return float(result)


def get_tech_hours_for_week(db, technician_id, week_start):
    week_end = week_start + timedelta(days=6)
    result = db.query(func.coalesce(func.sum(TimeEntry.duration_hours), 0)).filter(
        TimeEntry.technician_id == technician_id,
        TimeEntry.date >= week_start,
        TimeEntry.date <= week_end,
        TimeEntry.status != 'rejected',
    ).scalar()
    return float(result)


def get_job_labor_summary(db, job_id):
    entries = db.query(TimeEntry).filter(
        TimeEntry.job_id == job_id,
        TimeEntry.status.in_(['approved', 'exported', 'submitted']),
    ).all()

    total_hours = sum(float(e.duration_hours or 0) for e in entries)
    total_cost = sum(float(e.labor_cost or 0) for e in entries)
    total_billable = sum(float(e.billable_amount or 0) for e in entries)

    by_tech = {}
    for e in entries:
        tid = e.technician_id
        if tid not in by_tech:
            name = e.technician.full_name if e.technician else 'Unknown'
            by_tech[tid] = {'name': name, 'hours': 0, 'cost': 0}
        by_tech[tid]['hours'] += float(e.duration_hours or 0)
        by_tech[tid]['cost'] += float(e.labor_cost or 0)

    return {
        'total_hours': round(total_hours, 2),
        'total_labor_cost': round(total_cost, 2),
        'total_billable': round(total_billable, 2),
        'by_tech': by_tech,
        'entry_count': len(entries),
    }
