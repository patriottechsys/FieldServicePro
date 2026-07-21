"""Job Phase CRUD routes."""

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from models.database import get_session
from models.job import Job
from models.job_phase import JobPhase
from models.technician import Technician
from models.division import Division
from web.utils.phase_utils import (
    create_phase, update_phase, delete_phase,
    reorder_phases, sync_job_cost_from_phases,
)
from web.auth import role_required

phases_bp = Blueprint('phases', __name__, url_prefix='/jobs')


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


def _tpl_vars(**extra):
    base = dict(active_page='jobs', user=current_user, divisions=_get_divisions())
    base.update(extra)
    return base


# -- Create Phase --

@phases_bp.route('/<int:job_id>/phases/new', methods=['GET', 'POST'])
@login_required
@role_required('owner', 'admin', 'dispatcher')
def new_phase(job_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        job = db.query(Job).filter_by(id=job_id, organization_id=org_id).first()
        if not job:
            abort(404)

        technicians = db.query(Technician).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Technician.first_name).all()

        if request.method == 'POST':
            try:
                phase = create_phase(db, job, request.form)
                sync_job_cost_from_phases(db, job)
                db.commit()
                flash(f"Phase '{phase.title}' created.", 'success')
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'phase': phase.to_dict()})
                return redirect(url_for('jobs_bp.job_detail', job_id=job_id))
            except Exception as e:
                db.rollback()
                flash(f'Error creating phase: {str(e)}', 'danger')
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'error': str(e)}), 400

        return render_template('phases/phase_form_modal.html',
                               **_tpl_vars(
                                   job=job, phase=None, technicians=technicians,
                                   form_action=url_for('phases.new_phase', job_id=job_id),
                                   modal_title='Add New Phase',
                               ))
    finally:
        db.close()


# -- Edit Phase --

@phases_bp.route('/<int:job_id>/phases/<int:phase_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_phase(job_id, phase_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        job = db.query(Job).filter_by(id=job_id, organization_id=org_id).first()
        if not job:
            abort(404)
        phase = db.query(JobPhase).filter_by(id=phase_id, job_id=job_id).first()
        if not phase:
            abort(404)

        # Technicians can only edit their own assigned phases
        if current_user.role == 'technician':
            tech = db.query(Technician).filter_by(user_id=current_user.id).first()
            if not tech or phase.assigned_technician_id != tech.id:
                abort(403)
        elif current_user.role == 'viewer':
            abort(403)

        technicians = db.query(Technician).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Technician.first_name).all()

        if request.method == 'POST':
            try:
                update_phase(db, phase, request.form)
                sync_job_cost_from_phases(db, job)
                db.commit()
                flash(f"Phase '{phase.title}' updated.", 'success')
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'phase': phase.to_dict()})
                return redirect(url_for('jobs_bp.job_detail', job_id=job_id))
            except Exception as e:
                db.rollback()
                flash(f'Error updating phase: {str(e)}', 'danger')

        return render_template('phases/phase_form_modal.html',
                               **_tpl_vars(
                                   job=job, phase=phase, technicians=technicians,
                                   form_action=url_for('phases.edit_phase', job_id=job_id, phase_id=phase_id),
                                   modal_title=f'Edit Phase {phase.phase_number}: {phase.title}',
                               ))
    finally:
        db.close()


# -- Delete Phase --

@phases_bp.route('/<int:job_id>/phases/<int:phase_id>/delete', methods=['POST'])
@login_required
@role_required('owner', 'admin', 'dispatcher')
def delete_phase_route(job_id, phase_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        job = db.query(Job).filter_by(id=job_id, organization_id=org_id).first()
        if not job:
            abort(404)
        phase = db.query(JobPhase).filter_by(id=phase_id, job_id=job_id).first()
        if not phase:
            abort(404)

        phase_title = phase.title
        delete_phase(db, phase)
        sync_job_cost_from_phases(db, job)

        # Reset multi-phase if no phases remain
        remaining = db.query(JobPhase).filter_by(job_id=job_id).count()
        if remaining == 0:
            job.is_multi_phase = False

        db.commit()
        flash(f"Phase '{phase_title}' removed.", 'success')

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True})
        return redirect(url_for('jobs_bp.job_detail', job_id=job_id))
    except Exception as e:
        db.rollback()
        flash(f'Error deleting phase: {str(e)}', 'danger')
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()


# -- Reorder Phases (AJAX) --

