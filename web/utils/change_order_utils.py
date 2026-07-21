"""
Change order creation, update, line item management, and approval application.
All functions take an open db session. Caller must commit.
"""
from datetime import timezone, datetime, date
from models.change_order import (
    ChangeOrder, ChangeOrderLineItem,
    ChangeOrderStatus, ChangeOrderReason,
    ChangeOrderCostType, ChangeOrderRequestedBy,
)
from models.job import Job


def generate_co_number(db, job):
    """Generate CO number: CO-{JOB_NUMBER}-{SEQ}"""
    existing_count = db.query(ChangeOrder).filter_by(job_id=job.id).count()
    seq = existing_count + 1
    job_num = (job.job_number or str(job.id)).replace('/', '-').replace(' ', '_')
    return f"CO-{job_num}-{seq:02d}"


def can_create_change_order(job):
    """Validate that a job can accept new change orders."""
    valid_statuses = ('scheduled', 'in_progress')
    if job.status not in valid_statuses:
        return False, f"Change orders can only be created for jobs that are Scheduled or In Progress (current: {job.status})"
    return True, "ok"


def create_change_order(db, job, form_data, created_by_id):
    """Create a new ChangeOrder (draft). Does NOT commit."""
    co = ChangeOrder(
        change_order_number=generate_co_number(db, job),
        job_id=job.id,
        title=form_data['title'],
        description=form_data['description'],
        reason=form_data['reason'],
        status=ChangeOrderStatus.draft.value,
        requested_by=form_data['requested_by'],
        requested_date=_parse_date(form_data.get('requested_date')) or date.today(),
        cost_type=form_data.get('cost_type', 'addition'),
        original_amount=float(form_data.get('original_amount') or 0),
        revised_amount=float(form_data.get('revised_amount') or 0),
        labor_hours_impact=float(form_data.get('labor_hours_impact') or 0),
        requires_client_approval='requires_client_approval' in form_data,
        creates_new_phase='creates_new_phase' in form_data,
        new_phase_title=form_data.get('new_phase_title'),
        created_by_id=created_by_id,
    )

    phase_id = form_data.get('phase_id')
    if phase_id:
        try:
            co.phase_id = int(phase_id)
        except (ValueError, TypeError):
            pass

    db.add(co)
    db.flush()
    return co


def update_change_order(db, co, form_data):
    """Update an existing draft/submitted change order."""
    if not co.is_editable:
        raise ValueError("Cannot edit a change order that is not in draft or submitted state.")

    co.title = form_data.get('title', co.title)
    co.description = form_data.get('description', co.description)
    if form_data.get('reason'):
        co.reason = form_data['reason']
    if form_data.get('requested_by'):
        co.requested_by = form_data['requested_by']
    if form_data.get('cost_type'):
        co.cost_type = form_data['cost_type']
    co.original_amount = float(form_data.get('original_amount') or co.original_amount or 0)
    co.revised_amount = float(form_data.get('revised_amount') or co.revised_amount or 0)
    co.labor_hours_impact = float(form_data.get('labor_hours_impact') or co.labor_hours_impact or 0)
    co.requires_client_approval = 'requires_client_approval' in form_data
    co.creates_new_phase = 'creates_new_phase' in form_data
    co.new_phase_title = form_data.get('new_phase_title', co.new_phase_title)
    co.updated_at = datetime.now(timezone.utc)

    phase_id = form_data.get('phase_id')
    if phase_id is not None:
        try:
            co.phase_id = int(phase_id) if phase_id else None
        except (ValueError, TypeError):
            pass

    return co


def save_line_items(db, co, form_data):
    """Replace all line items from form arrays."""
    db.query(ChangeOrderLineItem).filter_by(change_order_id=co.id).delete()

    descriptions = form_data.getlist('li_description[]')
    quantities = form_data.getlist('li_qty[]')
    unit_prices = form_data.getlist('li_unit_price[]')
    addition_indices = set(form_data.getlist('li_is_addition[]'))

    for idx, desc in enumerate(descriptions):
        if not desc.strip():
            continue
        item = ChangeOrderLineItem(
            change_order_id=co.id,
            description=desc.strip(),
            quantity=float(quantities[idx]) if idx < len(quantities) and quantities[idx] else 1,
            unit_price=float(unit_prices[idx]) if idx < len(unit_prices) and unit_prices[idx] else 0,
            is_addition=str(idx) in addition_indices,
        )
        db.add(item)


def apply_approved_change_order(db, co):
    """After CO approval, update job costs and optionally create a new phase."""
    job = co.job

    if job.original_estimated_cost is None:
        job.original_estimated_cost = float(job.estimated_amount or 0)

    total_co_delta = sum(
        c.cost_difference for c in job.change_orders
        if c.status == 'approved'
    )
    job.adjusted_estimated_cost = float(job.original_estimated_cost or 0) + total_co_delta

    if co.creates_new_phase and co.new_phase_title:
        from web.utils.phase_utils import create_phase
        create_phase(db, job, {
            'title': co.new_phase_title,
            'description': co.description,
            'estimated_cost': co.revised_amount,
        })


def check_contract_scope(job, proposed_co_delta):
    """Check if a proposed CO keeps job within contract scope."""
    result = {
        'within_scope': True, 'contract_value': None,
        'new_total': None, 'overage': 0.0, 'warning': None,
    }
    contract = getattr(job, 'contract', None)
    if not contract:
        return result
    contract_value = float(getattr(contract, 'value', 0) or 0)
    if contract_value <= 0:
        return result

    current_total = float(job.current_contract_value or 0)
    new_total = current_total + float(proposed_co_delta)
    result['contract_value'] = contract_value
    result['new_total'] = new_total

    if new_total > contract_value:
        overage = new_total - contract_value
        result['within_scope'] = False
        result['overage'] = overage
        result['warning'] = (
            f"This change order will cause the job to exceed the contract value "
            f"by ${overage:,.2f}. Contract: ${contract_value:,.2f}, New Total: ${new_total:,.2f}."
        )
    return result


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except ValueError:
        return None
