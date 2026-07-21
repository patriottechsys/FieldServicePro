"""Capacity Planning Engine — tech availability, scheduling, and forecasting.
Adapted to project patterns: organization_id, assigned_technician_id, duration_hours.
"""
from datetime import date, datetime, timedelta
from sqlalchemy import func, or_
from models.technician import Technician
from models.job import Job
from models.app_settings import AppSettings


def get_capacity_settings():
    """Load capacity settings from AppSettings."""
    return {
        'hours_per_day': float(AppSettings.get('capacity_hours_per_day', '8')),
        'overbook_threshold': int(AppSettings.get('capacity_overbook_threshold', '100')),
        'underutil_threshold': int(AppSettings.get('capacity_underutil_threshold', '50')),
        'working_days': [0, 1, 2, 3, 4],  # Mon-Fri
    }


def get_working_days(start, end, working_days):
    """Return list of working day dates in range."""
    days = []
    current = start
    while current <= end:
        if current.weekday() in working_days:
            days.append(current)
        current += timedelta(days=1)
    return days


def get_capacity_data(db, org_id, start, end, division_id=None):
    """Calculate capacity grid: tech x day with hours booked/available."""
    settings = get_capacity_settings()
    hpd = settings['hours_per_day']
    wd = settings['working_days']

    q = db.query(Technician).filter(
        Technician.organization_id == org_id,
        Technician.is_active == True,
    )
    if division_id:
        q = q.filter(Technician.division_id == division_id)
    techs = q.order_by(Technician.first_name).all()

    all_days = []
    current = start
    while current <= end:
        all_days.append(current)
        current += timedelta(days=1)

    working_days = [d for d in all_days if d.weekday() in wd]

    # Get scheduled jobs
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())
    jobs = db.query(Job).filter(
        Job.organization_id == org_id,
        Job.scheduled_date >= start_dt,
        Job.scheduled_date <= end_dt,
        Job.status.in_(['scheduled', 'in_progress', 'pending']),
        Job.assigned_technician_id.isnot(None),
    ).all()

    # Build job map: tech_id -> date -> [jobs]
    job_map = {}
    for j in jobs:
        tid = j.assigned_technician_id
        d = j.scheduled_date.date() if isinstance(j.scheduled_date, datetime) else j.scheduled_date
        job_map.setdefault(tid, {}).setdefault(d, []).append(j)

    grid = []
    for tech in techs:
        row = {
            'tech_id': tech.id,
            'tech_name': tech.full_name,
            'division': tech.division.name if tech.division else '',
            'division_id': tech.division_id,
            'days': {},
            'total_available': 0.0,
            'total_booked': 0.0,
        }

        for d in all_days:
            is_working = d.weekday() in wd
            avail = hpd if is_working else 0.0
            day_jobs = job_map.get(tech.id, {}).get(d, [])
            # Each job consumes one day's worth of hours (Job has no estimated_hours field)
            booked = len(day_jobs) * hpd if day_jobs else 0

            row['days'][d.isoformat()] = {
                'date': d.isoformat(),
                'is_working': is_working,
                'hours_available': avail,
                'hours_booked': round(booked, 1),
                'utilization_pct': round((booked / avail * 100) if avail > 0 else 0, 1),
                'jobs': [
                    {'id': j.id, 'job_number': j.job_number or '',
                     'client_name': j.client.display_name if j.client else 'Unknown',
                     'status': j.status}
                    for j in day_jobs
                ],
                'is_overbooked': booked > avail and avail > 0,
            }
            row['total_available'] += avail
            row['total_booked'] += booked

        row['total_utilization'] = round(
            (row['total_booked'] / row['total_available'] * 100)
            if row['total_available'] > 0 else 0, 1
        )
        grid.append(row)

    total_cap = sum(r['total_available'] for r in grid)
    total_book = sum(r['total_booked'] for r in grid)
    over = [r for r in grid if r['total_utilization'] > settings['overbook_threshold']]
    under = [r for r in grid if r['total_utilization'] < settings['underutil_threshold'] and r['total_available'] > 0]

    return {
        'grid': grid,
        'all_days': [d.isoformat() for d in all_days],
        'working_days': [d.isoformat() for d in working_days],
        'total_capacity': total_cap,
        'total_booked': total_book,
        'total_available': total_cap - total_book,
        'overall_utilization': round((total_book / total_cap * 100) if total_cap > 0 else 0, 1),
        'overbooked_count': len(over),
        'underutil_count': len(under),
        'overbooked_techs': [r['tech_name'] for r in over],
        'underutil_techs': [r['tech_name'] for r in under],
        'hours_per_day': hpd,
        'settings': settings,
    }


def generate_capacity_alerts(db, org_id, capacity_data):
    """Generate alerts from capacity data."""
    alerts = []
    if capacity_data['overbooked_count'] > 0:
        alerts.append({
            'level': 'danger',
            'message': f"{capacity_data['overbooked_count']} tech(s) over-booked: {', '.join(capacity_data['overbooked_techs'])}",
        })
    if capacity_data['overall_utilization'] < 30:
        alerts.append({
            'level': 'warning',
            'message': f"Low bookings: overall utilization is {capacity_data['overall_utilization']:.0f}%",
        })
    if capacity_data['underutil_count'] > 0:
        alerts.append({
            'level': 'info',
            'message': f"{capacity_data['underutil_count']} tech(s) under-utilized",
        })
    return alerts


def get_unscheduled_work(db, org_id, limit=20):
    """Return pending/unscheduled jobs."""
    jobs = db.query(Job).filter(
        Job.organization_id == org_id,
        Job.status.in_(['pending', 'draft']),
        or_(Job.scheduled_date.is_(None), Job.assigned_technician_id.is_(None)),
    ).order_by(Job.priority.desc(), Job.created_at.asc()).limit(limit).all()

    return [
        {'id': j.id, 'job_number': j.job_number or '',
         'client_name': j.client.display_name if j.client else 'Unknown',
         'job_type': j.job_type or '', 'priority': j.priority or 'normal',
         'status': j.status}
        for j in jobs
    ]


def get_demand_forecast(db, org_id, start, end):
    """Forecast demand from recurring schedules."""
    weeks = {}
    current = start
    while current <= end:
        ws = current - timedelta(days=current.weekday())
        wk = ws.isoformat()
        if wk not in weeks:
            weeks[wk] = {'week_start': wk, 'label': ws.strftime('Week of %b %d'),
                         'expected_jobs': 0, 'expected_hours': 0.0}
        current += timedelta(days=7)

    try:
        from models.recurring_schedule import RecurringSchedule
        recurring = db.query(RecurringSchedule).filter_by(
            organization_id=org_id, is_active=True,
        ).all()
        range_days = (end - start).days + 1
        for rec in recurring:
            freq = getattr(rec, 'frequency', 'monthly')
            est = float(getattr(rec, 'estimated_amount', 2) or 2)
            occ = {'weekly': range_days / 7, 'biweekly': range_days / 14,
                   'monthly': range_days / 30}.get(freq, range_days / 90)
            per_week = occ / max(len(weeks), 1)
            for wk in weeks:
                weeks[wk]['expected_jobs'] += per_week
                weeks[wk]['expected_hours'] += per_week * min(est, 8)
    except Exception:
        pass

    return {
        'weeks': list(weeks.values()),
        'total_expected_jobs': sum(w['expected_jobs'] for w in weeks.values()),
        'total_expected_hours': sum(w['expected_hours'] for w in weeks.values()),
    }
