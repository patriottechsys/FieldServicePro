"""Payroll dashboard, period detail, calculation, finalization, and export."""
from datetime import timezone, date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required, current_user

from models.database import get_session
from models.payroll_period import PayrollPeriod, PAYROLL_STATUSES, PAY_FREQUENCIES
from models.payroll_line_item import PayrollLineItem
from models.technician import Technician
from models.time_entry import TimeEntry
from models.division import Division
from web.auth import role_required

payroll_bp = Blueprint('payroll', __name__)


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(val, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


# ── Dashboard ─────────────────────────────────────────────────────────────────

@payroll_bp.route('/payroll')
@login_required
@role_required('admin', 'owner')
def payroll_dashboard():
    db = get_session()
    try:
        from web.utils.payroll_utils import get_or_create_current_period
        current_period = get_or_create_current_period(db, 'biweekly')
        db.commit()

        past_periods = db.query(PayrollPeriod).filter(
            PayrollPeriod.id != current_period.id
        ).order_by(PayrollPeriod.start_date.desc()).limit(12).all()

        tech_count = db.query(Technician).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).count()

        return render_template('payroll/dashboard.html',
            active_page='payroll', user=current_user, divisions=_get_divisions(),
            current_period=current_period, past_periods=past_periods,
            tech_count=tech_count, today=date.today(),
            statuses=PAYROLL_STATUSES, frequencies=PAY_FREQUENCIES,
        )
    finally:
        db.close()


# ── Create Period ─────────────────────────────────────────────────────────────

@payroll_bp.route('/payroll/new', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'owner')
def payroll_new():
    db = get_session()
    try:
        if request.method == 'POST':
            start = _parse_date(request.form.get('start_date'))
            end = _parse_date(request.form.get('end_date'))
            if not start or not end or start >= end:
                flash('Valid start and end dates required.', 'error')
                return redirect(url_for('payroll.payroll_new'))

            overlap = db.query(PayrollPeriod).filter(
                PayrollPeriod.start_date <= end,
                PayrollPeriod.end_date >= start,
            ).first()
            if overlap:
                flash(f'Overlaps with: {overlap.period_name}', 'error')
                return redirect(url_for('payroll.payroll_new'))

            from web.utils.payroll_utils import generate_period_name
            period = PayrollPeriod(
                period_name=generate_period_name(start, end),
                start_date=start, end_date=end,
                pay_frequency=request.form.get('pay_frequency', 'biweekly'),
                status='open',
            )
            db.add(period)
            db.commit()
            flash('Pay period created.', 'success')
            return redirect(url_for('payroll.payroll_detail', period_id=period.id))

        return render_template('payroll/payroll_form.html',
            active_page='payroll', user=current_user, divisions=_get_divisions(),
            today=date.today(), frequencies=PAY_FREQUENCIES,
        )
    finally:
        db.close()


# ── Period Detail ─────────────────────────────────────────────────────────────

@payroll_bp.route('/payroll/<int:period_id>')
@login_required
@role_required('admin', 'owner')
def payroll_detail(period_id):
    db = get_session()
    try:
        period = db.query(PayrollPeriod).filter_by(id=period_id).first()
        if not period:
            flash('Period not found.', 'error')
            return redirect(url_for('payroll.payroll_dashboard'))

        from web.utils.payroll_utils import get_period_warnings
        warnings = get_period_warnings(db, period) if period.line_items else []

        totals = {
            'regular_hours': sum(float(li.regular_hours or 0) for li in period.line_items),
            'overtime_hours': sum(float(li.overtime_hours or 0) for li in period.line_items),
            'double_time_hours': sum(float(li.double_time_hours or 0) for li in period.line_items),
            'regular_pay': sum(float(li.regular_pay or 0) for li in period.line_items),
            'overtime_pay': sum(float(li.overtime_pay or 0) for li in period.line_items),
            'double_time_pay': sum(float(li.double_time_pay or 0) for li in period.line_items),
            'gross_pay': sum(li.gross_pay for li in period.line_items),
            'reimbursements': sum(float(li.reimbursable_expenses or 0) for li in period.line_items),
            'total_compensation': sum(li.total_compensation for li in period.line_items),
        }
        totals['total_hours'] = totals['regular_hours'] + totals['overtime_hours'] + totals['double_time_hours']

        return render_template('payroll/payroll_detail.html',
            active_page='payroll', user=current_user, divisions=_get_divisions(),
            period=period, warnings=warnings, totals=totals, today=date.today(),
        )
    finally:
        db.close()


# ── Calculate ─────────────────────────────────────────────────────────────────

