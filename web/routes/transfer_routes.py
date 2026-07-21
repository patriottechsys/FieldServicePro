"""Stock transfer workflow routes."""
from datetime import timezone, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import desc

from models.database import get_session
from models.stock_transfer import StockTransfer, StockTransferItem, TRANSFER_STATUSES
from models.inventory import InventoryLocation, InventoryStock
from models.part import Part
from models.division import Division
from web.auth import role_required
from web.utils.transfer_utils import (
    generate_transfer_number, dispatch_transfer, receive_transfer, cancel_transfer
)

transfers_bp = Blueprint('transfers', __name__, url_prefix='/inventory/transfers')


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


def _can_admin():
    return current_user.role in ('owner', 'admin')


def _can_dispatch():
    return current_user.role in ('owner', 'admin', 'dispatcher')


# ── Transfer List ─────────────────────────────────────────────────────────────

@transfers_bp.route('/')
@login_required
def transfer_list():
    db = get_session()
    try:
        org_id = current_user.organization_id
        status_filter = request.args.get('status', '')

        query = db.query(StockTransfer).filter_by(organization_id=org_id)
        if status_filter:
            query = query.filter(StockTransfer.status == status_filter)

        transfers = query.order_by(desc(StockTransfer.created_at)).all()

        return render_template('transfers/list.html',
            active_page='inventory', user=current_user, divisions=_get_divisions(),
            can_admin=_can_admin(), can_dispatch=_can_dispatch(),
            transfers=transfers, statuses=TRANSFER_STATUSES,
            status_filter=status_filter,
        )
    finally:
        db.close()


# ── Transfer Detail ───────────────────────────────────────────────────────────

@transfers_bp.route('/<int:transfer_id>')
@login_required
def transfer_detail(transfer_id):
    db = get_session()
    try:
        transfer = db.query(StockTransfer).filter_by(
            id=transfer_id, organization_id=current_user.organization_id
        ).first()
        if not transfer:
            flash('Transfer not found.', 'error')
            return redirect(url_for('transfers.transfer_list'))

        return render_template('transfers/detail.html',
            active_page='inventory', user=current_user, divisions=_get_divisions(),
            can_admin=_can_admin(), can_dispatch=_can_dispatch(),
            transfer=transfer,
        )
    finally:
        db.close()


# ── New Transfer ──────────────────────────────────────────────────────────────

@transfers_bp.route('/new', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def new_transfer():
    db = get_session()
    try:
        org_id = current_user.organization_id
        locations = db.query(InventoryLocation).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(InventoryLocation.name).all()
        parts = db.query(Part).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Part.name).all()

        if request.method == 'POST':
            from_loc_id = int(request.form.get('from_location_id', 0))
            to_loc_id = int(request.form.get('to_location_id', 0))

            if from_loc_id == to_loc_id:
                flash('Source and destination must be different.', 'error')
                return redirect(url_for('transfers.new_transfer'))

            part_ids = request.form.getlist('part_id[]')
            quantities = request.form.getlist('quantity[]')
            items_data = []
            for pid, qty in zip(part_ids, quantities):
                if pid and qty and int(qty) > 0:
                    items_data.append({'part_id': int(pid), 'quantity': int(qty)})

            if not items_data:
                flash('Add at least one item.', 'error')
                return redirect(url_for('transfers.new_transfer'))

            transfer = StockTransfer(
                organization_id=org_id,
                transfer_number=generate_transfer_number(db),
                status='requested',
                from_location_id=from_loc_id,
                to_location_id=to_loc_id,
                notes=request.form.get('notes', '').strip() or None,
                requested_by=current_user.id,
            )
            db.add(transfer)
            db.flush()

            for item_data in items_data:
                part = db.query(Part).filter_by(id=item_data['part_id']).first()
                db.add(StockTransferItem(
                    transfer_id=transfer.id,
                    part_id=item_data['part_id'],
                    quantity_requested=item_data['quantity'],
                    unit_cost=float(part.cost_price or 0) if part else 0,
                ))

            db.commit()
            flash(f'Transfer {transfer.transfer_number} created.', 'success')
            return redirect(url_for('transfers.transfer_detail', transfer_id=transfer.id))

        return render_template('transfers/form.html',
            active_page='inventory', user=current_user, divisions=_get_divisions(),
            locations=locations, parts=parts,
        )
    finally:
        db.close()


# ── Approve ───────────────────────────────────────────────────────────────────

