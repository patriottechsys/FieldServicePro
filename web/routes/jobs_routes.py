"""Job routes — job listing, detail, creation, status updates, notes."""

from datetime import datetime, date, timezone, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from models.database import get_session
from models.job import Job, JobNote, JobStatus
from models.invoice import Invoice
from models.client import Client
from web.utils.helpers import get_divisions, get_active_division

jobs_bp = Blueprint('jobs_bp', __name__)


def _get_job_communications(db, job_id):
    try:
        from models.communication import CommunicationLog
        return db.query(CommunicationLog).filter_by(job_id=job_id).order_by(CommunicationLog.communication_date.desc()).all()
    except Exception:
        return []


def _count_job_communications(db, job_id):
    try:
        from models.communication import CommunicationLog
        from sqlalchemy import func as _f
        return db.query(_f.count(CommunicationLog.id)).filter_by(job_id=job_id).scalar() or 0
    except Exception:
        return 0


@jobs_bp.route('/jobs')
@login_required
def jobs_page():
    db = get_session()
    try:
        org_id = current_user.organization_id
        active_div = get_active_division(request)
        status_filter = request.args.get('status', '')

        q = db.query(Job).filter_by(organization_id=org_id)
        if active_div:
            q = q.filter_by(division_id=active_div)
        if status_filter:
            q = q.filter_by(status=status_filter)

        project_filter = request.args.get('project_filter', '')
        if project_filter == 'has_project':
            q = q.filter(Job.project_id.isnot(None))
        elif project_filter == 'standalone':
            q = q.filter(Job.project_id.is_(None))

        from sqlalchemy.orm import joinedload
        jobs = q.options(
            joinedload(Job.client),
            joinedload(Job.division),
            joinedload(Job.technician),
            joinedload(Job.property),
            joinedload(Job.contract),
            joinedload(Job.project),
        ).order_by(Job.created_at.desc()).all()

        job_list = []
        for job in jobs:
            jd = job.to_dict()
            jd['client_name'] = job.client.display_name if job.client else 'Unknown'
            jd['project_number'] = job.project.project_number if job.project else None
            jd['project_id'] = job.project_id
            jd['division_name'] = job.division.name if job.division else ''
            jd['division_color'] = job.division.color if job.division else '#666'
            jd['technician_name'] = job.technician.full_name if job.technician else 'Unassigned'
            jd['property_address'] = job.property.display_address if job.property else ''
            jd['contract_number'] = job.contract.contract_number if job.contract else None
            job_list.append(jd)

        now = datetime.now(timezone.utc)
        thirty_days = timedelta(days=30)

        kpi_q = db.query(Job).filter_by(organization_id=org_id)
        if active_div:
            kpi_q = kpi_q.filter_by(division_id=active_div)

        jobs_late = kpi_q.filter(
            Job.scheduled_date < now,
            Job.status.notin_(['completed', 'cancelled', 'invoiced'])
        ).count()
        jobs_requires_invoicing = kpi_q.filter(Job.status == 'completed').count()
        jobs_action_required = kpi_q.filter(Job.status == 'on_hold').count()
        jobs_unscheduled = kpi_q.filter(
            Job.scheduled_date.is_(None),
            Job.status.notin_(['completed', 'cancelled', 'invoiced'])
        ).count()
        jobs_ending_soon = kpi_q.filter(
            Job.scheduled_date >= now,
            Job.scheduled_date <= now + thirty_days,
            Job.status.notin_(['completed', 'cancelled', 'invoiced'])
        ).count()
        recent_visits_count = kpi_q.filter(
            Job.status == 'completed',
            Job.updated_at >= now - thirty_days
        ).count()
        visits_scheduled_count = kpi_q.filter(
            Job.status.in_(['scheduled', 'in_progress']),
            Job.scheduled_date >= now
        ).count()
        total_jobs_value = sum(j.get('estimated_amount', 0) or 0 for j in job_list)

        return render_template('jobs.html',
            active_page='jobs',
            user=current_user,
            divisions=get_divisions(),
            active_division=active_div,
            jobs=job_list,
            status_filter=status_filter,
            statuses=[s.value for s in JobStatus],
            jobs_late=jobs_late,
            jobs_requires_invoicing=jobs_requires_invoicing,
            jobs_action_required=jobs_action_required,
            jobs_unscheduled=jobs_unscheduled,
            jobs_ending_soon=jobs_ending_soon,
            recent_visits_count=recent_visits_count,
            visits_scheduled_count=visits_scheduled_count,
            total_jobs_value=total_jobs_value,
        )
    finally:
        db.close()


