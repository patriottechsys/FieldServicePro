"""Utility functions for stock transfer workflow."""
from datetime import timezone, datetime
from models.stock_transfer import StockTransfer, StockTransferItem
from models.inventory import InventoryStock, InventoryTransaction
from models.part import Part


def generate_transfer_number(db):
    """Generate next sequential transfer number like TRF-2026-0001."""
    year = datetime.now(timezone.utc).year
    prefix = f"TRF-{year}-"
    last = db.query(StockTransfer).filter(
        StockTransfer.transfer_number.like(f"{prefix}%")
    ).order_by(StockTransfer.id.desc()).first()

    if last:
        try:
            num = int(last.transfer_number.split('-')[-1]) + 1
        except (ValueError, IndexError):
            num = 1
    else:
        num = 1

    return f"{prefix}{num:04d}"


def dispatch_transfer(db, transfer, sent_quantities, performed_by):
    """
    Mark items as sent, decrement source stock, set status to in_transit.
    sent_quantities = {item_id: quantity_sent, ...}
    """
    if transfer.status != 'approved':
        return False

    for item in transfer.items:
        qty_sent = sent_quantities.get(item.id, item.quantity_requested)
        item.quantity_sent = qty_sent

        # Decrement source stock
        stock = db.query(InventoryStock).filter_by(
            part_id=item.part_id, location_id=transfer.from_location_id
        ).first()
        if stock:
            stock.quantity_on_hand = max(0, stock.quantity_on_hand - qty_sent)

        # Audit transaction
        db.add(InventoryTransaction(
            organization_id=transfer.organization_id,
            part_id=item.part_id,
            location_id=transfer.from_location_id,
            transaction_type='transferred_out',
            quantity=-qty_sent,
            unit_cost=float(item.part.cost_price or 0) if item.part else 0,
            transfer_id=transfer.id,
            reference_number=transfer.transfer_number,
            notes=f'Transfer {transfer.transfer_number} dispatched',
            created_by=performed_by,
        ))

    transfer.status = 'in_transit'
    db.commit()
    return True


def receive_transfer(db, transfer, received_quantities, performed_by):
    """
    Mark items as received, increment destination stock, set status to completed.
    received_quantities = {item_id: quantity_received, ...}
    """
    if transfer.status != 'in_transit':
        return False

    for item in transfer.items:
        qty_received = received_quantities.get(item.id, item.quantity_sent or 0)
        item.quantity_received = qty_received

        # Get or create destination stock
        stock = db.query(InventoryStock).filter_by(
            part_id=item.part_id, location_id=transfer.to_location_id
        ).first()
        if not stock:
            stock = InventoryStock(
                part_id=item.part_id,
                location_id=transfer.to_location_id,
                quantity_on_hand=0,
            )
            db.add(stock)
            db.flush()

        stock.quantity_on_hand += qty_received
        stock.last_received_at = datetime.now(timezone.utc)

        # Audit transaction
        db.add(InventoryTransaction(
            organization_id=transfer.organization_id,
            part_id=item.part_id,
            location_id=transfer.to_location_id,
            transaction_type='transferred_in',
            quantity=qty_received,
            unit_cost=float(item.part.cost_price or 0) if item.part else 0,
            transfer_id=transfer.id,
            reference_number=transfer.transfer_number,
            notes=f'Transfer {transfer.transfer_number} received',
            created_by=performed_by,
        ))

    transfer.status = 'completed'
    transfer.completed_at = datetime.now(timezone.utc)
    transfer.completed_by = performed_by
    db.commit()
    return True


def cancel_transfer(db, transfer, performed_by):
    """Cancel a transfer. If in_transit, restore source stock."""
    if transfer.status == 'completed':
        return False

    # If already dispatched, restore source stock
    if transfer.status == 'in_transit':
        for item in transfer.items:
            if item.quantity_sent:
                stock = db.query(InventoryStock).filter_by(
                    part_id=item.part_id, location_id=transfer.from_location_id
                ).first()
                if stock:
                    stock.quantity_on_hand += item.quantity_sent

                db.add(InventoryTransaction(
                    organization_id=transfer.organization_id,
                    part_id=item.part_id,
                    location_id=transfer.from_location_id,
                    transaction_type='adjusted',
                    quantity=item.quantity_sent,
                    unit_cost=float(item.part.cost_price or 0) if item.part else 0,
                    transfer_id=transfer.id,
                    reference_number=transfer.transfer_number,
                    notes=f'Transfer {transfer.transfer_number} cancelled — stock restored',
                    created_by=performed_by,
                ))

    transfer.status = 'cancelled'
    db.commit()
    return True
