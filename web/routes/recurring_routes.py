"""Recurring schedule & preventive maintenance routes."""
from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import desc, or_

from models.database import get_session
from models.recurring_schedule import (
    RecurringSchedule, RecurringJobLog,
    FREQUENCY_CHOICES, DAY_OF_WEEK_CHOICES, SCHEDULE_STATUS_CHOICES,
)
from models.client import Client
from models.division import Division
from models.technician import Technician
from models.checklist import ChecklistTemplate
from models.contract import Contract
from web.auth import role_required
from web.utils.recurring_engine import (
    generate_schedule_number, generate_for_schedule, run_generation_pass,
    get_dashboard_summary, get_due_schedules, sync_from_contract_line_items,
    preview_upcoming_dates,
)

recurring_bp = Blueprint('recurring', __name__, url_prefix='/recurring')


def _get_divisions():
    db = get_session()
    try:
        divs = db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
        return [d.to_dict() for d in divs]
    finally:
        db.close()


def _can_admin():
    return current_user.role in ('owner', 'admin')


# ── Schedule List ─────────────────────────────────────────────────────────────

@recurring_bp.route('/')
@login_required
def schedule_list():
    db = get_session()
    try:
        org_id = current_user.organization_id
        status_filter = request.args.get('status', '')
        search = request.args.get('search', '').strip()

        query = db.query(RecurringSchedule).filter_by(organization_id=org_id)
        if status_filter:
            query = query.filter(RecurringSchedule.status == status_filter)
        else:
            query = query.filter(RecurringSchedule.status.in_(['active', 'paused']))
        if search:
            s = f'%{search}%'
            query = query.filter(or_(
                RecurringSchedule.title.ilike(s),
                RecurringSchedule.schedule_number.ilike(s),
            ))

        schedules = query.order_by(RecurringSchedule.next_due_date).all()
        summary = get_dashboard_summary(db, org_id)

        return render_template('recurring/schedule_list.html',
            active_page='recurring', user=current_user, divisions=_get_divisions(),
            can_admin=_can_admin(),
            schedules=schedules, summary=summary,
            statuses=SCHEDULE_STATUS_CHOICES,
            status_filter=status_filter, search=search,
        )
    finally:
        db.close()


# ── Schedule Detail ───────────────────────────────────────────────────────────

@recurring_bp.route('/<int:schedule_id>')
@login_required
def schedule_detail(schedule_id):
    db = get_session()
    try:
        schedule = db.query(RecurringSchedule).filter_by(
            id=schedule_id, organization_id=current_user.organization_id
        ).first()
        if not schedule:
            flash('Schedule not found.', 'error')
            return redirect(url_for('recurring.schedule_list'))

        logs = db.query(RecurringJobLog).filter_by(
            schedule_id=schedule_id
        ).order_by(desc(RecurringJobLog.generated_at)).limit(20).all()

        upcoming_dates = preview_upcoming_dates(schedule, count=6)

        return render_template('recurring/schedule_detail.html',
            active_page='recurring', user=current_user, divisions=_get_divisions(),
            can_admin=_can_admin(), schedule=schedule, logs=logs,
            upcoming_dates=upcoming_dates,
        )
    finally:
        db.close()


# ── New Schedule ──────────────────────────────────────────────────────────────

