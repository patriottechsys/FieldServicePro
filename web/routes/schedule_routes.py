"""API endpoints for the scheduling/calendar system."""
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user
from models.database import get_session
from models.job import Job
from models.technician import Technician
from models.division import Division

schedule_api_bp = Blueprint('schedule_api', __name__)


@schedule_api_bp.route('/api/schedule/events')
@login_required
def schedule_events():
    """Return scheduled jobs as FullCalendar-compatible JSON."""
    db = get_session()
    try:
        org_id = current_user.organization_id
        start = request.args.get('start', '')
        end = request.args.get('end', '')
        tech_id = request.args.get('technician_id', type=int)
        division_id = request.args.get('division', type=int)

        q = db.query(Job).filter(
            Job.organization_id == org_id,
            Job.scheduled_date != None,
            Job.status.in_(['scheduled', 'in_progress', 'draft'])
        )

        if start:
            try:
                q = q.filter(Job.scheduled_date >= datetime.fromisoformat(start.replace('Z', '')))
            except ValueError:
                pass
        if end:
            try:
                q = q.filter(Job.scheduled_date <= datetime.fromisoformat(end.replace('Z', '')))
            except ValueError:
                pass
        if tech_id:
            q = q.filter(Job.assigned_technician_id == tech_id)
        if division_id:
            q = q.filter(Job.division_id == division_id)

        jobs = q.order_by(Job.scheduled_date).all()

        events = []
        for j in jobs:
            end_time = j.scheduled_end or (j.scheduled_date + timedelta(hours=2)) if j.scheduled_date else None
            div_color = j.division.color if j.division else '#2563eb'

            events.append({
                'id': f'job-{j.id}',
                'title': f'{j.job_number} — {j.title[:30]}',
                'start': j.scheduled_date.isoformat() if j.scheduled_date else None,
                'end': end_time.isoformat() if end_time else None,
                'color': div_color,
                'extendedProps': {
                    'jobId': j.id,
                    'jobNumber': j.job_number,
                    'jobTitle': j.title,
                    'clientName': j.client.display_name if j.client else '',
                    'technicianName': j.technician.full_name if j.technician else 'Unassigned',
                    'technicianId': j.assigned_technician_id,
                    'status': j.status,
                    'priority': j.priority or 'normal',
                    'division': j.division.name if j.division else '',
                    'divisionCode': j.division.code if j.division and hasattr(j.division, 'code') else '',
                    'jobType': j.job_type or '',
                    'propertyAddress': j.property.display_address if j.property else '',
                    'estimatedAmount': j.estimated_amount or 0,
                },
            })

        return jsonify(events)
    finally:
        db.close()


@schedule_api_bp.route('/api/schedule/assign', methods=['POST'])
@login_required
def schedule_assign():
    """Assign a technician to a job at a specific time."""
    if current_user.role not in ('owner', 'admin', 'dispatcher'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403

    from web.utils.validation import validate, ScheduleCreateSchema
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data'}), 400

    obj, err = validate(ScheduleCreateSchema, data)
    if err:
        return jsonify(err), 400

    job_id = obj.job_id
    tech_id = obj.technician_id
    start_time = obj.start_time
    end_time = obj.end_time

    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, organization_id=current_user.organization_id).first()
        if not job:
            return jsonify({'success': False, 'error': 'Job not found'}), 404

        try:
            job.scheduled_date = datetime.fromisoformat(start_time.replace('Z', ''))
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid start_time format'}), 400

        if end_time:
            try:
                job.scheduled_end = datetime.fromisoformat(end_time.replace('Z', ''))
            except ValueError:
                pass

        if tech_id:
            tech = db.query(Technician).filter_by(id=tech_id, organization_id=current_user.organization_id).first()
            if tech:
                job.assigned_technician_id = tech.id

        if job.status == 'draft':
            job.status = 'scheduled'

        db.commit()

        try:
            from web.utils.notification_service import NotificationService
            NotificationService.notify('job_scheduled', job, triggered_by=current_user)
        except Exception:
            pass

        div_color = job.division.color if job.division else '#2563eb'
        event_end = job.scheduled_end or (job.scheduled_date + timedelta(hours=2))

        return jsonify({
            'success': True,
            'event': {
                'id': f'job-{job.id}',
                'title': f'{job.job_number} — {job.title[:30]}',
                'start': job.scheduled_date.isoformat(),
                'end': event_end.isoformat(),
                'color': div_color,
                'extendedProps': {
                    'jobId': job.id,
                    'jobNumber': job.job_number,
                    'jobTitle': job.title,
                    'clientName': job.client.display_name if job.client else '',
                    'technicianName': job.technician.full_name if job.technician else 'Unassigned',
                    'technicianId': job.assigned_technician_id,
                    'status': job.status,
                    'priority': job.priority or 'normal',
                    'division': job.division.name if job.division else '',
                },
            },
        })
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