@payroll_bp.route('/payroll/<int:period_id>/calculate', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def payroll_calculate(period_id):
    db = get_session()
    try:
        period = db.query(PayrollPeriod).filter_by(id=period_id).first()
        if not period:
            flash('Period not found.', 'error')
            return redirect(url_for('payroll.payroll_dashboard'))
        if period.status == 'finalized':
            flash('Finalized period cannot be recalculated.', 'error')
            return redirect(url_for('payroll.payroll_detail', period_id=period_id))

        from web.utils.payroll_utils import calculate_period
        calculate_period(db, period, current_user.organization_id)
        db.commit()

        flash(f'Payroll calculated for {len(period.line_items)} employee(s). '
              f'Total gross: ${float(period.total_gross_pay or 0):,.2f}', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Error: {e}', 'error')
    finally:
        db.close()
    return redirect(url_for('payroll.payroll_detail', period_id=period_id))


# ── Finalize ──────────────────────────────────────────────────────────────────

@payroll_bp.route('/payroll/<int:period_id>/finalize', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def payroll_finalize(period_id):
    db = get_session()
    try:
        period = db.query(PayrollPeriod).filter_by(id=period_id).first()
        if not period:
            flash('Period not found.', 'error')
            return redirect(url_for('payroll.payroll_dashboard'))
        if not period.line_items:
            flash('Cannot finalize: no payroll data.', 'error')
            return redirect(url_for('payroll.payroll_detail', period_id=period_id))

        from web.utils.payroll_utils import finalize_period
        finalize_period(period, current_user.id)
        db.commit()
        flash(f'Period finalized. Total: ${period.total_compensation:,.2f}', 'success')
    finally:
        db.close()
    return redirect(url_for('payroll.payroll_detail', period_id=period_id))


# ── Re-open ───────────────────────────────────────────────────────────────────

@payroll_bp.route('/payroll/<int:period_id>/reopen', methods=['POST'])
@login_required
@role_required('owner')
def payroll_reopen(period_id):
    db = get_session()
    try:
        period = db.query(PayrollPeriod).filter_by(id=period_id).first()
        if period and period.status in ('finalized', 'exported'):
            period.status = 'open'
            period.finalized_by = None
            period.finalized_at = None
            db.commit()
            flash('Period re-opened.', 'warning')
    finally:
        db.close()
    return redirect(url_for('payroll.payroll_detail', period_id=period_id))


# ── Update Line Item Status ───────────────────────────────────────────────────

@payroll_bp.route('/payroll/line-item/<int:item_id>/status', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def update_line_item_status(item_id):
    db = get_session()
    try:
        item = db.query(PayrollLineItem).filter_by(id=item_id).first()
        if not item:
            return jsonify({'success': False, 'error': 'Not found'}), 404
        new_status = request.form.get('status', 'draft')
        if new_status in ('draft', 'reviewed', 'approved'):
            item.status = new_status
            db.commit()
            return jsonify({'success': True, 'status': item.status})
        return jsonify({'success': False, 'error': 'Invalid status'}), 400
    finally:
        db.close()


# ── CSV Export ────────────────────────────────────────────────────────────────

@payroll_bp.route('/payroll/<int:period_id>/export')
@login_required
@role_required('admin', 'owner')
def payroll_export(period_id):
    db = get_session()
    try:
        period = db.query(PayrollPeriod).filter_by(id=period_id).first()
        if not period:
            flash('Period not found.', 'error')
            return redirect(url_for('payroll.payroll_dashboard'))

        export_type = request.args.get('type', 'summary')

        from web.utils.payroll_utils import export_period_csv, export_period_detailed_csv
        if export_type == 'detailed':
            csv_data = export_period_detailed_csv(db, period)
            filename = f'payroll_detailed_{period.start_date}_{period.end_date}.csv'
        else:
            csv_data = export_period_csv(period)
            filename = f'payroll_{period.start_date}_{period.end_date}.csv'

        if period.status == 'finalized':
            period.status = 'exported'
            period.exported_at = datetime.now(timezone.utc)
            db.commit()

        return Response(csv_data, mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="{filename}"'})
    finally:
        db.close()


# ── Tech Drill-down ───────────────────────────────────────────────────────────

@payroll_bp.route('/payroll/<int:period_id>/tech/<int:tech_id>')
@login_required
@role_required('admin', 'owner')
def tech_entries(period_id, tech_id):
    db = get_session()
    try:
        period = db.query(PayrollPeriod).filter_by(id=period_id).first()
        tech = db.query(Technician).filter_by(id=tech_id).first()
        if not period or not tech:
            flash('Not found.', 'error')
            return redirect(url_for('payroll.payroll_dashboard'))

        line_item = db.query(PayrollLineItem).filter_by(
            period_id=period_id, technician_id=tech_id
        ).first()

        entries = db.query(TimeEntry).filter(
            TimeEntry.technician_id == tech_id,
            TimeEntry.date >= period.start_date,
            TimeEntry.date <= period.end_date,
        ).order_by(TimeEntry.date, TimeEntry.start_time).all()

        return render_template('payroll/tech_entries.html',
            active_page='payroll', user=current_user, divisions=_get_divisions(),
            period=period, tech=tech, line_item=line_item, entries=entries,
        )
    finally:
        db.close()
