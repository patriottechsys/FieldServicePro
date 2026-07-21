"""Time Tracking routes: dashboard, entries, approvals, my-time, export, reports, API."""
import csv
import io
from datetime import timezone, datetime, date, timedelta
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, Response, abort
)
from flask_login import login_required, current_user
from sqlalchemy import func, desc
from models.database import get_session
from models.time_entry import TimeEntry, ActiveClock
from models.job import Job
from models.job_phase import JobPhase
from models.technician import Technician
from models.division import Division
from web.auth import role_required
from web.utils.time_tracking_utils import (
    clock_in, clock_out, switch_job, get_active_clock,
    submit_entries, approve_entries, reject_entries,
    get_job_labor_summary,
)
from web.utils.overtime_engine import get_overtime_alerts, calculate_overtime_for_tech_day

time_tracking_bp = Blueprint('time_tracking', __name__, url_prefix='/time-tracking')


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


def _get_tech_for_user(db):
    """Get Technician record linked to current user."""
    return db.query(Technician).filter_by(user_id=current_user.id).first()


def _can_admin():
    return current_user.role in ('owner', 'admin')


def _can_dispatch():
    return current_user.role in ('owner', 'admin', 'dispatcher')


# ══════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════════════════════

@time_tracking_bp.route('/')
@login_required
def tt_dashboard():
    db = get_session()
    try:
        today = date.today()

        active_clocks = db.query(ActiveClock).all()
        today_entries = db.query(TimeEntry).filter(TimeEntry.date == today).all()
        total_hours = sum(float(e.duration_hours or 0) for e in today_entries)
        total_cost = sum(float(e.labor_cost or 0) for e in today_entries)
        pending_count = db.query(TimeEntry).filter_by(status='submitted').count()
        ot_alerts = get_overtime_alerts()
        technicians = db.query(Technician).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).all()

        return render_template('time_tracking/dashboard.html',
            active_page='time_tracking', user=current_user, divisions=_get_divisions(),
            active_clocks=active_clocks, today_entries=today_entries,
            total_hours=round(total_hours, 2), total_cost=round(total_cost, 2),
            active_count=len(active_clocks), pending_count=pending_count,
            ot_alerts=ot_alerts, technicians=technicians, today=today,
            can_admin=_can_admin(),
        )
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════
#  ENTRIES LIST
# ══════════════════════════════════════════════════════════════════════════

@time_tracking_bp.route('/entries')
@login_required
def tt_entries():
    db = get_session()
    try:
        query = db.query(TimeEntry)

        # Techs only see their own
        tech = _get_tech_for_user(db)
        if current_user.role == 'technician' and tech:
            query = query.filter(TimeEntry.technician_id == tech.id)

        # Filters
        tech_filter = request.args.get('technician_id', type=int)
        status_filter = request.args.get('status', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')

        if tech_filter and current_user.role != 'technician':
            query = query.filter(TimeEntry.technician_id == tech_filter)
        if status_filter:
            query = query.filter(TimeEntry.status == status_filter)
        if date_from:
            try:
                query = query.filter(TimeEntry.date >= datetime.strptime(date_from, '%Y-%m-%d').date())
            except ValueError:
                pass
        if date_to:
            try:
                query = query.filter(TimeEntry.date <= datetime.strptime(date_to, '%Y-%m-%d').date())
            except ValueError:
                pass

        entries = query.order_by(desc(TimeEntry.date), desc(TimeEntry.created_at)).limit(200).all()
        total_hours = sum(float(e.duration_hours or 0) for e in entries)
        total_cost = sum(float(e.labor_cost or 0) for e in entries)

        technicians = db.query(Technician).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).all()

        return render_template('time_tracking/entries.html',
            active_page='time_tracking', user=current_user, divisions=_get_divisions(),
            entries=entries, total_hours=round(total_hours, 2),
            total_cost=round(total_cost, 2), technicians=technicians,
            filter_tech=tech_filter, filter_status=status_filter,
            filter_date_from=date_from, filter_date_to=date_to,
            can_admin=_can_admin(),
        )
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════
#  ENTRY CREATE / EDIT
# ══════════════════════════════════════════════════════════════════════════

