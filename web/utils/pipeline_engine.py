"""Sales Pipeline Engine — funnel data, aging, forecast, win/loss analysis."""
from datetime import timezone, date, datetime, timedelta
from sqlalchemy import func
from models.quote import Quote
from models.job import Job
from models.communication import CommunicationLog


PIPELINE_STAGES = [
    ('draft', 'Draft', 0.10),
    ('sent', 'Sent', 0.40),
    ('follow_up', 'Follow-Up Needed', 0.40),
    ('approved', 'Approved', 0.90),
    ('converted', 'Won (Converted)', 1.00),
    ('declined', 'Lost (Declined)', 0.00),
    ('expired', 'Lost (Expired)', 0.00),
]


def get_funnel_data(db, org_id, start=None, end=None, division_id=None):
    """Build pipeline funnel: quote counts and values per stage."""
    q = db.query(Quote).filter(Quote.organization_id == org_id)
    if start:
        q = q.filter(Quote.created_at >= datetime.combine(start, datetime.min.time()))
    if end:
        q = q.filter(Quote.created_at <= datetime.combine(end, datetime.max.time()))
    if division_id:
        q = q.filter(Quote.division_id == division_id)

    all_quotes = q.all()

    stages = {}
    for key, label, prob in PIPELINE_STAGES:
        stages[key] = {
            'key': key, 'label': label, 'probability': prob,
            'count': 0, 'value': 0.0, 'weighted_value': 0.0,
            'quotes': [], 'conversion_rate': 0.0,
        }

    for quote in all_quotes:
        status = quote.status or 'draft'
        # Classify sent quotes as follow_up if stale
        if status == 'sent':
            stage_key = _classify_sent(db, quote)
        elif status in ('converted', 'accepted'):
            stage_key = 'converted'
        elif status in ('declined', 'rejected'):
            stage_key = 'declined'
        elif status in stages:
            stage_key = status
        else:
            stage_key = 'draft'

        if stage_key in stages:
            val = float(quote.total or 0)
            prob = stages[stage_key]['probability']
            stages[stage_key]['count'] += 1
            stages[stage_key]['value'] += val
            stages[stage_key]['weighted_value'] += val * prob
            stages[stage_key]['quotes'].append({
                'id': quote.id, 'quote_number': quote.quote_number or '',
                'client_name': quote.client.display_name if quote.client else 'Unknown',
                'value': val, 'status': status, 'stage': stage_key,
                'days_open': (date.today() - quote.created_at.date()).days if quote.created_at else 0,
            })

    total_pipeline = sum(s['value'] for k, s in stages.items() if k not in ('converted', 'declined', 'expired'))
    weighted_pipeline = sum(s['weighted_value'] for k, s in stages.items() if k not in ('converted', 'declined', 'expired'))

    return {
        'stages': stages,
        'total_pipeline_value': total_pipeline,
        'weighted_pipeline_value': weighted_pipeline,
        'total_count': len(all_quotes),
    }


def _classify_sent(db, quote):
    """Sent quotes become follow_up if >7d with no recent communication."""
    if not quote.created_at:
        return 'sent'
    days = (date.today() - quote.created_at.date()).days
    if days < 7:
        return 'sent'
    last_comm = db.query(CommunicationLog).filter(
        CommunicationLog.client_id == quote.client_id,
        CommunicationLog.communication_date >= datetime.now(timezone.utc) - timedelta(days=7),
    ).first()
    return 'sent' if last_comm else 'follow_up'


def get_aging_analysis(db, org_id, threshold=14):
    """Group open quotes by age buckets."""
    open_q = db.query(Quote).filter(
        Quote.organization_id == org_id,
        Quote.status.in_(['draft', 'sent', 'approved']),
    ).all()

    buckets = {
        '0-7': {'label': '0-7 days', 'quotes': [], 'value': 0.0},
        '8-14': {'label': '8-14 days', 'quotes': [], 'value': 0.0},
        '15-30': {'label': '15-30 days', 'quotes': [], 'value': 0.0},
        '31-60': {'label': '31-60 days', 'quotes': [], 'value': 0.0},
        '60+': {'label': '60+ days', 'quotes': [], 'value': 0.0},
    }
    stale = []

    for q in open_q:
        if not q.created_at:
            continue
        days = (date.today() - q.created_at.date()).days
        val = float(q.total or 0)
        qd = {'id': q.id, 'quote_number': q.quote_number or '',
              'client_name': q.client.display_name if q.client else 'Unknown',
              'value': val, 'status': q.status, 'days_open': days}

        if days <= 7: b = '0-7'
        elif days <= 14: b = '8-14'
        elif days <= 30: b = '15-30'
        elif days <= 60: b = '31-60'
        else: b = '60+'
        buckets[b]['quotes'].append(qd)
        buckets[b]['value'] += val
        if days >= threshold:
            stale.append(qd)

    return {
        'buckets': buckets,
        'stale_quotes': sorted(stale, key=lambda x: x['days_open'], reverse=True),
        'stale_count': len(stale),
        'stale_value': sum(x['value'] for x in stale),
    }


