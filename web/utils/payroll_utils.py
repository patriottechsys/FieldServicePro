"""
Payroll calculation engine.

Overtime rules (defaults):
  - daily_ot_threshold    : 8 hours/day
  - daily_dt_threshold    : 12 hours/day
  - weekly_ot_threshold   : 40 hours/week
  - ot_multiplier         : 1.5x
  - dt_multiplier         : 2.0x
"""
import csv
import io
from collections import defaultdict
from datetime import timezone, date, datetime, timedelta

from models.database import get_session
from models.technician import Technician
from models.time_entry import TimeEntry
from models.expense import Expense
from models.payroll_period import PayrollPeriod
from models.payroll_line_item import PayrollLineItem


# ── Period generation ─────────────────────────────────────────────────────────

def generate_period_name(start, end):
    return f"Pay Period: {start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"


def get_period_dates(frequency, reference_date=None):
    """Calculate start/end dates for the CURRENT period given a frequency."""
    today = reference_date or date.today()

    if frequency == 'weekly':
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif frequency == 'biweekly':
        epoch = date(2024, 1, 1)
        days_since = (today - epoch).days
        period_num = days_since // 14
        start = epoch + timedelta(days=period_num * 14)
        end = start + timedelta(days=13)
    elif frequency == 'semi_monthly':
        if today.day <= 15:
            start = today.replace(day=1)
            end = today.replace(day=15)
        else:
            import calendar
            start = today.replace(day=16)
            last_day = calendar.monthrange(today.year, today.month)[1]
            end = today.replace(day=last_day)
    elif frequency == 'monthly':
        import calendar
        start = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        end = today.replace(day=last_day)
    else:
        raise ValueError(f'Unknown pay frequency: {frequency}')

    return start, end


def get_or_create_current_period(db, frequency='biweekly'):
    """Return the current open PayrollPeriod, creating it if necessary."""
    start, end = get_period_dates(frequency)
    existing = db.query(PayrollPeriod).filter_by(start_date=start, end_date=end).first()
    if existing:
        return existing

    period = PayrollPeriod(
        period_name=generate_period_name(start, end),
        start_date=start, end_date=end,
        status='open', pay_frequency=frequency,
    )
    db.add(period)
    db.flush()
    return period


# ── OT rule loading ───────────────────────────────────────────────────────────

def _load_ot_rules():
    """Load overtime rules from AppSettings key-value store or return defaults."""
    try:
        from models.app_settings import AppSettings
        return {
            'daily_ot': float(AppSettings.get('daily_ot_threshold', 8)),
            'daily_dt': float(AppSettings.get('daily_dt_threshold', 12)),
            'weekly_ot': float(AppSettings.get('weekly_ot_threshold', 40)),
            'ot_mult': float(AppSettings.get('ot_multiplier', 1.5)),
            'dt_mult': float(AppSettings.get('dt_multiplier', 2.0)),
        }
    except Exception:
        return {
            'daily_ot': 8.0, 'daily_dt': 12.0, 'weekly_ot': 40.0,
            'ot_mult': 1.5, 'dt_mult': 2.0,
        }


# ── Per-technician calculation ────────────────────────────────────────────────

def _classify_daily_hours(daily_hours, rules):
    """Split a day's hours into (regular, overtime, double_time)."""
    dt_thresh = rules['daily_dt']
    ot_thresh = rules['daily_ot']

    if daily_hours <= ot_thresh:
        return daily_hours, 0.0, 0.0
    if daily_hours <= dt_thresh:
        return ot_thresh, daily_hours - ot_thresh, 0.0
    return ot_thresh, dt_thresh - ot_thresh, daily_hours - dt_thresh