@time_tracking_bp.route('/entries/new', methods=['GET', 'POST'])
@login_required
def tt_entry_new():
    db = get_session()
    try:
        if request.method == 'POST':
            f = request.form
            tech = _get_tech_for_user(db)
            tech_id = int(f.get('technician_id', 0)) if _can_admin() else (tech.id if tech else 0)

            entry_date = f.get('date', '')
            start_time = f.get('start_time', '')
            end_time = f.get('end_time', '')
            duration = f.get('duration_hours', '')

            if not tech_id or not f.get('job_id') or not entry_date:
                flash('Technician, job, and date are required.', 'danger')
            else:
                try:
                    d = datetime.strptime(entry_date, '%Y-%m-%d').date()
                except ValueError:
                    flash('Invalid date.', 'danger')
                    d = None

                if d:
                    st = datetime.strptime(start_time, '%H:%M').time() if start_time else None
                    et = datetime.strptime(end_time, '%H:%M').time() if end_time else None

                    if st and et and not duration:
                        dt_s = datetime.combine(d, st)
                        dt_e = datetime.combine(d, et)
                        if dt_e < dt_s:
                            dt_e += timedelta(days=1)
                        dur = round((dt_e - dt_s).total_seconds() / 3600, 2)
                    elif duration:
                        dur = float(duration)
                    else:
                        dur = 0

                    tech_obj = db.query(Technician).filter_by(id=tech_id).first()
                    job = db.query(Job).filter_by(id=int(f.get('job_id'))).first()

                    entry = TimeEntry(
                        technician_id=tech_id,
                        job_id=int(f.get('job_id')),
                        phase_id=int(f.get('phase_id')) if f.get('phase_id') else None,
                        project_id=job.project_id if job else None,
                        entry_type=f.get('entry_type', 'regular'),
                        date=d,
                        start_time=st,
                        end_time=et,
                        duration_hours=dur,
                        billable=f.get('billable') != 'false',
                        hourly_rate=float(f.get('hourly_rate') or (tech_obj.hourly_rate if tech_obj else 55)),
                        billable_rate=float(f.get('billable_rate') or (getattr(tech_obj, 'billable_rate', 95) if tech_obj else 95)),
                        description=f.get('description', '').strip() or None,
                        status='submitted' if f.get('action') == 'submit' else 'draft',
                        source='manual',
                        created_by=current_user.id,
                    )
                    entry.compute_costs()
                    db.add(entry)
                    db.commit()
                    calculate_overtime_for_tech_day(tech_id, d)
                    flash('Time entry saved.', 'success')
                    return redirect(url_for('time_tracking.tt_entries'))

        tech = _get_tech_for_user(db)
        technicians = db.query(Technician).filter_by(
            organization_id=current_user.organization_id, is_active=True).all()
        jobs = db.query(Job).filter(
            Job.organization_id == current_user.organization_id,
            Job.status.notin_(['completed', 'cancelled'])
        ).order_by(desc(Job.id)).limit(100).all()

        return render_template('time_tracking/entry_form.html',
            active_page='time_tracking', user=current_user, divisions=_get_divisions(),
            entry=None, technicians=technicians, jobs=jobs,
            default_tech_id=tech.id if tech else None,
            default_rate=tech.hourly_rate if tech else 55,
            default_billable_rate=getattr(tech, 'billable_rate', 95) if tech else 95,
            can_admin=_can_admin(), today=date.today(),
        )
    finally:
        db.close()


@time_tracking_bp.route('/entries/<int:entry_id>/delete', methods=['POST'])
@login_required
def tt_entry_delete(entry_id):
    db = get_session()
    try:
        entry = db.query(TimeEntry).filter_by(id=entry_id).first()
        if not entry:
            abort(404)
        if entry.status not in ('draft', 'rejected') and not _can_admin():
            flash('Only draft or rejected entries can be deleted.', 'warning')
            return redirect(url_for('time_tracking.tt_entries'))
        db.delete(entry)
        db.commit()
        flash('Time entry deleted.', 'success')
    finally:
        db.close()
    return redirect(url_for('time_tracking.tt_entries'))


