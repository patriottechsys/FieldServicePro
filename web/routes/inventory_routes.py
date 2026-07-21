"""Inventory management routes: locations, stock, dashboard, transactions."""
from datetime import timezone, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import desc, or_

from models.database import get_session
from models.inventory import InventoryLocation, InventoryStock, InventoryTransaction, LOCATION_TYPES, TRANSACTION_TYPES
from models.part import Part
from models.stock_transfer import StockTransfer
from models.technician import Technician
from models.division import Division
from web.auth import role_required

inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')


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


# ─── Inventory Dashboard ──────────────────────────────────────────────────────

@inventory_bp.route('/')
@login_required
def dashboard():
    db = get_session()
    try:
        org_id = current_user.organization_id

        locations = db.query(InventoryLocation).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(InventoryLocation.location_type, InventoryLocation.name).all()

        # Total inventory value
        all_stocks = db.query(InventoryStock).join(InventoryLocation).filter(
            InventoryLocation.organization_id == org_id
        ).all()
        total_value = sum(
            s.quantity_on_hand * float(s.part.cost_price or 0)
            for s in all_stocks
        )

        # Low stock alerts
        all_parts = db.query(Part).filter_by(organization_id=org_id, is_active=True).all()
        low_stock_parts = [
            p for p in all_parts
            if p.minimum_stock_level > 0 and p.total_stock <= p.minimum_stock_level
        ]

        # Pending transfers
        pending_transfers = db.query(StockTransfer).filter(
            StockTransfer.organization_id == org_id,
            StockTransfer.status.in_(['draft', 'pending', 'approved', 'in_transit'])
        ).count()

        # Recent transactions
        recent_transactions = db.query(InventoryTransaction).filter_by(
            organization_id=org_id
        ).order_by(desc(InventoryTransaction.created_at)).limit(15).all()

        return render_template('inventory/dashboard.html',
            active_page='inventory', user=current_user, divisions=_get_divisions(),
            can_admin=_can_admin(),
            locations=locations, total_value=total_value,
            low_stock_parts=low_stock_parts,
            pending_transfers=pending_transfers,
            recent_transactions=recent_transactions,
        )
    finally:
        db.close()


# ─── Location List ────────────────────────────────────────────────────────────

@inventory_bp.route('/locations')
@login_required
def locations():
    db = get_session()
    try:
        org_id = current_user.organization_id
        locs = db.query(InventoryLocation).filter_by(
            organization_id=org_id
        ).order_by(InventoryLocation.location_type, InventoryLocation.name).all()

        return render_template('inventory/locations.html',
            active_page='inventory', user=current_user, divisions=_get_divisions(),
            can_admin=_can_admin(), locations=locs,
        )
    finally:
        db.close()


# ─── New Location ─────────────────────────────────────────────────────────────

@inventory_bp.route('/locations/new', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'owner')
def new_location():
    db = get_session()
    try:
        org_id = current_user.organization_id
        techs = db.query(Technician).filter_by(is_active=True).order_by(Technician.first_name).all()

        if request.method == 'POST':
            tech_id = request.form.get('technician_id') or None
            loc = InventoryLocation(
                organization_id=org_id,
                name=request.form.get('name', '').strip(),
                location_type=request.form.get('location_type', 'warehouse'),
                address=request.form.get('address', '').strip() or None,
                description=request.form.get('description', '').strip() or None,
                technician_id=int(tech_id) if tech_id else None,
                is_active='is_active' in request.form or not request.form.get('_active_submitted'),
            )
            db.add(loc)
            db.commit()
            flash(f"Location '{loc.name}' created.", 'success')
            return redirect(url_for('inventory.locations'))

        return render_template('inventory/location_form.html',
            active_page='inventory', user=current_user, divisions=_get_divisions(),
            location=None, technicians=techs, location_types=LOCATION_TYPES,
            title='New Location',
        )
    finally:
        db.close()


# ─── Edit Location ────────────────────────────────────────────────────────────

