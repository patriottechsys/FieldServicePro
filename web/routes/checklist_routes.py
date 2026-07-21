"""Routes for safety checklist management."""
import re
from datetime import timezone, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
from models.database import get_session
from models.checklist import ChecklistTemplate, ChecklistItem, CompletedChecklist, CompletedChecklistItem
from models.job import Job
from models.job_phase import JobPhase
from models.technician import Technician
from models.division import Division
from web.auth import role_required

checklists_bp = Blueprint('checklists', __name__)


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


def _tpl_vars(**extra):
    base = dict(active_page='checklists', user=current_user, divisions=_get_divisions())
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------

@checklists_bp.route('/settings/checklists')
@login_required
def template_list():
    db = get_session()
    try:
        templates = db.query(ChecklistTemplate).order_by(
            ChecklistTemplate.created_at.desc()
        ).all()

        filter_type = request.args.get('type', '')
        filter_category = request.args.get('category', '')
        if filter_type:
            templates = [t for t in templates if t.checklist_type == filter_type]
        if filter_category:
            templates = [t for t in templates if t.category == filter_category]

        active_count = sum(1 for t in templates if t.is_active)
        inactive_count = len(templates) - active_count

        return render_template('checklists/template_list.html',
                               **_tpl_vars(
                                   templates=templates,
                                   active_count=active_count,
                                   inactive_count=inactive_count,
                                   type_choices=ChecklistTemplate.TYPE_CHOICES,
                                   category_choices=ChecklistTemplate.CATEGORY_CHOICES,
                                   filter_type=filter_type,
                                   filter_category=filter_category,
                               ))
    finally:
        db.close()


@checklists_bp.route('/settings/checklists/new', methods=['GET', 'POST'])
@login_required
@role_required('owner', 'admin')
def template_new():
    db = get_session()
    try:
        if request.method == 'POST':
            return _save_template(db, template=None)

        return render_template('checklists/template_form.html',
                               **_tpl_vars(
                                   template=None,
                                   type_choices=ChecklistTemplate.TYPE_CHOICES,
                                   category_choices=ChecklistTemplate.CATEGORY_CHOICES,
                                   item_types=ChecklistItem.ITEM_TYPES,
                                   failure_actions=ChecklistItem.FAILURE_ACTIONS,
                               ))
    finally:
        db.close()


@checklists_bp.route('/settings/checklists/<int:template_id>')
@login_required
def template_detail(template_id):
    db = get_session()
    try:
        template = db.query(ChecklistTemplate).filter_by(id=template_id).first()
        if not template:
            abort(404)

        completions = db.query(CompletedChecklist).filter_by(
            template_id=template_id
        ).order_by(CompletedChecklist.completed_at.desc()).limit(20).all()

        total_completions = db.query(CompletedChecklist).filter_by(template_id=template_id).count()
        passed = db.query(CompletedChecklist).filter_by(template_id=template_id, overall_status='passed').count()
        failed = db.query(CompletedChecklist).filter_by(template_id=template_id, overall_status='failed').count()

        return render_template('checklists/template_detail.html',
                               **_tpl_vars(
                                   template=template,
                                   completions=completions,
                                   total_completions=total_completions,
                                   passed_count=passed,
                                   failed_count=failed,
                               ))
    finally:
        db.close()