# ══════════════════════════════════════════════════════════════════════════
#  APPROVALS
# ══════════════════════════════════════════════════════════════════════════

@time_tracking_bp.route('/approvals')
@login_required
@role_required('owner', 'admin')
def tt_approvals():
    db = get_session()
    try:
        pending = db.query(TimeEntry).filter_by(status='submitted').order_by(
            TimeEntry.date.desc(), TimeEntry.technician_id
        ).all()

        total_hours = sum(float(e.duration_hours or 0) for e in pending)
        total_cost = sum(float(e.labor_cost or 0) for e in pending)

        by_tech = {}
        for e in pending:
            tid = e.technician_id
            if tid not in by_tech:
                by_tech[tid] = {
                    'name': e.technician.full_name if e.technician else 'Unknown',
                    'entries': [], 'total_hours': 0, 'total_cost': 0,
                }
            by_tech[tid]['entries'].append(e)
            by_tech[tid]['total_hours'] += float(e.duration_hours or 0)
            by_tech[tid]['total_cost'] += float(e.labor_cost or 0)

        return render_template('time_tracking/approvals.html',
            active_page='time_tracking', user=current_user, divisions=_get_divisions(),
            pending=pending, by_tech=by_tech,
            pending_count=len(pending),
            pending_hours=round(total_hours, 2),
            pending_cost=round(total_cost, 2),
        )
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════
#  EXPORT
# ══════════════════════════════════════════════════════════════════════════

@time_tracking_bp.route('/export', methods=['GET', 'POST'])
@login_required
@role_required('owner', 'admin')
def tt_export():
    db = get_session()
    try:
        today = date.today()
        d_from = request.args.get('date_from', (today - timedelta(days=13)).isoformat())
        d_to = request.args.get('date_to', today.isoformat())

        try:
            start = datetime.strptime(d_from, '%Y-%m-%d').date()
            end = datetime.strptime(d_to, '%Y-%m-%d').date()
        except ValueError:
            start, end = today - timedelta(days=13), today

        entries = db.query(TimeEntry).filter(
            TimeEntry.status == 'approved',
            TimeEntry.date >= start,
            TimeEntry.date <= end,
        ).order_by(TimeEntry.technician_id, TimeEntry.date).all()

        if request.method == 'POST' and request.form.get('action') == 'export_csv':
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Employee', 'ID', 'Date', 'Job', 'Hours', 'Rate', 'Type', 'Pay', 'Description'])
            for e in entries:
                writer.writerow([
                    e.technician.full_name if e.technician else '',
                    e.technician_id, e.date.isoformat(),
                    e.job.job_number if e.job else '',
                    float(e.duration_hours or 0), float(e.hourly_rate or 0),
                    e.entry_type, float(e.labor_cost or 0), e.description or '',
                ])
            now = datetime.now(timezone.utc)
            for e in entries:
                e.status = 'exported'
                e.exported_at = now
            db.commit()
            output.seek(0)
            return Response(output.getvalue(), mimetype='text/csv',
                           headers={'Content-Disposition': f'attachment; filename=payroll_{start}_{end}.csv'})

        # Summary
        summary = {}
        for e in entries:
            tid = e.technician_id
            if tid not in summary:
                summary[tid] = {'name': e.technician.full_name if e.technician else 'Unknown',
                                'regular_hours': 0, 'ot_hours': 0, 'total_hours': 0, 'total_pay': 0}
            h = float(e.duration_hours or 0)
            c = float(e.labor_cost or 0)
            if e.entry_type == 'overtime':
                summary[tid]['ot_hours'] += h
            else:
                summary[tid]['regular_hours'] += h
            summary[tid]['total_hours'] += h
            summary[tid]['total_pay'] += c

        technicians = db.query(Technician).filter_by(
            organization_id=current_user.organization_id, is_active=True).all()

        return render_template('time_tracking/export.html',
            active_page='time_tracking', user=current_user, divisions=_get_divisions(),
            entries=entries, summary=summary,
            date_from=start.isoformat(), date_to=end.isoformat(),
            technicians=technicians, entry_count=len(entries),
        )
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════
#  API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════

