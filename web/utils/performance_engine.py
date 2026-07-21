"""Performance Score Calculation Engine.

Computes composite technician performance scores from weighted metrics
across 7 dimensions. Stores results in TechPerformanceScore.
Adapted to project's actual field names (organization_id, assigned_technician_id, etc.)
"""
from datetime import timezone, date, datetime, timedelta
from sqlalchemy import func
from models.tech_performance import (
    TechPerformanceScore, TechAchievement, ACHIEVEMENT_DEFINITIONS
)
from models.technician import Technician
from models.job import Job
from models.time_entry import TimeEntry
from models.callback import Callback
from models.feedback_survey import FeedbackSurvey
from models.invoice import Invoice
from models.expense import Expense


DEFAULT_WEIGHTS = {
    'customer_rating': 0.25, 'completion_rate': 0.20,
    'callback_rate': 0.15, 'utilization': 0.15,
    'revenue': 0.10, 'efficiency': 0.10, 'profitability': 0.05,
}


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def get_period_bounds(period_type, ref=None):
    """Return (start, end) dates for period containing ref."""
    ref = ref or date.today()
    if period_type == 'weekly':
        start = ref - timedelta(days=ref.weekday())
        end = start + timedelta(days=6)
    elif period_type == 'monthly':
        start = ref.replace(day=1)
        end = (date(ref.year, ref.month + 1, 1) if ref.month < 12
               else date(ref.year + 1, 1, 1)) - timedelta(days=1)
    elif period_type == 'quarterly':
        q = (ref.month - 1) // 3
        start = date(ref.year, q * 3 + 1, 1)
        end_month = q * 3 + 3
        end = (date(ref.year, end_month + 1, 1) if end_month < 12
               else date(ref.year + 1, 1, 1)) - timedelta(days=1)
    else:
        start = ref.replace(day=1)
        end = ref
    return start, end


def _get_previous_period(period_type, current_start):
    """Return (start, end) of the period before current_start."""
    if period_type == 'weekly':
        prev_ref = current_start - timedelta(weeks=1)
    elif period_type == 'monthly':
        prev_ref = (current_start - timedelta(days=1)).replace(day=1)
    elif period_type == 'quarterly':
        prev_ref = (current_start - timedelta(days=1)).replace(day=1)
        q = (prev_ref.month - 1) // 3
        prev_ref = date(prev_ref.year, q * 3 + 1, 1)
    else:
        prev_ref = current_start - timedelta(days=30)
    return get_period_bounds(period_type, prev_ref)


# ── Metric calculators ───────────────────────────────────────────────────────

def _calc_customer_rating(db, tech_id, org_id, start, end):
    """Returns (score, avg_rating)."""
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())
    avg = db.query(func.avg(FeedbackSurvey.overall_rating)).filter(
        FeedbackSurvey.technician_id == tech_id,
        FeedbackSurvey.completed_at >= start_dt,
        FeedbackSurvey.completed_at <= end_dt,
        FeedbackSurvey.overall_rating.isnot(None),
        FeedbackSurvey.status == 'completed',
    ).scalar()
    avg_rating = float(avg) if avg else 0.0
    score = (avg_rating / 5.0) * 100 if avg_rating > 0 else 50.0
    return _clamp(score), avg_rating


def _calc_completion_rate(db, tech_id, org_id, start, end):
    """Returns (score, completed, total)."""
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())
    total = db.query(func.count(Job.id)).filter(
        Job.organization_id == org_id,
        Job.assigned_technician_id == tech_id,
        Job.scheduled_date >= start_dt,
        Job.scheduled_date <= end_dt,
    ).scalar() or 0
    completed = db.query(func.count(Job.id)).filter(
        Job.organization_id == org_id,
        Job.assigned_technician_id == tech_id,
        Job.scheduled_date >= start_dt,
        Job.scheduled_date <= end_dt,
        Job.status == 'completed',
    ).scalar() or 0
    if total == 0:
        return 50.0, 0, 0
    return _clamp((completed / total) * 100), completed, total


def _calc_callback_rate(db, tech_id, org_id, start, end, jobs_completed):
    """Returns (score, callback_count)."""
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())
    cb_count = db.query(func.count(Callback.id)).filter(
        Callback.responsible_technician_id == tech_id,
        Callback.created_at >= start_dt,
        Callback.created_at <= end_dt,
    ).scalar() or 0
    if jobs_completed == 0:
        return 75.0, 0
    rate = cb_count / jobs_completed
    score = max(0.0, (1.0 - rate * 10) * 100)
    return _clamp(score), cb_count


