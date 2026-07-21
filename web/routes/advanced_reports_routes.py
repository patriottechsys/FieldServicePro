"""Advanced Reports Routes — Tech Leaderboard, Sales Pipeline, Achievements."""
from datetime import timezone, date, datetime, timedelta
from flask import (Blueprint, render_template, request, jsonify,
                   redirect, url_for, flash)
from flask_login import login_required, current_user
from sqlalchemy import func, desc

from models.database import get_session
from models.tech_performance import TechPerformanceScore, TechAchievement
from models.technician import Technician
from models.job import Job
from models.time_entry import TimeEntry
from models.feedback_survey import FeedbackSurvey
from models.callback import Callback
from models.invoice import Invoice
from models.division import Division
from web.auth import role_required
from web.utils.performance_engine import (
    get_leaderboard_data, get_tech_trend,
    calculate_tech_scores_for_period,
    calculate_and_assign_achievements,
    get_period_bounds, _get_previous_period,
)

advanced_reports_bp = Blueprint('advanced_reports', __name__, url_prefix='/reports')


def _parse_period(args):
    """Parse period filter. Returns (period_label, period_type, start, end)."""
    period = args.get('period', 'this_month')
    today = date.today()

    if period == 'this_week':
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        ptype = 'weekly'
    elif period == 'this_month':
        start = today.replace(day=1)
        end = (date(today.year, today.month + 1, 1) if today.month < 12
               else date(today.year + 1, 1, 1)) - timedelta(days=1)
        ptype = 'monthly'
    elif period == 'this_quarter':
        q = (today.month - 1) // 3
        start = date(today.year, q * 3 + 1, 1)
        em = q * 3 + 3
        end = (date(today.year, em + 1, 1) if em < 12
               else date(today.year + 1, 1, 1)) - timedelta(days=1)
        ptype = 'quarterly'
    else:
        start = today.replace(day=1)
        end = today
        ptype = 'monthly'

    return period, ptype, start, end


@advanced_reports_bp.route('/tech-leaderboard')
@login_required
def tech_leaderboard():
    """Technician Performance Leaderboard."""
    db = get_session()
    try:
        org_id = current_user.organization_id
        period, ptype, start, end = _parse_period(request.args)
        division_id = request.args.get('division_id', type=int)
        sort_by = request.args.get('sort', 'rank')
        sort_dir = request.args.get('dir', 'asc')

        # Auto-calculate if no scores
        count = db.query(func.count(TechPerformanceScore.id)).filter(
            TechPerformanceScore.organization_id == org_id,
            TechPerformanceScore.period_type == ptype,
            TechPerformanceScore.period_start == start,
        ).scalar() or 0

        if count == 0:
            scores = calculate_tech_scores_for_period(db, org_id, ptype, start, end)
            calculate_and_assign_achievements(db, org_id, ptype, start, end, scores)

        leaderboard = get_leaderboard_data(db, org_id, ptype, start, end, division_id)

        # Technician role: filter to self
        if current_user.role == 'technician':
            tech = db.query(Technician).filter_by(
                organization_id=org_id, user_id=current_user.id
            ).first()
            if tech:
                leaderboard['rows'] = [r for r in leaderboard['rows'] if r['technician_id'] == tech.id]

        # Sort
        sort_map = {
            'rank': 'rank', 'score': 'overall_score', 'rating': 'avg_customer_rating',
            'completion': 'completion_rate_score', 'revenue': 'total_revenue',
            'efficiency': 'efficiency_score',
        }
        key = sort_map.get(sort_by, 'rank')
        leaderboard['rows'].sort(key=lambda r: r.get(key, 0) or 0, reverse=(sort_dir == 'desc'))

        # Trend data for top 5
        top5 = [r['technician_id'] for r in leaderboard['rows'][:5]]
        trend_data = {tid: get_tech_trend(db, tid, org_id, ptype, 6) for tid in top5}
        tech_names = {r['technician_id']: r['tech_name'] for r in leaderboard['rows']}
        all_scores = [r['overall_score'] for r in leaderboard['rows']]

        divisions = db.query(Division).filter_by(organization_id=org_id, is_active=True).all()

        return render_template('reports/tech_leaderboard.html',
            active_page='reports', user=current_user,
            leaderboard=leaderboard, trend_data=trend_data,
            all_scores=all_scores, tech_names=tech_names,
            divisions=divisions, period=period, period_type=ptype,
            start=start, end=end, division_id=division_id,
            sort_by=sort_by, sort_dir=sort_dir,
            user_role=current_user.role, top5_ids=top5,
        )
    finally:
        db.close()