@schedule_api_bp.route('/api/schedule/reschedule', methods=['POST'])
@login_required
def schedule_reschedule():
    """Move an existing event to a new time."""
    if current_user.role not in ('owner', 'admin', 'dispatcher'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403

    from web.utils.validation import validate, ScheduleRescheduleSchema
    data = request.get_json()
    obj, err = validate(ScheduleRescheduleSchema, data or {})
    if err:
        return jsonify(err), 400

    job_id = obj.job_id
    new_start = obj.new_start
    new_end = obj.new_end

    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, organization_id=current_user.organization_id).first()
        if not job:
            return jsonify({'success': False, 'error': 'Job not found'}), 404

        original_date = job.scheduled_date
        job.scheduled_date = datetime.fromisoformat(new_start.replace('Z', ''))
        if new_end:
            job.scheduled_end = datetime.fromisoformat(new_end.replace('Z', ''))

        db.commit()

        if original_date and original_date != job.scheduled_date:
            try:
                from web.utils.notification_service import NotificationService
                NotificationService.notify('schedule_changed', job, triggered_by=current_user,
                                           extra_context={'scheduled_date': job.scheduled_date.strftime('%B %d, %Y')})
            except Exception:
                pass

        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


@schedule_api_bp.route('/api/schedule/tech-availability')
@login_required
def tech_availability():
    """Get a technician's assignments for a date."""
    db = get_session()
    try:
        tech_id = request.args.get('technician_id', type=int)
        date_str = request.args.get('date', '')

        if not tech_id or not date_str:
            return jsonify({'assignments': []})

        try:
            # Handle both "2026-04-10" and "2026-04-10T00:00:00" formats
            if 'T' in date_str:
                target_date = datetime.fromisoformat(date_str.replace('Z', '')).date()
            else:
                from datetime import date as date_type
                parts = date_str.split('-')
                target_date = date_type(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            return jsonify({'assignments': [], 'count': 0})

        day_start = datetime.combine(target_date, datetime.min.time())
        day_end = day_start + timedelta(days=1)

        jobs = db.query(Job).filter(
            Job.organization_id == current_user.organization_id,
            Job.assigned_technician_id == tech_id,
            Job.scheduled_date >= day_start,
            Job.scheduled_date < day_end,
            Job.status.in_(['scheduled', 'in_progress'])
        ).order_by(Job.scheduled_date).all()

        assignments = [{
            'jobId': j.id,
            'jobNumber': j.job_number,
            'title': j.title,
            'start': j.scheduled_date.isoformat() if j.scheduled_date else None,
            'end': (j.scheduled_end or (j.scheduled_date + timedelta(hours=2))).isoformat() if j.scheduled_date else None,
        } for j in jobs]

        return jsonify({'assignments': assignments, 'count': len(assignments)})
    finally:
        db.close()


@schedule_api_bp.route('/api/schedule/unassigned-jobs')
@login_required
def unassigned_jobs():
    """Return unassigned/unscheduled jobs."""
    db = get_session()
    try:
        from sqlalchemy import or_
        jobs = db.query(Job).filter(
            Job.organization_id == current_user.organization_id,
            Job.status.in_(['draft', 'scheduled']),
            or_(
                Job.assigned_technician_id == None,
                Job.scheduled_date == None,
            )
        ).order_by(Job.created_at.desc()).limit(50).all()

        result = [{
            'id': j.id,
            'jobNumber': j.job_number,
            'title': j.title[:40],
            'clientName': j.client.display_name if j.client else '',
            'priority': j.priority or 'normal',
            'division': j.division.name if j.division else '',
            'divisionColor': j.division.color if j.division else '#666',
            'jobType': j.job_type or '',
            'estimatedAmount': j.estimated_amount or 0,
            'status': j.status,
        } for j in jobs]

        return jsonify(result)
    finally:
        db.close()