def _calc_utilization(db, tech_id, org_id, start, end, hours_per_day=8.0):
    """Returns (score, billable_hours, total_hours)."""
    working_days = sum(1 for i in range((end - start).days + 1)
                       if (start + timedelta(days=i)).weekday() < 5)
    available = working_days * hours_per_day

    total_hrs = float(db.query(func.sum(TimeEntry.duration_hours)).filter(
        TimeEntry.technician_id == tech_id,
        TimeEntry.date >= start,
        TimeEntry.date <= end,
    ).scalar() or 0)

    billable_hrs = float(db.query(func.sum(TimeEntry.duration_hours)).filter(
        TimeEntry.technician_id == tech_id,
        TimeEntry.date >= start,
        TimeEntry.date <= end,
        TimeEntry.billable == True,
    ).scalar() or 0)

    if available == 0:
        return 50.0, 0.0, 0.0
    return _clamp((billable_hrs / available) * 100), billable_hrs, total_hrs


def _calc_revenue(db, tech_id, org_id, start, end, max_revenue):
    """Returns (score, total_revenue)."""
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())
    rev = float(db.query(func.sum(Invoice.total)).join(
        Job, Invoice.job_id == Job.id
    ).filter(
        Invoice.organization_id == org_id,
        Job.assigned_technician_id == tech_id,
        Job.status == 'completed',
        Job.scheduled_date >= start_dt,
        Job.scheduled_date <= end_dt,
    ).scalar() or 0)
    if max_revenue <= 0:
        return 50.0, rev
    return _clamp((rev / max_revenue) * 100), rev


def _calc_profitability(db, tech_id, org_id, start, end, target_margin=30.0):
    """Returns (score, avg_margin_pct)."""
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())
    jobs = db.query(Job).filter(
        Job.organization_id == org_id,
        Job.assigned_technician_id == tech_id,
        Job.scheduled_date >= start_dt,
        Job.scheduled_date <= end_dt,
        Job.status == 'completed',
    ).all()
    if not jobs:
        return 50.0, 0.0

    margins = []
    for job in jobs:
        rev = float(db.query(func.sum(Invoice.total)).filter(
            Invoice.job_id == job.id,
        ).scalar() or 0)
        if rev <= 0:
            continue
        labor = float(db.query(func.sum(TimeEntry.labor_cost)).filter(
            TimeEntry.job_id == job.id,
        ).scalar() or 0)
        expense = float(db.query(func.sum(Expense.amount)).filter(
            Expense.job_id == job.id,
        ).scalar() or 0)
        cost = labor + expense
        margins.append(((rev - cost) / rev) * 100)

    if not margins:
        return 50.0, 0.0
    avg = sum(margins) / len(margins)
    return _clamp((avg / target_margin) * 100), avg


# ── Main calculation ─────────────────────────────────────────────────────────

def calculate_tech_scores_for_period(db, org_id, period_type, start, end, verbose=False):
    """Calculate scores for ALL technicians in an org for a period."""
    weights = DEFAULT_WEIGHTS
    techs = db.query(Technician).filter(
        Technician.organization_id == org_id,
        Technician.is_active == True,
    ).all()

    if not techs:
        return []

    # Pass 1: revenue for normalization
    rev_map = {}
    for tech in techs:
        _, rev = _calc_revenue(db, tech.id, org_id, start, end, 1.0)
        rev_map[tech.id] = rev
    max_rev = max(rev_map.values()) if rev_map else 0.0

    # Pass 2: all scores
    scores = []
    for tech in techs:
        rat_score, avg_rat = _calc_customer_rating(db, tech.id, org_id, start, end)
        comp_score, completed, total = _calc_completion_rate(db, tech.id, org_id, start, end)
        cb_score, cb_count = _calc_callback_rate(db, tech.id, org_id, start, end, completed)
        util_score, bill_hrs, tot_hrs = _calc_utilization(db, tech.id, org_id, start, end)
        rev_score, tot_rev = _calc_revenue(db, tech.id, org_id, start, end, max_rev)
        eff_score = 50.0  # Simplified: no estimated_hours on Job
        prof_score, avg_margin = _calc_profitability(db, tech.id, org_id, start, end)

        overall = (
            rat_score * weights['customer_rating'] +
            comp_score * weights['completion_rate'] +
            cb_score * weights['callback_rate'] +
            util_score * weights['utilization'] +
            rev_score * weights['revenue'] +
            eff_score * weights['efficiency'] +
            prof_score * weights['profitability']
        )
        overall = _clamp(overall)

        # Upsert
        existing = db.query(TechPerformanceScore).filter_by(
            organization_id=org_id, technician_id=tech.id,
            period_type=period_type, period_start=start,
        ).first()

        s = existing or TechPerformanceScore(
            organization_id=org_id, technician_id=tech.id,
            period_type=period_type, period_start=start, period_end=end,
        )
        if not existing:
            db.add(s)

        s.overall_score = overall
        s.customer_rating_score = rat_score
        s.completion_rate_score = comp_score
        s.callback_rate_score = cb_score
        s.utilization_score = util_score
        s.revenue_score = rev_score
        s.efficiency_score = eff_score
        s.profitability_score = prof_score
        s.jobs_completed = completed
        s.jobs_total = total
        s.total_hours = tot_hrs
        s.billable_hours = bill_hrs
        s.total_revenue = tot_rev
        s.total_callbacks = cb_count
        s.avg_customer_rating = avg_rat
        s.avg_job_margin = avg_margin
        s.calculated_at = datetime.now(timezone.utc)
        s.period_end = end
        scores.append(s)

    db.flush()

    # Assign ranks
    scores.sort(key=lambda x: x.overall_score, reverse=True)
    for rank, s in enumerate(scores, 1):
        s.rank = rank

    db.commit()
    return scores