@advanced_reports_bp.route('/tech-leaderboard/recalculate', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def recalculate_scores():
    """Trigger score recalculation."""
    db = get_session()
    try:
        org_id = current_user.organization_id
        period = request.form.get('period', 'this_month')
        _, ptype, start, end = _parse_period({'period': period})

        scores = calculate_tech_scores_for_period(db, org_id, ptype, start, end)
        achievements = calculate_and_assign_achievements(db, org_id, ptype, start, end, scores)

        flash(f'Scores recalculated for {len(scores)} techs. {len(achievements)} new achievements.', 'success')
    finally:
        db.close()
    return redirect(url_for('advanced_reports.tech_leaderboard', period=period))


@advanced_reports_bp.route('/tech-leaderboard/tech/<int:tech_id>')
@login_required
def tech_detail_api(tech_id):
    """JSON detail for tech drill-down modal."""
    db = get_session()
    try:
        org_id = current_user.organization_id
        period, ptype, start, end = _parse_period(request.args)

        # Permission check
        if current_user.role == 'technician':
            own = db.query(Technician).filter_by(organization_id=org_id, user_id=current_user.id).first()
            if not own or own.id != tech_id:
                return jsonify({'error': 'Forbidden'}), 403

        tech = db.query(Technician).filter_by(id=tech_id, organization_id=org_id).first()
        if not tech:
            return jsonify({'error': 'Not found'}), 404

        score = db.query(TechPerformanceScore).filter_by(
            organization_id=org_id, technician_id=tech_id,
            period_type=ptype, period_start=start,
        ).first()

        trend = get_tech_trend(db, tech_id, org_id, ptype, 12)

        recent_fb = db.query(FeedbackSurvey).filter(
            FeedbackSurvey.technician_id == tech_id,
            FeedbackSurvey.comments.isnot(None),
            FeedbackSurvey.status == 'completed',
        ).order_by(desc(FeedbackSurvey.completed_at)).limit(5).all()

        recent_cb = db.query(Callback).filter(
            Callback.responsible_technician_id == tech_id,
        ).order_by(desc(Callback.created_at)).limit(5).all()

        total_jobs = db.query(func.count(Job.id)).filter(
            Job.organization_id == org_id,
            Job.assigned_technician_id == tech_id,
            Job.status == 'completed',
        ).scalar() or 0

        total_rev = float(db.query(func.sum(Invoice.total)).join(
            Job, Invoice.job_id == Job.id
        ).filter(
            Invoice.organization_id == org_id,
            Job.assigned_technician_id == tech_id,
        ).scalar() or 0)

        total_hrs = float(db.query(func.sum(TimeEntry.duration_hours)).filter(
            TimeEntry.technician_id == tech_id,
        ).scalar() or 0)

        achievements = db.query(TechAchievement).filter_by(
            organization_id=org_id, technician_id=tech_id,
            period_type=ptype, period_start=start,
        ).all()

        all_ach = db.query(TechAchievement).filter_by(
            organization_id=org_id, technician_id=tech_id,
        ).order_by(desc(TechAchievement.earned_at)).limit(10).all()

        score_data = score.to_dict() if score else {}

        # Strengths / improvements
        metrics = {}
        if score:
            metrics = {
                'Customer Rating': score.customer_rating_score or 0,
                'Completion Rate': score.completion_rate_score or 0,
                'Callback Rate': score.callback_rate_score or 0,
                'Utilization': score.utilization_score or 0,
                'Revenue': score.revenue_score or 0,
                'Efficiency': score.efficiency_score or 0,
                'Profitability': score.profitability_score or 0,
            }
        sorted_m = sorted(metrics.items(), key=lambda x: x[1], reverse=True)
        strengths = sorted_m[:2]
        improvements = sorted_m[-2:]

        return jsonify({
            'tech': {
                'id': tech.id, 'name': tech.full_name,
                'division': tech.division.name if tech.division else None,
            },
            'score': score_data,
            'trend': trend,
            'strengths': [{'metric': m, 'score': round(s, 1)} for m, s in strengths],
            'improvements': [{'metric': m, 'score': round(s, 1)} for m, s in improvements],
            'recent_feedback': [
                {'rating': f.overall_rating, 'comment': f.comments,
                 'date': f.completed_at.strftime('%b %d, %Y') if f.completed_at else ''}
                for f in recent_fb
            ],
            'recent_callbacks': [
                {'job_id': c.original_job_id, 'reason': c.reason or '',
                 'date': c.created_at.strftime('%b %d, %Y') if c.created_at else ''}
                for c in recent_cb
            ],
            'all_time': {'total_jobs': total_jobs, 'total_revenue': total_rev, 'total_hours': total_hrs},
            'achievements': [a.to_dict() for a in achievements],
            'all_achievements': [a.to_dict() for a in all_ach],
        })
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# TECH PROFILE (full page)
# ─────────────────────────────────────────────────────────────────────────────

@advanced_reports_bp.route('/tech-leaderboard/tech/<int:tech_id>/profile')
@login_required
def tech_profile(tech_id):
    """Full-page tech performance profile."""
    db = get_session()
    try:
        org_id = current_user.organization_id

        if current_user.role == 'technician':
            own = db.query(Technician).filter_by(organization_id=org_id, user_id=current_user.id).first()
            if not own or own.id != tech_id:
                flash('You can only view your own profile.', 'warning')
                return redirect(url_for('advanced_reports.tech_leaderboard'))

        period, ptype, start, end = _parse_period(request.args)
        tech = db.query(Technician).filter_by(id=tech_id, organization_id=org_id).first()
        if not tech:
            flash('Technician not found.', 'error')
            return redirect(url_for('advanced_reports.tech_leaderboard'))

        score = db.query(TechPerformanceScore).filter_by(
            organization_id=org_id, technician_id=tech_id,
            period_type=ptype, period_start=start,
        ).first()

        trend = get_tech_trend(db, tech_id, org_id, ptype, 12)

        achievements = db.query(TechAchievement).filter_by(
            organization_id=org_id, technician_id=tech_id,
        ).order_by(desc(TechAchievement.earned_at)).all()

        recent_fb = db.query(FeedbackSurvey).filter(
            FeedbackSurvey.technician_id == tech_id,
            FeedbackSurvey.status == 'completed',
        ).order_by(desc(FeedbackSurvey.completed_at)).limit(10).all()

        recent_cb = db.query(Callback).filter(
            Callback.responsible_technician_id == tech_id,
        ).order_by(desc(Callback.created_at)).limit(10).all()

        return render_template('reports/tech_profile.html',
            active_page='reports', user=current_user,
            tech=tech, score=score, trend=trend,
            achievements=achievements,
            recent_feedback=recent_fb, recent_callbacks=recent_cb,
            period=period, period_type=ptype, start=start, end=end,
        )
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# ACHIEVEMENTS
# ─────────────────────────────────────────────────────────────────────────────

@advanced_reports_bp.route('/tech-leaderboard/achievements')
@login_required
@role_required('admin', 'owner')
def achievements_list():
    """All achievements across techs."""
    db = get_session()
    try:
        org_id = current_user.organization_id
        achievements = db.query(TechAchievement).join(Technician).filter(
            TechAchievement.organization_id == org_id,
        ).order_by(desc(TechAchievement.earned_at)).limit(100).all()

        by_tech = {}
        for a in achievements:
            name = a.technician.full_name if a.technician else 'Unknown'
            by_tech.setdefault(name, []).append(a)

        return render_template('reports/achievements.html',
            active_page='reports', user=current_user,
            achievements=achievements, by_tech=by_tech,
        )
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# SALES PIPELINE DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@advanced_reports_bp.route('/sales-pipeline-dashboard')
@login_required
@role_required('admin', 'owner', 'dispatcher')
def sales_pipeline():
    """Sales Pipeline Dashboard."""
    db = get_session()
    try:
        from models.quote import Quote
        from models.contract import Contract
        from models.recurring_schedule import RecurringSchedule
        from web.utils.pipeline_engine import (
            get_funnel_data, get_aging_analysis,
            get_revenue_forecast, get_win_loss_analysis,
        )

        org_id = current_user.organization_id
        today = date.today()

        try:
            start = date.fromisoformat(request.args.get('start', ''))
        except (ValueError, TypeError):
            start = date(today.year, 1, 1)
        try:
            end = date.fromisoformat(request.args.get('end', ''))
        except (ValueError, TypeError):
            end = today

        division_id = request.args.get('division_id', type=int)

        funnel = get_funnel_data(db, org_id, start, end, division_id)
        aging = get_aging_analysis(db, org_id)
        forecast = get_revenue_forecast(db, org_id)
        win_loss = get_win_loss_analysis(db, org_id)

        top_opps = db.query(Quote).filter(
            Quote.organization_id == org_id,
            Quote.status.in_(['draft', 'sent', 'approved']),
        ).order_by(desc(Quote.total)).limit(10).all()

        divisions = db.query(Division).filter_by(organization_id=org_id, is_active=True).all()

        # Avg days to close
        won = db.query(Quote).filter(
            Quote.organization_id == org_id,
            Quote.status.in_(['converted', 'accepted']),
        ).all()
        days_list = [(q.updated_at - q.created_at).days for q in won if q.created_at and q.updated_at]
        avg_close = round(sum(days_list) / len(days_list), 1) if days_list else 0

        return render_template('reports/sales_pipeline_dashboard.html',
            active_page='reports', user=current_user,
            funnel=funnel, aging=aging, forecast=forecast, win_loss=win_loss,
            top_opportunities=top_opps, divisions=divisions,
            start=start, end=end, division_id=division_id,
            avg_days_to_close=avg_close, today=today,
        )
    finally:
        db.close()


@advanced_reports_bp.route('/sales-pipeline-dashboard/update-stage', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def update_quote_stage():
    """Update quote status via Kanban drag."""
    db = get_session()
    try:
        from models.quote import Quote
        data = request.get_json(silent=True) or {}
        quote_id = data.get('quote_id')
        new_status = data.get('status')
        if new_status not in ('draft', 'sent', 'approved', 'converted', 'declined', 'expired'):
            return jsonify({'error': 'Invalid status'}), 400
        q = db.query(Quote).filter_by(id=quote_id, organization_id=current_user.organization_id).first()
        if not q:
            return jsonify({'error': 'Not found'}), 404
        q.status = new_status
        q.updated_at = datetime.now(timezone.utc)
        db.commit()
        return jsonify({'success': True, 'quote_id': quote_id, 'status': new_status})
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# CAPACITY PLANNER
# ─────────────────────────────────────────────────────────────────────────────

@advanced_reports_bp.route('/capacity-planner')
@login_required
@role_required('admin', 'owner', 'dispatcher')
def capacity_planner():
    """Capacity Planning Forecaster."""
    db = get_session()
    try:
        from web.utils.capacity_engine import (
            get_capacity_data, get_unscheduled_work,
            get_demand_forecast, generate_capacity_alerts,
        )
        org_id = current_user.organization_id
        today = date.today()
        monday = today - timedelta(days=today.weekday())

        try:
            start = date.fromisoformat(request.args.get('start', ''))
        except (ValueError, TypeError):
            start = monday
        try:
            end = date.fromisoformat(request.args.get('end', ''))
        except (ValueError, TypeError):
            end = monday + timedelta(days=13)

        if (end - start).days > 28:
            end = start + timedelta(days=27)

        division_id = request.args.get('division_id', type=int)

        capacity = get_capacity_data(db, org_id, start, end, division_id)
        unscheduled = get_unscheduled_work(db, org_id)
        demand = get_demand_forecast(db, org_id, start, end)
        alerts = generate_capacity_alerts(db, org_id, capacity)
        divisions = db.query(Division).filter_by(organization_id=org_id, is_active=True).all()

        return render_template('reports/capacity_planner.html',
            active_page='reports', user=current_user,
            capacity=capacity, unscheduled=unscheduled, demand=demand,
            alerts=alerts, divisions=divisions,
            start=start, end=end, division_id=division_id, today=today,
        )
    finally:
        db.close()