@time_tracking_bp.route('/api/clock-in', methods=['POST'])
@login_required
def api_clock_in():
    from web.utils.validation import validate, ClockInSchema
    data = request.get_json()
    db = get_session()
    try:
        tech = _get_tech_for_user(db)
        if not tech and current_user.role != 'technician':
            pass  # admin: require explicit technician_id
        data_for_val = {**data}
        if not data_for_val.get('technician_id') and tech:
            data_for_val['technician_id'] = tech.id
        obj, err = validate(ClockInSchema, data_for_val)
        if err:
            return jsonify(err), 400
        tech_id = obj.technician_id
        if not tech_id:
            return jsonify({'error': 'Technician ID required.'}), 400
        if not obj.job_id:
            return jsonify({'error': 'Job ID required.'}), 400
    finally:
        db.close()

    clock, err = clock_in(tech_id, obj.job_id, phase_id=obj.phase_id, notes=obj.notes)
    if err:
        return jsonify({'error': err}), 400
    return jsonify({'success': True, 'clock_id': clock.id if clock else None})


@time_tracking_bp.route('/api/clock-out', methods=['POST'])
@login_required
def api_clock_out():
    from web.utils.validation import validate, ClockOutSchema
    data = request.get_json()
    db = get_session()
    try:
        tech = _get_tech_for_user(db)
        data_for_val = {**data}
        if not data_for_val.get('technician_id') and tech:
            data_for_val['technician_id'] = tech.id
        obj, err = validate(ClockOutSchema, data_for_val)
        if err:
            return jsonify(err), 400
        tech_id = obj.technician_id
        if not tech_id:
            return jsonify({'error': 'Technician ID required.'}), 400
    finally:
        db.close()

    entry, err = clock_out(tech_id, description=obj.description, entry_type=obj.entry_type)
    if err:
        return jsonify({'error': err}), 400
    return jsonify({'success': True, 'entry_id': entry.id if entry else None,
                    'duration_hours': float(entry.duration_hours) if entry else 0})


@time_tracking_bp.route('/api/approve', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def api_approve():
    from web.utils.validation import validate, ApproveEntriesSchema
    data = request.get_json()
    obj, err = validate(ApproveEntriesSchema, data or {})
    if err:
        return jsonify(err), 400
    count = approve_entries(obj.entry_ids, current_user.id)
    return jsonify({'success': True, 'approved_count': count})


@time_tracking_bp.route('/api/reject', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def api_reject():
    from web.utils.validation import validate, RejectEntriesSchema
    data = request.get_json()
    obj, err = validate(RejectEntriesSchema, data or {})
    if err:
        return jsonify(err), 400
    count = reject_entries(obj.entry_ids, current_user.id, obj.reason)
    return jsonify({'success': True, 'rejected_count': count})


@time_tracking_bp.route('/api/submit', methods=['POST'])
@login_required
def api_submit():
    data = request.get_json()
    ids = data.get('entry_ids', [])
    if not ids:
        return jsonify({'error': 'No entries specified.'}), 400
    db = get_session()
    try:
        tech = _get_tech_for_user(db)
    finally:
        db.close()
    tech_id = tech.id if tech and current_user.role == 'technician' else None
    count = submit_entries(ids, technician_id=tech_id)
    return jsonify({'success': True, 'submitted_count': count})


@time_tracking_bp.route('/api/job-phases/<int:job_id>')
@login_required
def api_job_phases(job_id):
    db = get_session()
    try:
        phases = db.query(JobPhase).filter_by(job_id=job_id).all()
        return jsonify([{'id': p.id, 'name': p.title or f'Phase {p.phase_number}'} for p in phases])
    finally:
        db.close()