def calculate_line_item(db, technician, period, rules=None):
    """Build or update a PayrollLineItem for one technician + period."""
    if rules is None:
        rules = _load_ot_rules()

    # Pull time entries
    entries = db.query(TimeEntry).filter(
        TimeEntry.technician_id == technician.id,
        TimeEntry.date >= period.start_date,
        TimeEntry.date <= period.end_date,
        TimeEntry.status.in_(['approved', 'completed', 'exported']),
    ).all()

    # Group by day
    daily = defaultdict(float)
    job_ids = set()
    for entry in entries:
        day = entry.date
        daily[day] += float(entry.duration_hours or 0)
        if entry.job_id:
            job_ids.add(entry.job_id)

    # Daily OT/DT pass
    reg_total = ot_total = dt_total = 0.0
    for _day, hrs in daily.items():
        r, o, d = _classify_daily_hours(hrs, rules)
        reg_total += r
        ot_total += o
        dt_total += d

    # Weekly OT spill-over
    weekly_total = reg_total + ot_total + dt_total
    if weekly_total > rules['weekly_ot'] and reg_total > 0:
        spill = weekly_total - rules['weekly_ot']
        extra_weekly_ot = min(spill, reg_total)
        reg_total -= extra_weekly_ot
        ot_total += extra_weekly_ot

    # Rates
    base_rate = float(getattr(technician, 'hourly_rate', 0) or 0)
    ot_rate = round(base_rate * rules['ot_mult'], 2)
    dt_rate = round(base_rate * rules['dt_mult'], 2)

    # Pay amounts
    reg_pay = round(reg_total * base_rate, 2)
    ot_pay = round(ot_total * ot_rate, 2)
    dt_pay = round(dt_total * dt_rate, 2)

    # Reimbursable expenses (linked via paid_by user -> technician user)
    expense_total = _sum_reimbursable_expenses(db, technician, period.start_date, period.end_date)

    # Find or create line item
    line = db.query(PayrollLineItem).filter_by(
        period_id=period.id, technician_id=technician.id
    ).first()

    if not line:
        line = PayrollLineItem(period_id=period.id, technician_id=technician.id)
        db.add(line)

    line.regular_hours = round(reg_total, 4)
    line.overtime_hours = round(ot_total, 4)
    line.double_time_hours = round(dt_total, 4)
    line.regular_rate = base_rate
    line.overtime_rate = ot_rate
    line.double_time_rate = dt_rate
    line.regular_pay = reg_pay
    line.overtime_pay = ot_pay
    line.double_time_pay = dt_pay
    line.reimbursable_expenses = expense_total
    line.jobs_worked = len(job_ids)
    line.days_worked = len(daily)
    line.status = 'draft'

    return line


def _sum_reimbursable_expenses(db, technician, start, end):
    """Sum approved reimbursable expenses for a technician in a date range."""
    # Link via paid_by (user_id) -> technician.user_id
    user_id = getattr(technician, 'user_id', None)
    if not user_id:
        return 0.0

    rows = db.query(Expense).filter(
        Expense.paid_by == user_id,
        Expense.expense_date >= start,
        Expense.expense_date <= end,
        Expense.is_reimbursable == True,
        Expense.status.in_(['approved', 'reimbursed']),
    ).all()
    return round(sum(float(e.total_amount or 0) for e in rows), 2)


# ── Full-period calculation ───────────────────────────────────────────────────

def calculate_period(db, period, organization_id):
    """Calculate all line items for a PayrollPeriod."""
    period.status = 'processing'
    rules = _load_ot_rules()

    technicians = db.query(Technician).filter_by(
        organization_id=organization_id, is_active=True
    ).all()

    for tech in technicians:
        calculate_line_item(db, tech, period, rules)

    db.flush()
    period.refresh_totals()
    return period


def finalize_period(period, user_id):
    """Lock the period."""
    period.status = 'finalized'
    period.finalized_by = user_id
    period.finalized_at = datetime.now(timezone.utc)
    period.refresh_totals()
    return period


# ── CSV Export ────────────────────────────────────────────────────────────────