@recurring_bp.route('/new', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'owner')
def new_schedule():
    db = get_session()
    try:
        org_id = current_user.organization_id

        if request.method == 'POST':
            import json as _json
            start_date = date.fromisoformat(request.form.get('start_date'))
            next_due = date.fromisoformat(request.form.get('next_due_date') or request.form.get('start_date'))
            seasonal_raw = request.form.getlist('seasonal_months')
            seasonal_json = _json.dumps([int(m) for m in seasonal_raw]) if seasonal_raw else None

            schedule = RecurringSchedule(
                organization_id=org_id,
                schedule_number=generate_schedule_number(db),
                title=request.form.get('title', '').strip(),
                description=request.form.get('description', '').strip() or None,
                client_id=int(request.form.get('client_id')),
                property_id=int(request.form.get('property_id')) if request.form.get('property_id') else None,
                contract_id=int(request.form.get('contract_id')) if request.form.get('contract_id') else None,
                contract_line_item_id=int(request.form.get('contract_line_item_id')) if request.form.get('contract_line_item_id') else None,
                division_id=int(request.form.get('division_id')) if request.form.get('division_id') else None,
                job_type=request.form.get('job_type', 'maintenance'),
                trade=request.form.get('trade') or None,
                default_description=request.form.get('default_description', '').strip() or None,
                default_priority=request.form.get('default_priority', 'normal'),
                estimated_duration_hours=float(request.form.get('estimated_duration_hours') or 0) or None,
                estimated_amount=float(request.form.get('estimated_amount') or 0) or None,
                default_technician_id=int(request.form.get('default_technician_id')) if request.form.get('default_technician_id') else None,
                checklist_template_id=int(request.form.get('checklist_template_id')) if request.form.get('checklist_template_id') else None,
                frequency=request.form.get('frequency', 'annual'),
                custom_interval_days=int(request.form.get('custom_interval_days') or 0) or None,
                requires_parts=request.form.get('requires_parts', '').strip() or None,
                preferred_day_of_week=request.form.get('preferred_day_of_week') or None,
                preferred_time=request.form.get('preferred_time') or None,
                seasonal_months=seasonal_json,
                start_date=start_date,
                end_date=date.fromisoformat(request.form.get('end_date')) if request.form.get('end_date') else None,
                next_due_date=next_due,
                auto_generate='auto_generate' in request.form,
                auto_assign='auto_assign' in request.form,
                auto_schedule='auto_schedule' in request.form,
                advance_generation_days=int(request.form.get('advance_generation_days') or 14),
                status='active',
                created_by=current_user.id,
            )
            db.add(schedule)
            db.commit()
            flash(f'Schedule {schedule.schedule_number} created.', 'success')
            return redirect(url_for('recurring.schedule_detail', schedule_id=schedule.id))

        clients = db.query(Client).filter_by(organization_id=org_id).order_by(Client.company_name).all()
        technicians = db.query(Technician).filter_by(is_active=True).order_by(Technician.first_name).all()
        divisions = db.query(Division).filter_by(organization_id=org_id, is_active=True).order_by(Division.sort_order).all()
        contracts = db.query(Contract).filter_by(organization_id=org_id, status='active').all()
        checklists = db.query(ChecklistTemplate).filter_by(is_active=True).all()

        return render_template('recurring/schedule_form.html',
            active_page='recurring', user=current_user, divisions=_get_divisions(),
            schedule=None, title='New Recurring Schedule',
            clients=clients, technicians=technicians, all_divisions=divisions,
            contracts=contracts, checklists=checklists,
            frequencies=FREQUENCY_CHOICES, days_of_week=DAY_OF_WEEK_CHOICES,
        )
    finally:
        db.close()


# ── Edit Schedule ─────────────────────────────────────────────────────────────