@checklists_bp.route('/settings/checklists/<int:template_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('owner', 'admin')
def template_edit(template_id):
    db = get_session()
    try:
        template = db.query(ChecklistTemplate).filter_by(id=template_id).first()
        if not template:
            abort(404)

        if request.method == 'POST':
            return _save_template(db, template=template)

        return render_template('checklists/template_form.html',
                               **_tpl_vars(
                                   template=template,
                                   type_choices=ChecklistTemplate.TYPE_CHOICES,
                                   category_choices=ChecklistTemplate.CATEGORY_CHOICES,
                                   item_types=ChecklistItem.ITEM_TYPES,
                                   failure_actions=ChecklistItem.FAILURE_ACTIONS,
                               ))
    finally:
        db.close()


@checklists_bp.route('/settings/checklists/<int:template_id>/delete', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def template_delete(template_id):
    db = get_session()
    try:
        template = db.query(ChecklistTemplate).filter_by(id=template_id).first()
        if not template:
            abort(404)
        db.delete(template)
        db.commit()
        flash('Checklist template deleted.', 'success')
    finally:
        db.close()
    return redirect(url_for('checklists.template_list'))


@checklists_bp.route('/settings/checklists/<int:template_id>/toggle', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def template_toggle(template_id):
    db = get_session()
    try:
        template = db.query(ChecklistTemplate).filter_by(id=template_id).first()
        if not template:
            abort(404)
        template.is_active = not template.is_active
        db.commit()
        status = 'activated' if template.is_active else 'deactivated'
        flash(f'Checklist template {status}.', 'success')
    finally:
        db.close()
    return redirect(url_for('checklists.template_detail', template_id=template_id))


def _parse_indexed_items(form):
    """Parse items[0][question], items[0][type], ... from form data."""
    items = {}
    pattern = re.compile(r'^items\[(\d+)\]\[(\w+)\]$')
    for key in form:
        m = pattern.match(key)
        if m:
            idx, field = int(m.group(1)), m.group(2)
            items.setdefault(idx, {})[field] = form[key]
    return [items[k] for k in sorted(items.keys())]


def _save_template(db, template=None):
    """Save or update a checklist template from form data."""
    f = request.form
    is_new = template is None

    if is_new:
        template = ChecklistTemplate(created_by=current_user.id)
        db.add(template)

    template.name = f.get('name', '').strip()
    template.description = f.get('description', '').strip() or None
    template.checklist_type = f.get('checklist_type', 'pre_job')
    template.category = f.get('category', 'general_safety')
    template.is_active = f.get('is_active') == 'on'

    div_id = f.get('division_id', '').strip()
    template.division_id = int(div_id) if div_id else None

    # Required for job types (comma-separated → JSON list)
    raw_types = f.get('required_for_job_types', '').strip()
    if raw_types:
        template.required_job_types_list = [t.strip() for t in raw_types.split(',') if t.strip()]
    else:
        template.required_job_types_list = []

    # Remove existing items — they'll be re-created from form
    if not is_new:
        for item in list(template.items):
            db.delete(item)
        db.flush()

    # Parse indexed items: items[0][question], items[0][type], ...
    parsed_items = _parse_indexed_items(f)
    for i, data in enumerate(parsed_items):
        q = data.get('question', '').strip()
        if not q:
            continue
        item = ChecklistItem(
            question=q,
            item_type=data.get('type', 'yes_no'),
            is_required='required' in data,
            failure_action=data.get('failure_action', 'warning'),
            help_text=data.get('help_text', '').strip() or None,
            sort_order=i,
        )
        template.items.append(item)

    db.commit()
    flash(f'Checklist template {"created" if is_new else "updated"}.', 'success')
    return redirect(url_for('checklists.template_detail', template_id=template.id))


# ---------------------------------------------------------------------------
# Checklist Completion
# ---------------------------------------------------------------------------

@checklists_bp.route('/jobs/<int:job_id>/checklists')
@login_required
def job_checklists(job_id):
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id).first()
        if not job:
            abort(404)

        available = db.query(ChecklistTemplate).filter_by(is_active=True).order_by(
            ChecklistTemplate.checklist_type, ChecklistTemplate.name
        ).all()

        completed = db.query(CompletedChecklist).filter_by(job_id=job_id).order_by(
            CompletedChecklist.completed_at.desc()
        ).all()

        return render_template('checklists/job_checklists.html',
                               **_tpl_vars(
                                   job=job,
                                   available_templates=available,
                                   completed_checklists=completed,
                                   active_page='jobs',
                               ))
    finally:
        db.close()


@checklists_bp.route('/jobs/<int:job_id>/checklists/<int:template_id>/complete', methods=['GET', 'POST'])
@login_required
def complete_checklist(job_id, template_id):
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id).first()
        if not job:
            abort(404)
        template = db.query(ChecklistTemplate).filter_by(id=template_id).first()
        if not template:
            abort(404)

        phases = db.query(JobPhase).filter_by(job_id=job_id).order_by(JobPhase.sort_order).all()

        if request.method == 'POST':
            f = request.form
            completed = CompletedChecklist(
                template_id=template_id,
                job_id=job_id,
                completed_by=current_user.id,
                location=f.get('location', '').strip() or None,
                weather_conditions=f.get('weather_conditions', '').strip() or None,
                notes=f.get('notes', '').strip() or None,
            )
            phase_id = f.get('phase_id', '').strip()
            if phase_id:
                completed.phase_id = int(phase_id)

            has_failure = False
            has_block = False

            for item in template.items:
                response = f.get(f'item_{item.id}', '').strip()
                notes = f.get(f'item_{item.id}_notes', '').strip()

                is_compliant = True
                if item.item_type in ('yes_no', 'pass_fail'):
                    fail_values = ('no', 'fail')
                    if response.lower() in fail_values:
                        is_compliant = False
                        has_failure = True
                        if item.failure_action == 'block_work':
                            has_block = True

                ci = CompletedChecklistItem(
                    checklist_item_id=item.id,
                    response=response or None,
                    is_compliant=is_compliant,
                    notes=notes or None,
                    sort_order=item.sort_order,
                )
                completed.items.append(ci)

            if has_block:
                completed.overall_status = 'failed'
            elif has_failure:
                completed.overall_status = 'passed_with_exceptions'
            else:
                completed.overall_status = 'passed'

            db.add(completed)
            db.commit()

            flash(f'Checklist completed — {completed.status_display}.', 'success')
            return redirect(url_for('checklists.job_checklists', job_id=job_id))

        return render_template('checklists/complete_checklist.html',
                               **_tpl_vars(
                                   job=job,
                                   template=template,
                                   phases=phases,
                                   active_page='jobs',
                               ))
    finally:
        db.close()


@checklists_bp.route('/checklists/completed/<int:completed_id>')
@login_required
def completed_detail(completed_id):
    db = get_session()
    try:
        completed = db.query(CompletedChecklist).filter_by(id=completed_id).first()
        if not completed:
            abort(404)

        return render_template('checklists/completed_detail.html',
                               **_tpl_vars(
                                   completed=completed,
                                   active_page='jobs',
                               ))
    finally:
        db.close()


@checklists_bp.route('/checklists/completed/<int:completed_id>/review', methods=['POST'])
@login_required
@role_required('owner', 'admin')
def review_checklist(completed_id):
    db = get_session()
    try:
        completed = db.query(CompletedChecklist).filter_by(id=completed_id).first()
        if not completed:
            abort(404)

        completed.supervisor_reviewed = True
        completed.supervisor_id = current_user.id
        completed.supervisor_reviewed_at = datetime.now(timezone.utc)
        db.commit()
        flash('Checklist marked as reviewed.', 'success')
    finally:
        db.close()
    return redirect(url_for('checklists.completed_detail', completed_id=completed_id))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@checklists_bp.route('/api/checklists/reorder', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def api_reorder_items():
    """Reorder checklist items (AJAX drag-and-drop)."""
    data = request.get_json()
    if not data or 'items' not in data:
        return jsonify({'error': 'Invalid data'}), 400

    db = get_session()
    try:
        for idx, item_id in enumerate(data['items']):
            item = db.query(ChecklistItem).filter_by(id=item_id).first()
            if item:
                item.sort_order = idx
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()