def export_period_csv(period):
    """Return a CSV string for the period's payroll summary."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        'Employee Name', 'Pay Period Start', 'Pay Period End',
        'Regular Hours', 'OT Hours', 'DT Hours', 'Total Hours',
        'Regular Rate', 'OT Rate', 'DT Rate',
        'Regular Pay', 'OT Pay', 'DT Pay', 'Gross Pay',
        'Reimbursements', 'Total Compensation',
        'Jobs Worked', 'Days Worked', 'Status',
    ])

    for li in sorted(period.line_items, key=lambda x: x.technician.full_name if x.technician else ''):
        tech = li.technician
        name = tech.full_name if tech else f'Tech #{li.technician_id}'
        writer.writerow([
            name,
            period.start_date.strftime('%Y-%m-%d'),
            period.end_date.strftime('%Y-%m-%d'),
            f'{float(li.regular_hours or 0):.2f}',
            f'{float(li.overtime_hours or 0):.2f}',
            f'{float(li.double_time_hours or 0):.2f}',
            f'{li.total_hours:.2f}',
            f'{float(li.regular_rate or 0):.2f}',
            f'{float(li.overtime_rate or 0):.2f}',
            f'{float(li.double_time_rate or 0):.2f}',
            f'{float(li.regular_pay or 0):.2f}',
            f'{float(li.overtime_pay or 0):.2f}',
            f'{float(li.double_time_pay or 0):.2f}',
            f'{li.gross_pay:.2f}',
            f'{float(li.reimbursable_expenses or 0):.2f}',
            f'{li.total_compensation:.2f}',
            li.jobs_worked, li.days_worked, li.status,
        ])

    # Totals row
    writer.writerow([
        'TOTALS', period.start_date.strftime('%Y-%m-%d'), period.end_date.strftime('%Y-%m-%d'),
        f'{float(period.total_regular_hours or 0):.2f}',
        f'{float(period.total_overtime_hours or 0):.2f}',
        f'{float(period.total_double_time_hours or 0):.2f}',
        f'{period.total_hours:.2f}',
        '', '', '', '', '', '',
        f'{float(period.total_gross_pay or 0):.2f}',
        f'{float(period.total_reimbursements or 0):.2f}',
        f'{period.total_compensation:.2f}',
        '', '', '',
    ])

    return output.getvalue()


def export_period_detailed_csv(db, period):
    """Detailed export: one row per time entry per technician."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Employee Name', 'Date', 'Start', 'End', 'Hours', 'Job #',
        'Entry Type', 'Status',
    ])

    rules = _load_ot_rules()

    for li in sorted(period.line_items, key=lambda x: x.technician.full_name if x.technician else ''):
        tech = li.technician
        if not tech:
            continue

        entries = db.query(TimeEntry).filter(
            TimeEntry.technician_id == tech.id,
            TimeEntry.date >= period.start_date,
            TimeEntry.date <= period.end_date,
        ).order_by(TimeEntry.date, TimeEntry.start_time).all()

        for entry in entries:
            job_num = ''
            if entry.job:
                job_num = entry.job.job_number or f'#{entry.job_id}'
            writer.writerow([
                tech.full_name,
                entry.date.strftime('%Y-%m-%d') if entry.date else '',
                entry.start_time.strftime('%H:%M') if entry.start_time else '',
                entry.end_time.strftime('%H:%M') if entry.end_time else '',
                f'{float(entry.duration_hours or 0):.2f}',
                job_num,
                entry.entry_type or 'regular',
                entry.status or '',
            ])

    return output.getvalue()


# ── Warnings / validation ─────────────────────────────────────────────────────

def get_period_warnings(db, period):
    """Return a list of warning dicts for the period detail page."""
    warnings = []

    for li in period.line_items:
        tech = li.technician
        name = tech.full_name if tech else f'Tech #{li.technician_id}'

        # Unapproved time entries
        unapproved = db.query(TimeEntry).filter(
            TimeEntry.technician_id == li.technician_id,
            TimeEntry.date >= period.start_date,
            TimeEntry.date <= period.end_date,
            TimeEntry.status.notin_(['approved', 'completed', 'exported']),
        ).count()

        if unapproved:
            warnings.append({
                'type': 'warning',
                'message': f'{name}: {unapproved} unapproved time entry(s)',
                'technician_id': li.technician_id,
            })

        if li.total_hours == 0 and li.days_worked == 0:
            warnings.append({
                'type': 'info',
                'message': f'{name}: No time entries found for this period',
                'technician_id': li.technician_id,
            })

    return warnings