@recurring_bp.route('/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'owner')
def edit_schedule(schedule_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        schedule = db.query(RecurringSchedule).filter_by(id=schedule_id, organization_id=org_id).first()
        if not schedule:
            flash('Schedule not found.', 'error')
            return redirect(url_for('recurring.schedule_list'))

        if request.method == 'POST':
            import json as _json
            seasonal_raw = request.form.getlist('seasonal_months')
            schedule.title = request.form.get('title', '').strip()
            schedule.description = request.form.get('description', '').strip() or None
            schedule.client_id = int(request.form.get('client_id'))
            schedule.property_id = int(request.form.get('property_id')) if request.form.get('property_id') else None
            schedule.contract_id = int(request.form.get('contract_id')) if request.form.get('contract_id') else None
            schedule.contract_line_item_id = int(request.form.get('contract_line_item_id')) if request.form.get('contract_line_item_id') else None
            schedule.division_id = int(request.form.get('division_id')) if request.form.get('division_id') else None
            schedule.job_type = request.form.get('job_type', schedule.job_type)
            schedule.trade = request.form.get('trade') or None
            schedule.default_description = request.form.get('default_description', '').strip() or None
            schedule.default_priority = request.form.get('default_priority', 'normal')
            schedule.estimated_duration_hours = float(request.form.get('estimated_duration_hours') or 0) or None
            schedule.estimated_amount = float(request.form.get('estimated_amount') or 0) or None
            schedule.default_technician_id = int(request.form.get('default_technician_id')) if request.form.get('default_technician_id') else None
            schedule.checklist_template_id = int(request.form.get('checklist_template_id')) if request.form.get('checklist_template_id') else None
            schedule.frequency = request.form.get('frequency', schedule.frequency)
            schedule.custom_interval_days = int(request.form.get('custom_interval_days') or 0) or None
            schedule.requires_parts = request.form.get('requires_parts', '').strip() or None
            schedule.preferred_day_of_week = request.form.get('preferred_day_of_week') or None
            schedule.preferred_time = request.form.get('preferred_time') or None
            schedule.seasonal_months = _json.dumps([int(m) for m in seasonal_raw]) if seasonal_raw else None
            if request.form.get('next_due_date'):
                schedule.next_due_date = date.fromisoformat(request.form.get('next_due_date'))
            if request.form.get('end_date'):
                schedule.end_date = date.fromisoformat(request.form.get('end_date'))
            schedule.auto_generate = 'auto_generate' in request.form
            schedule.auto_assign = 'auto_assign' in request.form
            schedule.auto_schedule = 'auto_schedule' in request.form
            schedule.advance_generation_days = int(request.form.get('advance_generation_days') or 14)
            db.commit()
            flash('Schedule updated.', 'success')
            return redirect(url_for('recurring.schedule_detail', schedule_id=schedule.id))

        clients = db.query(Client).filter_by(organization_id=org_id).order_by(Client.company_name).all()
        technicians = db.query(Technician).filter_by(is_active=True).order_by(Technician.first_name).all()
        divisions = db.query(Division).filter_by(organization_id=org_id, is_active=True).order_by(Division.sort_order).all()
        contracts = db.query(Contract).filter_by(organization_id=org_id, status='active').all()
        checklists = db.query(ChecklistTemplate).filter_by(is_active=True).all()

        return render_template('recurring/schedule_form.html',
            active_page='recurring', user=current_user, divisions=_get_divisions(),
            schedule=schedule, title=f'Edit {schedule.schedule_number}',
            clients=clients, technicians=technicians, all_divisions=divisions,
            contracts=contracts, checklists=checklists,
            frequencies=FREQUENCY_CHOICES, days_of_week=DAY_OF_WEEK_CHOICES,
        )
    finally:
        db.close()


# ── Status Actions ────────────────────────────────────────────────────────────

@recurring_bp.route('/<int:schedule_id>/pause', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def pause_schedule(schedule_id):
    db = get_session()
    try:
        schedule = db.query(RecurringSchedule).filter_by(
            id=schedule_id, organization_id=current_user.organization_id
        ).first()
        if schedule and schedule.status == 'active':
            schedule.status = 'paused'
            schedule.pause_reason = request.form.get('pause_reason', '')
            pause_until = request.form.get('pause_until')
            schedule.pause_until = date.fromisoformat(pause_until) if pause_until else None
            db.commit()
            flash('Schedule paused.', 'warning')
    finally:
        db.close()
    return redirect(url_for('recurring.schedule_detail', schedule_id=schedule_id))


@recurring_bp.route('/<int:schedule_id>/resume', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def resume_schedule(schedule_id):
    db = get_session()
    try:
        schedule = db.query(RecurringSchedule).filter_by(
            id=schedule_id, organization_id=current_user.organization_id
        ).first()
        if schedule and schedule.status == 'paused':
            schedule.status = 'active'
            schedule.pause_reason = None
            schedule.pause_until = None
            db.commit()
            flash('Schedule resumed.', 'success')
    finally:
        db.close()
    return redirect(url_for('recurring.schedule_detail', schedule_id=schedule_id))


@recurring_bp.route('/<int:schedule_id>/cancel', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def cancel_schedule(schedule_id):
    db = get_session()
    try:
        schedule = db.query(RecurringSchedule).filter_by(
            id=schedule_id, organization_id=current_user.organization_id
        ).first()
        if schedule and schedule.status not in ('completed', 'cancelled'):
            schedule.status = 'cancelled'
            db.commit()
            flash('Schedule cancelled.', 'warning')
    finally:
        db.close()
    return redirect(url_for('recurring.schedule_detail', schedule_id=schedule_id))


# ── Generate Now ──────────────────────────────────────────────────────────────

@recurring_bp.route('/<int:schedule_id>/generate', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def generate_now(schedule_id):
    db = get_session()
    try:
        schedule = db.query(RecurringSchedule).filter_by(
            id=schedule_id, organization_id=current_user.organization_id
        ).first()
        if not schedule:
            flash('Schedule not found.', 'error')
            return redirect(url_for('recurring.schedule_list'))

        force = 'force' in request.form
        job = generate_for_schedule(db, schedule, user_id=current_user.id, method='manual', force=force)
        if job:
            db.commit()
            flash(f'Job {job.job_number} generated.', 'success')
        else:
            flash('Job already generated for this cycle.', 'info')
    except Exception as e:
        db.rollback()
        flash(f'Error: {e}', 'error')
    finally:
        db.close()
    return redirect(url_for('recurring.schedule_detail', schedule_id=schedule_id))


# ── Run All (bulk generation) ────────────────────────────────────────────────

@recurring_bp.route('/run-all', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def run_all():
    db = get_session()
    try:
        result = run_generation_pass(db, org_id=current_user.organization_id, user_id=current_user.id, method='manual')
        if result.total_created:
            flash(f'Generated {result.total_created} jobs from {result.schedules_processed} schedules.', 'success')
        else:
            flash('No jobs needed generation at this time.', 'info')
        if result.errors:
            for err in result.errors[:3]:
                flash(f"Error: {err}", 'warning')
    except Exception as e:
        flash(f'Error: {e}', 'error')
    finally:
        db.close()
    return redirect(url_for('recurring.schedule_list'))


# ── API: Dashboard Summary ────────────────────────────────────────────────────

@recurring_bp.route('/api/summary')
@login_required
def api_summary():
    db = get_session()
    try:
        summary = get_dashboard_summary(db, current_user.organization_id)
        return jsonify(summary)
    finally:
        db.close()


# ── API: Contract line items for a contract ──────────────────────────────────

@recurring_bp.route('/api/contract-line-items/<int:contract_id>')
@login_required
def api_contract_line_items(contract_id):
    db = get_session()
    try:
        from models.contract import ContractLineItem
        items = db.query(ContractLineItem).filter_by(contract_id=contract_id).all()
        return jsonify([{
            'id': li.id,
            'service_type': li.service_type,
            'description': li.description,
            'frequency': li.frequency.value if hasattr(li.frequency, 'value') else str(li.frequency),
            'next_scheduled_date': li.next_scheduled_date.isoformat() if li.next_scheduled_date else None,
            'unit_price': float(li.unit_price) if li.unit_price else None,
        } for li in items])
    finally:
        db.close()


# ── Contract Sync ─────────────────────────────────────────────────────────────

@recurring_bp.route('/sync-contract/<int:contract_id>', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def sync_contract(contract_id):
    db = get_session()
    try:
        result = sync_from_contract_line_items(db, contract_id, current_user.id)
        if result.get('error'):
            flash(result['error'], 'error')
        else:
            flash(f"Sync complete: {len(result['created'])} schedule(s) created, {len(result['skipped'])} skipped.", 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')
    finally:
        db.close()
    return redirect(url_for('recurring.schedule_list'))