@inventory_bp.route('/locations/<int:loc_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'owner')
def edit_location(loc_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        loc = db.query(InventoryLocation).filter_by(id=loc_id, organization_id=org_id).first()
        if not loc:
            flash('Location not found.', 'error')
            return redirect(url_for('inventory.locations'))

        techs = db.query(Technician).filter_by(is_active=True).order_by(Technician.first_name).all()

        if request.method == 'POST':
            tech_id = request.form.get('technician_id') or None
            loc.name = request.form.get('name', '').strip()
            loc.location_type = request.form.get('location_type', loc.location_type)
            loc.address = request.form.get('address', '').strip() or None
            loc.description = request.form.get('description', '').strip() or None
            loc.technician_id = int(tech_id) if tech_id else None
            loc.is_active = 'is_active' in request.form
            db.commit()
            flash(f"Location '{loc.name}' updated.", 'success')
            return redirect(url_for('inventory.locations'))

        return render_template('inventory/location_form.html',
            active_page='inventory', user=current_user, divisions=_get_divisions(),
            location=loc, technicians=techs, location_types=LOCATION_TYPES,
            title=f'Edit {loc.name}',
        )
    finally:
        db.close()


# ─── Location Detail ──────────────────────────────────────────────────────────

@inventory_bp.route('/locations/<int:loc_id>')
@login_required
def location_detail(loc_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        loc = db.query(InventoryLocation).filter_by(id=loc_id, organization_id=org_id).first()
        if not loc:
            flash('Location not found.', 'error')
            return redirect(url_for('inventory.locations'))

        stocks = db.query(InventoryStock).filter_by(
            location_id=loc_id
        ).join(Part).order_by(Part.trade, Part.name).all()

        transactions = db.query(InventoryTransaction).filter_by(
            location_id=loc_id
        ).order_by(desc(InventoryTransaction.created_at)).limit(20).all()

        return render_template('inventory/location_detail.html',
            active_page='inventory', user=current_user, divisions=_get_divisions(),
            can_admin=_can_admin(), location=loc, stocks=stocks,
            transactions=transactions,
        )
    finally:
        db.close()


# ─── Stock Adjustment (Admin only) ───────────────────────────────────────────

@inventory_bp.route('/adjust', methods=['POST'])
@login_required
@role_required('admin', 'owner')
def adjust_stock():
    db = get_session()
    try:
        part_id = int(request.form.get('part_id'))
        location_id = int(request.form.get('location_id'))
        new_qty = int(request.form.get('new_quantity', 0))
        notes = request.form.get('notes', '').strip()

        stock = db.query(InventoryStock).filter_by(
            part_id=part_id, location_id=location_id
        ).first()

        if not stock:
            stock = InventoryStock(part_id=part_id, location_id=location_id, quantity_on_hand=0)
            db.add(stock)
            db.flush()

        old_qty = stock.quantity_on_hand
        diff = new_qty - old_qty
        stock.quantity_on_hand = new_qty
        stock.last_counted_at = datetime.now(timezone.utc)

        part = db.query(Part).filter_by(id=part_id).first()
        loc = db.query(InventoryLocation).filter_by(id=location_id).first()

        tx = InventoryTransaction(
            organization_id=current_user.organization_id,
            part_id=part_id,
            location_id=location_id,
            transaction_type='adjusted',
            quantity=diff,
            unit_cost=float(part.cost_price or 0) if part else 0,
            notes=notes or f'Manual adjustment: {old_qty} -> {new_qty}',
            created_by=current_user.id,
        )
        db.add(tx)
        db.commit()

        flash(f'Stock adjusted: {old_qty} -> {new_qty}.', 'success')
        return redirect(request.referrer or url_for('inventory.dashboard'))
    except Exception as e:
        db.rollback()
        flash(f'Error adjusting stock: {e}', 'error')
        return redirect(url_for('inventory.dashboard'))
    finally:
        db.close()


# ─── Receive Stock ────────────────────────────────────────────────────────────

@inventory_bp.route('/receive', methods=['POST'])
@login_required
@role_required('admin', 'owner', 'dispatcher')
def receive_stock():
    db = get_session()
    try:
        data = request.get_json() or request.form
        part_id = int(data.get('part_id'))
        location_id = int(data.get('location_id'))
        quantity = int(data.get('quantity', 0))
        unit_cost = float(data.get('unit_cost', 0) or 0)
        notes = data.get('notes', '')

        if quantity <= 0:
            return jsonify({'error': 'Quantity must be positive'}), 400

        part = db.query(Part).filter_by(id=part_id).first()
        if not part:
            return jsonify({'error': 'Part not found'}), 404

        stock = db.query(InventoryStock).filter_by(
            part_id=part_id, location_id=location_id
        ).first()

        if not stock:
            stock = InventoryStock(part_id=part_id, location_id=location_id, quantity_on_hand=0)
            db.add(stock)
            db.flush()

        stock.quantity_on_hand += quantity
        stock.last_received_at = datetime.now(timezone.utc)

        tx = InventoryTransaction(
            organization_id=current_user.organization_id,
            part_id=part_id,
            location_id=location_id,
            transaction_type='received',
            quantity=quantity,
            unit_cost=unit_cost or float(part.cost_price or 0),
            notes=notes,
            created_by=current_user.id,
        )
        db.add(tx)
        db.commit()

        return jsonify({
            'success': True,
            'new_quantity': stock.quantity_on_hand,
            'message': f'Received {quantity} units of {part.name}.',
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


# ─── API: Stock levels for a location ────────────────────────────────────────

@inventory_bp.route('/api/stock/<int:location_id>')
@login_required
def api_location_stock(location_id):
    db = get_session()
    try:
        from models.inventory import InventoryLocation
        loc = db.query(InventoryLocation).filter_by(id=location_id, organization_id=current_user.organization_id).first()
        if not loc:
            return jsonify([]), 404
        stocks = db.query(InventoryStock).filter_by(
            location_id=location_id
        ).join(Part).filter(Part.is_active == True).order_by(Part.name).all()

        return jsonify([{
            'part_id': s.part_id,
            'part_number': s.part.part_number,
            'part_name': s.part.name,
            'unit': s.part.unit_of_measure,
            'quantity_on_hand': s.quantity_on_hand,
            'available_quantity': s.available_quantity,
            'quantity_reserved': s.quantity_reserved,
            'is_low_stock': s.is_low_stock,
        } for s in stocks])
    finally:
        db.close()


# ─── Transaction Audit Trail ─────────────────────────────────────────────────

@inventory_bp.route('/transactions')
@login_required
@role_required('admin', 'owner', 'dispatcher')
def transactions():
    db = get_session()
    try:
        org_id = current_user.organization_id
        page = int(request.args.get('page', 1))
        per_page = 50

        query = db.query(InventoryTransaction).filter_by(organization_id=org_id)

        # Filters
        tx_type = request.args.get('type', '')
        part_search = request.args.get('part', '').strip()
        location_id = request.args.get('location', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')

        if tx_type:
            query = query.filter(InventoryTransaction.transaction_type == tx_type)
        if location_id:
            query = query.filter(InventoryTransaction.location_id == int(location_id))
        if date_from:
            try:
                query = query.filter(InventoryTransaction.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
            except ValueError:
                pass
        if date_to:
            try:
                query = query.filter(InventoryTransaction.created_at <= datetime.strptime(date_to + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
            except ValueError:
                pass
        if part_search:
            query = query.join(Part).filter(or_(
                Part.name.ilike(f'%{part_search}%'),
                Part.part_number.ilike(f'%{part_search}%'),
            ))

        query = query.order_by(desc(InventoryTransaction.created_at))
        total = query.count()
        txns = query.offset((page - 1) * per_page).limit(per_page).all()
        total_pages = (total + per_page - 1) // per_page

        locations = db.query(InventoryLocation).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(InventoryLocation.name).all()

        return render_template('inventory/transactions.html',
            active_page='inventory', user=current_user, divisions=_get_divisions(),
            can_admin=_can_admin(),
            transactions=txns, total=total, page=page, per_page=per_page,
            total_pages=total_pages,
            tx_types=TRANSACTION_TYPES, locations=locations,
            tx_type=tx_type, part_search=part_search,
            location_id=location_id, date_from=date_from, date_to=date_to,
        )
    finally:
        db.close()