def calculate_and_assign_achievements(db, org_id, period_type, start, end, scores):
    """Award achievements based on score data."""
    new_achievements = []
    if not scores:
        return []

    by_revenue = sorted(scores, key=lambda s: s.total_revenue, reverse=True)
    by_hours = sorted(scores, key=lambda s: s.total_hours, reverse=True)
    by_rating = sorted(scores, key=lambda s: s.avg_customer_rating, reverse=True)

    for score in scores:
        tid = score.technician_id
        earned = set(
            a.achievement_type for a in db.query(TechAchievement).filter_by(
                organization_id=org_id, technician_id=tid,
                period_type=period_type, period_start=start,
            ).all()
        )

        def _award(atype):
            if atype in earned:
                return
            defn = ACHIEVEMENT_DEFINITIONS[atype]
            ach = TechAchievement(
                organization_id=org_id, technician_id=tid,
                achievement_type=atype, achievement_name=defn['name'],
                description=defn['description'], icon=defn['icon'],
                period_type=period_type, period_start=start, period_end=end,
            )
            db.add(ach)
            new_achievements.append(ach)

        if score.total_callbacks == 0 and score.jobs_completed >= 3:
            _award('zero_callbacks')
        if by_revenue and by_revenue[0].technician_id == tid:
            _award('revenue_king')
        if by_hours and by_hours[0].technician_id == tid:
            _award('iron_horse')
        if by_rating and by_rating[0].technician_id == tid and score.avg_customer_rating >= 4.5:
            _award('customer_favorite')

        # Check 5-star reviews
        five_star = db.query(FeedbackSurvey).filter(
            FeedbackSurvey.technician_id == tid,
            FeedbackSurvey.overall_rating == 5,
            FeedbackSurvey.status == 'completed',
            FeedbackSurvey.completed_at >= datetime.combine(start, datetime.min.time()),
            FeedbackSurvey.completed_at <= datetime.combine(end, datetime.max.time()),
        ).first()
        if five_star:
            _award('perfect_stars')

    db.commit()
    return new_achievements


def get_tech_trend(db, tech_id, org_id, period_type, n_periods=6):
    """Return last n periods of scores (oldest first)."""
    scores = db.query(TechPerformanceScore).filter(
        TechPerformanceScore.organization_id == org_id,
        TechPerformanceScore.technician_id == tech_id,
        TechPerformanceScore.period_type == period_type,
    ).order_by(TechPerformanceScore.period_start.desc()).limit(n_periods).all()
    return [s.to_dict() for s in reversed(scores)]


def get_leaderboard_data(db, org_id, period_type, start, end, division_id=None):
    """Fetch ranked leaderboard with trend deltas."""
    query = db.query(TechPerformanceScore).join(Technician).filter(
        TechPerformanceScore.organization_id == org_id,
        TechPerformanceScore.period_type == period_type,
        TechPerformanceScore.period_start == start,
    )
    if division_id:
        query = query.filter(Technician.division_id == division_id)

    current = query.order_by(TechPerformanceScore.rank).all()

    # Previous period for trend
    prev_start, prev_end = _get_previous_period(period_type, start)
    prev_scores = db.query(TechPerformanceScore).filter(
        TechPerformanceScore.organization_id == org_id,
        TechPerformanceScore.period_type == period_type,
        TechPerformanceScore.period_start == prev_start,
    ).all()
    prev_map = {s.technician_id: s for s in prev_scores}

    rows = []
    for s in current:
        prev = prev_map.get(s.technician_id)
        row = s.to_dict()
        row['score_delta'] = round(s.overall_score - prev.overall_score, 1) if prev else 0.0
        row['rank_delta'] = (prev.rank - s.rank) if prev and prev.rank else 0
        row['prev_score'] = round(prev.overall_score, 1) if prev else None

        achievements = db.query(TechAchievement).filter_by(
            organization_id=org_id, technician_id=s.technician_id,
            period_type=period_type, period_start=start,
        ).all()
        row['achievements'] = [a.to_dict() for a in achievements]
        rows.append(row)

    top = rows[0] if rows else None
    most_improved = max(rows, key=lambda r: r['score_delta']) if rows else None
    highest_rating = max(rows, key=lambda r: r['avg_customer_rating']) if rows else None
    most_efficient = max(rows, key=lambda r: r['efficiency_score']) if rows else None

    return {
        'rows': rows,
        'top_performer': top,
        'most_improved': most_improved,
        'highest_rating': highest_rating,
        'most_efficient': most_efficient,
        'period_start': start.isoformat(),
        'period_end': end.isoformat(),
        'period_type': period_type,
    }