@jobs_bp.route('/api/jobs', methods=['POST'])
@login_required
def create_job():
    from web.utils.validation import validate, JobCreateSchema
    data = request.get_json()
    obj, err = validate(JobCreateSchema, data or {})
    if err:
        return jsonify(err), 400
    db = get_session()
    try:
        max_num = db.query(func.max(Job.id)).filter_by(organization_id=current_user.organization_id).scalar() or 0
        job_number = f"JOB-{max_num + 1:05d}"

        job = Job(
            organization_id=current_user.organization_id,
            division_id=obj.division_id,
            client_id=obj.client_id,
            property_id=obj.property_id,
            job_number=job_number,
            title=obj.title,
            description=obj.description,
            status=obj.status,
            priority=obj.priority,
            job_type=obj.job_type,
            scheduled_date=datetime.fromisoformat(obj.scheduled_date) if obj.scheduled_date else None,
            assigned_technician_id=obj.technician_id,
            estimated_amount=float(obj.estimated_amount),
            created_by_id=current_user.id,
        )
        if obj.is_callback and obj.original_job_id:
            job.is_callback = True
            job.original_job_id = int(obj.original_job_id)
            from models.warranty import Warranty as _Warranty
            orig_warranty = db.query(_Warranty).filter(
                _Warranty.job_id == int(data['original_job_id']),
                _Warranty.status.in_(['active', 'expiring_soon']),
            ).first()
            if orig_warranty:
                job.is_warranty_work = True

        db.add(job)
        db.flush()

        manual_contract_id = obj.contract_id
        if manual_contract_id:
            from models.contract import Contract
            contract = db.query(Contract).filter_by(id=int(manual_contract_id)).first()
        else:
            from web.utils.sla_engine import detect_contract_for_job
            contract = detect_contract_for_job(db, obj.client_id, obj.property_id)
        if contract:
            from web.utils.sla_engine import detect_sla_for_job, apply_sla_to_job
            sla = detect_sla_for_job(contract, obj.priority)
            apply_sla_to_job(job, contract, sla, created_at=job.created_at)

        if job.is_callback and job.original_job_id:
            from models.callback import Callback
            from web.utils.callback_utils import generate_callback_number
            cb = Callback(
                callback_number=generate_callback_number(db),
                original_job_id=job.original_job_id,
                callback_job_id=job.id,
                client_id=job.client_id,
                reason='other',
                description=f'Callback for job {job.original_job_id}',
                severity='minor',
                is_warranty=job.is_warranty_work,
                reported_date=date.today(),
                status='reported',
                created_by=current_user.id,
            )
            db.add(cb)

        db.commit()

        try:
            from web.utils.notification_service import NotificationService
            NotificationService.notify('job_created', job, triggered_by=current_user)
            if job.assigned_technician_id and job.scheduled_date:
                NotificationService.notify('job_scheduled', job, triggered_by=current_user)
        except Exception:
            pass

        return jsonify({'success': True, 'job': job.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()


@jobs_bp.route('/jobs/<int:job_id>')
@login_required
def job_detail(job_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        job = db.query(Job).filter_by(id=job_id, organization_id=org_id).first()
        if not job:
            flash('Job not found', 'error')
            return redirect(url_for('jobs_bp.jobs_page'))

        client = job.client
        prop = job.property
        tech = job.technician
        division = job.division
        job_notes = db.query(JobNote).filter_by(job_id=job.id).order_by(JobNote.created_at.desc()).all()
        job_invoices = db.query(Invoice).filter_by(job_id=job.id, organization_id=org_id).order_by(Invoice.created_at.desc()).all()

        total_invoiced = sum(inv.total or 0 for inv in job_invoices)
        total_paid = sum(inv.amount_paid or 0 for inv in job_invoices)
        total_balance = sum(inv.balance_due or 0 for inv in job_invoices)

        total_price = job.estimated_amount or 0
        profit = total_price
        profit_pct = 100 if total_price > 0 else 0

        show_sla_details = True
        if current_user.role == 'technician':
            tech_id = getattr(current_user, 'technician_id', None)
            if not tech_id or job.assigned_technician_id != tech_id:
                show_sla_details = False

        try:
            contract_val = float(job.current_contract_value or 0)
        except (TypeError, ValueError):
            contract_val = 0
        financial_summary = {
            'invoiced_total': total_invoiced,
            'remaining': contract_val - total_invoiced,
        }

        activity_log = []
        for phase in job.phases:
            activity_log.append({
                'timestamp': phase.updated_at,
                'title': f'Phase {phase.phase_number} -- {phase.status_label}',
                'description': phase.completion_notes or phase.title,
                'icon': 'layers', 'type_class': 'primary',
                'actor': phase.assigned_technician.full_name if phase.assigned_technician else None,
            })
        for co in job.change_orders:
            activity_log.append({
                'timestamp': co.created_at,
                'title': f'Change Order {co.change_order_number}',
                'description': f'{co.title} -- {co.status_label}',
                'icon': 'file-diff', 'type_class': 'warning',
                'actor': co.created_by.full_name if co.created_by else None,
            })
        activity_log.append({
            'timestamp': job.created_at,
            'title': 'Job Created', 'description': job.title,
            'icon': 'plus-circle', 'type_class': 'success', 'actor': None,
        })
        activity_log = sorted(
            [e for e in activity_log if e['timestamp']],
            key=lambda x: x['timestamp'], reverse=True
        )

        active_tab = request.args.get('tab', 'overview')
        can_edit_phases = current_user.role in ('owner', 'admin', 'dispatcher')

        from web.utils.compliance_checks import get_job_compliance_status
        from models.permit import Permit
        from models.checklist import CompletedChecklist
        from models.lien_waiver import LienWaiver
        compliance_status = get_job_compliance_status(db, job.id)
        job_permits = db.query(Permit).filter_by(job_id=job.id).order_by(Permit.created_at.desc()).all()
        job_checklists = db.query(CompletedChecklist).filter_by(job_id=job.id).order_by(
            CompletedChecklist.completed_at.desc()).all()
        job_lien_waivers = db.query(LienWaiver).filter_by(job_id=job.id).order_by(
            LienWaiver.created_at.desc()).all()
        from web.utils.file_utils import get_entity_documents
        job_documents = get_entity_documents(db, 'job', job.id,
                                              include_confidential=current_user.role in ('owner', 'admin'))

        from models.job_material import JobMaterial
        from models.inventory import InventoryLocation
        from web.utils.materials_utils import get_job_material_summary
        job_materials = db.query(JobMaterial).filter_by(job_id=job.id).order_by(JobMaterial.added_at.desc()).all()
        material_summary = get_job_material_summary(db, job.id)
        inv_locations = db.query(InventoryLocation).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(InventoryLocation.name).all()
        job_phases = job.phases if job.is_multi_phase else []

        from web.utils.job_costing import get_job_cost_breakdown
        cost_breakdown = get_job_cost_breakdown(db, job)

        return render_template('job_detail.html',
            active_page='jobs', user=current_user, divisions=get_divisions(),
            job=job.to_dict(), job_obj=job, show_sla_details=show_sla_details,
            client=client.to_dict() if client else {},
            client_name=client.display_name if client else 'Unknown',
            property=prop.to_dict() if prop else {},
            property_address=prop.display_address if prop else '',
            technician=tech.to_dict() if tech else {},
            technician_name=tech.full_name if tech else 'Unassigned',
            division=division,
            division_name=division.name if division else '',
            division_color=division.color if division else '#666',
            quote=(job.quote.to_dict() if job.quote else None) if hasattr(job, 'quote') else None,
            job_notes=[n.to_dict() for n in job_notes],
            job_invoices=[inv.to_dict() for inv in job_invoices],
            total_invoiced=total_invoiced, total_paid=total_paid, total_balance=total_balance,
            total_price=total_price, line_item_cost=0, labour_cost=0, expenses=0,
            profit=profit, profit_pct=profit_pct,
            financial_summary=financial_summary,
            activity_log=activity_log,
            active_tab=active_tab,
            can_edit_phases=can_edit_phases,
            compliance_status=compliance_status,
            job_permits=job_permits,
            job_checklists=job_checklists,
            job_lien_waivers=job_lien_waivers,
            job_documents=job_documents,
            job_materials=job_materials,
            material_summary=material_summary,
            inv_locations=inv_locations,
            job_phases=job_phases,
            can_admin=current_user.role in ('owner', 'admin'),
            cost_breakdown=cost_breakdown,
            job_communications=_get_job_communications(db, job.id),
            job_comm_count=_count_job_communications(db, job.id),
        )
    finally:
        db.close()


@jobs_bp.route('/jobs/<int:job_id>/pm-notes', methods=['POST'])
@login_required
def update_pm_notes(job_id):
    if current_user.role not in ('owner', 'admin', 'dispatcher'):
        abort(403)
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, organization_id=current_user.organization_id).first()
        if not job:
            abort(404)
        job.project_manager_notes = request.form.get('project_manager_notes', '')
        db.commit()
        flash('PM notes saved.', 'success')
    finally:
        db.close()
    return redirect(url_for('jobs_bp.job_detail', job_id=job_id))


@jobs_bp.route('/api/jobs/<int:job_id>/notes', methods=['POST'])
@login_required
def add_job_note(job_id):
    data = request.get_json()
    db = get_session()
    try:
        note = JobNote(
            job_id=job_id,
            user_id=current_user.id,
            content=data['content'],
        )
        db.add(note)
        db.commit()
        return jsonify({'success': True, 'note': note.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()


@jobs_bp.route('/api/jobs/<int:job_id>/status', methods=['PUT'])
@login_required
def update_job_status(job_id):
    data = request.get_json()
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, organization_id=current_user.organization_id).first()
        if not job:
            return jsonify({'success': False, 'error': 'Job not found'}), 404
        new_status = data['status']
        override = data.get('compliance_override', False)

        if not override:
            from web.utils.compliance_checks import check_job_can_start, check_job_can_complete
            warnings = []
            if new_status == 'in_progress':
                ok, warnings = check_job_can_start(db, job.id)
            elif new_status == 'completed':
                ok, warnings = check_job_can_complete(db, job.id)

            if warnings:
                can_override = current_user.role in ('owner', 'admin')
                return jsonify({
                    'success': False,
                    'compliance_warnings': warnings,
                    'can_override': can_override,
                    'error': 'Compliance warnings must be resolved or overridden.',
                }), 409

        if job.sla_id:
            from web.utils.sla_engine import handle_job_status_change
            handle_job_status_change(job, new_status)
        else:
            job.status = new_status
        if new_status == 'completed':
            job.completed_at = datetime.now(timezone.utc)
        if new_status == 'in_progress' and not job.started_at:
            job.started_at = datetime.now(timezone.utc)
        db.commit()

        try:
            from web.utils.notification_service import NotificationService
            NotificationService.notify('job_status_changed', job, triggered_by=current_user,
                                       extra_context={'status': new_status})
            if new_status == 'completed':
                NotificationService.notify('job_completed', job, triggered_by=current_user)
            elif new_status == 'on_hold':
                NotificationService.notify('job_on_hold', job, triggered_by=current_user)
        except Exception:
            pass

        prompt_warranty = False
        if new_status == 'completed':
            from models.warranty import Warranty
            has_warranty = db.query(Warranty).filter_by(job_id=job_id).first()
            if not has_warranty:
                prompt_warranty = True

        return jsonify({'success': True, 'job': job.to_dict(), 'prompt_warranty': prompt_warranty})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()