def get_revenue_forecast(db, org_id):
    """3-month forecast from quotes + recurring + contracts."""
    today = date.today()
    months = []
    for i in range(3):
        mn = (today.month + i - 1) % 12 + 1
        yr = today.year + (today.month + i - 1) // 12
        months.append(date(yr, mn, 1))

    forecast = {}
    for m in months:
        label = m.strftime('%b %Y')
        forecast[label] = {
            'month': label, 'date': m.isoformat(),
            'optimistic': 0.0, 'weighted': 0.0, 'conservative': 0.0,
            'sources': {'approved_quotes': 0.0, 'sent_quotes': 0.0, 'recurring': 0.0, 'contracts': 0.0},
        }

    # Approved quotes → 90%
    for q in db.query(Quote).filter_by(organization_id=org_id, status='approved').all():
        val = float(q.total or 0)
        label = months[0].strftime('%b %Y')
        if label in forecast:
            forecast[label]['sources']['approved_quotes'] += val
            forecast[label]['optimistic'] += val
            forecast[label]['weighted'] += val * 0.9
            forecast[label]['conservative'] += val * 0.9

    # Sent quotes → 40%
    for q in db.query(Quote).filter_by(organization_id=org_id, status='sent').all():
        val = float(q.total or 0)
        label = months[0].strftime('%b %Y')
        if label in forecast:
            forecast[label]['sources']['sent_quotes'] += val
            forecast[label]['optimistic'] += val
            forecast[label]['weighted'] += val * 0.4

    # Recurring schedules
    try:
        from models.recurring_schedule import RecurringSchedule
        for rec in db.query(RecurringSchedule).filter_by(organization_id=org_id, is_active=True).all():
            mv = _recurring_monthly(rec)
            for label in forecast:
                forecast[label]['sources']['recurring'] += mv
                forecast[label]['optimistic'] += mv
                forecast[label]['weighted'] += mv * 0.95
                forecast[label]['conservative'] += mv * 0.95
    except Exception:
        pass

    # Active contracts
    try:
        from models.contract import Contract
        for c in db.query(Contract).filter_by(organization_id=org_id, status='active').all():
            mv = _contract_monthly(c)
            for label in forecast:
                forecast[label]['sources']['contracts'] += mv
                forecast[label]['optimistic'] += mv
                forecast[label]['weighted'] += mv
                forecast[label]['conservative'] += mv
    except Exception:
        pass

    return {
        'months': list(forecast.values()),
        'total_weighted': sum(m['weighted'] for m in forecast.values()),
        'total_optimistic': sum(m['optimistic'] for m in forecast.values()),
        'total_conservative': sum(m['conservative'] for m in forecast.values()),
    }


def _recurring_monthly(rec):
    base = float(getattr(rec, 'estimated_amount', 0) or 0)
    freq = getattr(rec, 'frequency', 'monthly')
    return {'weekly': base * 4.3, 'biweekly': base * 2.15, 'monthly': base,
            'quarterly': base / 3, 'annually': base / 12}.get(freq, base)


def _contract_monthly(c):
    total = float(getattr(c, 'value', 0) or 0)
    s, e = getattr(c, 'start_date', None), getattr(c, 'end_date', None)
    if s and e and hasattr(s, 'year'):
        months = max(1, (e.year - s.year) * 12 + (e.month - s.month))
        return total / months
    return total / 12


def get_win_loss_analysis(db, org_id, days=90):
    """Win/loss rates over past N days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    closed = db.query(Quote).filter(
        Quote.organization_id == org_id,
        Quote.status.in_(['converted', 'accepted', 'declined', 'rejected', 'expired']),
        Quote.updated_at >= since,
    ).all()

    won = [q for q in closed if q.status in ('converted', 'accepted')]
    lost = [q for q in closed if q.status in ('declined', 'rejected', 'expired')]
    total = len(closed)
    win_rate = round((len(won) / total) * 100, 1) if total else 0
    avg_deal = round(sum(float(q.total or 0) for q in won) / len(won), 2) if won else 0

    buckets = {'<$1K': {'won': 0, 'lost': 0}, '$1K-$5K': {'won': 0, 'lost': 0},
               '$5K-$10K': {'won': 0, 'lost': 0}, '$10K+': {'won': 0, 'lost': 0}}
    for q in closed:
        val = float(q.total or 0)
        outcome = 'won' if q.status in ('converted', 'accepted') else 'lost'
        if val < 1000: buckets['<$1K'][outcome] += 1
        elif val < 5000: buckets['$1K-$5K'][outcome] += 1
        elif val < 10000: buckets['$5K-$10K'][outcome] += 1
        else: buckets['$10K+'][outcome] += 1

    return {
        'total_closed': total, 'won_count': len(won), 'lost_count': len(lost),
        'win_rate': win_rate, 'avg_deal_size': avg_deal,
        'value_buckets': buckets, 'days_analyzed': days,
    }