@phases_bp.route('/<int:job_id>/phases/reorder', methods=['POST'])
@login_required
@role_required('owner', 'admin', 'dispatcher')
def reorder_phases_route(job_id):
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, organization_id=current_user.organization_id).first()
        if not job:
            abort(404)

        data = request.get_json()
        phase_ids = data.get('phase_ids', [])
        if not phase_ids:
            return jsonify({'success': False, 'error': 'No phase IDs provided'}), 400

        reorder_phases(db, job_id, phase_ids)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


# -- Convert Job to Multi-Phase --

@phases_bp.route('/<int:job_id>/convert-to-multiphase', methods=['POST'])
@login_required
@role_required('owner', 'admin', 'dispatcher')
def convert_to_multiphase(job_id):
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, organization_id=current_user.organization_id).first()
        if not job:
            abort(404)

        if job.is_multi_phase:
            flash('Job is already multi-phase.', 'info')
            return redirect(url_for('jobs_bp.job_detail', job_id=job_id))

        job.is_multi_phase = True
        if job.original_estimated_cost is None:
            job.original_estimated_cost = job.estimated_amount

        db.commit()
        flash('Job converted to multi-phase. Add phases below.', 'success')
        return redirect(url_for('jobs_bp.job_detail', job_id=job_id))
    finally:
        db.close()


# -- Phase Status Update (AJAX) --

@phases_bp.route('/<int:job_id>/phases/<int:phase_id>/status', methods=['POST'])
@login_required
def update_phase_status(job_id, phase_id):
    """AJAX: POST {"status": "in_progress", "note": "optional"}"""
    from web.utils.phase_status import (
        transition_phase_status, sync_job_status_from_phases, get_phase_status_summary
    )
    db = get_session()
    try:
        org_id = current_user.organization_id
        job = db.query(Job).filter_by(id=job_id, organization_id=org_id).first()
        if not job:
            return jsonify({'success': False, 'error': 'Job not found'}), 404
        phase = db.query(JobPhase).filter_by(id=phase_id, job_id=job_id).first()
        if not phase:
            return jsonify({'success': False, 'error': 'Phase not found'}), 404

        # Technicians can only update their own phases
        if current_user.role == 'technician':
            tech = db.query(Technician).filter_by(user_id=current_user.id).first()
            if not tech or phase.assigned_technician_id != tech.id:
                return jsonify({'success': False, 'error': 'Not your phase'}), 403
        elif current_user.role == 'viewer':
            return jsonify({'success': False, 'error': 'Read-only access'}), 403

        data = request.get_json() or {}
        new_status = data.get('status')
        if not new_status:
            return jsonify({'success': False, 'error': 'Status required'}), 400

        success, message = transition_phase_status(phase, new_status, actor_note=data.get('note'))

        if success:
            sync_job_status_from_phases(job)
            db.commit()
            summary = get_phase_status_summary(job)
            return jsonify({
                'success': True, 'message': message,
                'phase': phase.to_dict(), 'job_summary': summary,
            })
        else:
            return jsonify({'success': False, 'error': message}), 422
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


# -- Inspection Recording --

@phases_bp.route('/<int:job_id>/phases/<int:phase_id>/inspection', methods=['POST'])
@login_required
@role_required('owner', 'admin', 'dispatcher')
def record_phase_inspection(job_id, phase_id):
    """Record inspection pass/fail on a phase."""
    from web.utils.phase_status import record_inspection
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, organization_id=current_user.organization_id).first()
        if not job:
            return jsonify({'success': False, 'error': 'Job not found'}), 404
        phase = db.query(JobPhase).filter_by(id=phase_id, job_id=job_id).first()
        if not phase:
            return jsonify({'success': False, 'error': 'Phase not found'}), 404

        data = request.get_json() or request.form
        passed = str(data.get('passed', 'false')).lower() in ('true', '1', 'yes')
        notes = data.get('notes')

        success, message = record_inspection(phase, passed=passed, inspector_notes=notes)
        if success:
            db.commit()
            return jsonify({'success': True, 'message': message, 'phase': phase.to_dict()})
        return jsonify({'success': False, 'error': message}), 422
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


# -- Phase Summary (AJAX) --

@phases_bp.route('/<int:job_id>/phases/summary', methods=['GET'])
@login_required
def phases_summary(job_id):
    """Return JSON summary of phase progress."""
    from web.utils.phase_status import get_phase_status_summary
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, organization_id=current_user.organization_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        return jsonify(get_phase_status_summary(job))
    finally:
        db.close()