@transfers_bp.route('/<int:transfer_id>/approve', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def approve_transfer_route(transfer_id):
    db = get_session()
    try:
        transfer = db.query(StockTransfer).filter_by(
            id=transfer_id, organization_id=current_user.organization_id
        ).first()
        if not transfer or transfer.status != 'requested':
            flash('Cannot approve this transfer.', 'error')
        else:
            transfer.status = 'approved'
            transfer.approved_by = current_user.id
            transfer.approved_at = datetime.now(timezone.utc)
            db.commit()
            flash('Transfer approved.', 'success')
    finally:
        db.close()
    return redirect(url_for('transfers.transfer_detail', transfer_id=transfer_id))


# ── Dispatch ──────────────────────────────────────────────────────────────────

@transfers_bp.route('/<int:transfer_id>/dispatch', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def dispatch_transfer_route(transfer_id):
    db = get_session()
    try:
        transfer = db.query(StockTransfer).filter_by(
            id=transfer_id, organization_id=current_user.organization_id
        ).first()
        if not transfer:
            flash('Transfer not found.', 'error')
            return redirect(url_for('transfers.transfer_list'))

        sent = {}
        for item in transfer.items:
            val = request.form.get(f'qty_sent_{item.id}', item.quantity_requested)
            sent[item.id] = int(val)

        result = dispatch_transfer(db, transfer, sent, current_user.id)
        if result:
            flash('Transfer dispatched. Items removed from source.', 'success')
        else:
            flash('Cannot dispatch this transfer.', 'error')
    except Exception as e:
        db.rollback()
        flash(f'Error: {e}', 'error')
    finally:
        db.close()
    return redirect(url_for('transfers.transfer_detail', transfer_id=transfer_id))


# ── Receive ───────────────────────────────────────────────────────────────────

@transfers_bp.route('/<int:transfer_id>/receive', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def receive_transfer_route(transfer_id):
    db = get_session()
    try:
        transfer = db.query(StockTransfer).filter_by(
            id=transfer_id, organization_id=current_user.organization_id
        ).first()
        if not transfer:
            flash('Transfer not found.', 'error')
            return redirect(url_for('transfers.transfer_list'))

        received = {}
        for item in transfer.items:
            val = request.form.get(f'qty_received_{item.id}', item.quantity_sent or 0)
            received[item.id] = int(val)

        result = receive_transfer(db, transfer, received, current_user.id)
        if result:
            flash('Transfer received. Inventory updated at destination.', 'success')
        else:
            flash('Cannot receive this transfer.', 'error')
    except Exception as e:
        db.rollback()
        flash(f'Error: {e}', 'error')
    finally:
        db.close()
    return redirect(url_for('transfers.transfer_detail', transfer_id=transfer_id))


# ── Cancel ────────────────────────────────────────────────────────────────────

@transfers_bp.route('/<int:transfer_id>/cancel', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def cancel_transfer_route(transfer_id):
    db = get_session()
    try:
        transfer = db.query(StockTransfer).filter_by(
            id=transfer_id, organization_id=current_user.organization_id
        ).first()
        if not transfer:
            flash('Transfer not found.', 'error')
        else:
            result = cancel_transfer(db, transfer, current_user.id)
            if result:
                flash('Transfer cancelled.', 'warning')
            else:
                flash('Cannot cancel a completed transfer.', 'error')
    except Exception as e:
        db.rollback()
        flash(f'Error: {e}', 'error')
    finally:
        db.close()
    return redirect(url_for('transfers.transfer_detail', transfer_id=transfer_id))


# ── API: Stock at a location for transfer form ───────────────────────────────

@transfers_bp.route('/api/location-stock/<int:location_id>')
@login_required
def api_transfer_stock(location_id):
    db = get_session()
    try:
        from models.inventory import InventoryLocation
        loc = db.query(InventoryLocation).filter_by(id=location_id, organization_id=current_user.organization_id).first()
        if not loc:
            return jsonify([]), 404
        stocks = db.query(InventoryStock).filter_by(
            location_id=location_id
        ).join(Part).filter(
            Part.is_active == True, InventoryStock.quantity_on_hand > 0
        ).all()
        return jsonify([{
            'part_id': s.part_id,
            'part_number': s.part.part_number,
            'part_name': s.part.name,
            'available': s.available_quantity,
        } for s in stocks])
    finally:
        db.close()
