"""Parts & Materials utility functions."""
import csv
import io
from datetime import timezone, datetime
from sqlalchemy import func
from models.part import Part, PART_CATEGORIES, PART_TRADES, UNIT_TYPES
from models.inventory import InventoryStock, InventoryTransaction
from models.job_material import JobMaterial


def generate_part_number(db, org_id, trade='general'):
    """Generate next sequential part number like PRT-ELEC-0001."""
    prefix_map = {
        'plumbing': 'PLM', 'hvac': 'HVAC', 'electrical': 'ELEC',
        'general': 'GEN', 'multi': 'MLT',
    }
    trade_prefix = prefix_map.get(trade, 'GEN')
    prefix = f"PRT-{trade_prefix}-"

    last = db.query(Part).filter(
        Part.organization_id == org_id,
        Part.part_number.like(f"{prefix}%")
    ).order_by(Part.id.desc()).first()

    if last:
        try:
            num = int(last.part_number.split('-')[-1]) + 1
        except (ValueError, IndexError):
            num = 1
    else:
        num = 1

    return f"{prefix}{num:04d}"


def get_catalog_stats(db, org_id):
    """Get summary stats for the parts catalog."""
    total = db.query(func.count(Part.id)).filter_by(organization_id=org_id, is_active=True).scalar() or 0

    low_stock_count = 0
    total_value = 0.0

    parts = db.query(Part).filter_by(organization_id=org_id, is_active=True).all()
    for p in parts:
        stock = sum(s.quantity_on_hand for s in p.inventory_stocks)
        val = stock * float(p.cost_price or 0)
        total_value += val
        if p.minimum_stock_level > 0 and stock <= p.minimum_stock_level:
            low_stock_count += 1

    return {
        'total_parts': total,
        'low_stock_count': low_stock_count,
        'total_value': round(total_value, 2),
    }


def get_low_stock_count(db, org_id):
    """Get count of low-stock active parts for sidebar badge."""
    count = 0
    parts = db.query(Part).filter_by(organization_id=org_id, is_active=True).filter(
        Part.minimum_stock_level > 0
    ).all()
    for p in parts:
        stock = sum(s.quantity_on_hand for s in p.inventory_stocks)
        if stock <= p.minimum_stock_level:
            count += 1
    return count


def export_parts_csv(db, org_id):
    """Export parts catalog as CSV string."""
    parts = db.query(Part).filter_by(organization_id=org_id).order_by(Part.part_number).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'part_number', 'name', 'trade', 'category', 'subcategory', 'description',
        'manufacturer', 'manufacturer_part_number', 'preferred_vendor_name',
        'unit_of_measure', 'cost_price', 'sell_price', 'markup_percentage',
        'minimum_stock_level', 'barcode', 'is_active',
    ])

    for p in parts:
        writer.writerow([
            p.part_number, p.name, p.trade, p.category, p.subcategory or '',
            p.description or '', p.manufacturer or '',
            p.manufacturer_part_number or '', p.preferred_vendor_name or '',
            p.unit_of_measure, p.cost_price, p.sell_price,
            p.markup_percentage, p.minimum_stock_level,
            p.barcode or '', 'Yes' if p.is_active else 'No',
        ])

    return output.getvalue()


def generate_csv_template():
    """Generate an empty CSV template with headers."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'part_number', 'name', 'trade', 'category', 'subcategory', 'description',
        'manufacturer', 'manufacturer_part_number', 'preferred_vendor_name',
        'unit_of_measure', 'cost_price', 'sell_price', 'markup_percentage',
        'minimum_stock_level', 'barcode',
    ])
    # Example row
    writer.writerow([
        '', '3/4" Copper 90° Elbow', 'plumbing', 'pipe_fittings', 'copper',
        'Standard copper elbow fitting', 'Mueller Industries', 'W-07004',
        'Ferguson Enterprises', 'each', '4.50', '8.10', '80', '25', '',
    ])
    return output.getvalue()


def import_parts_csv(db, org_id, file_stream, created_by=None):
    """Import parts from CSV. Returns (created_count, updated_count, errors)."""
    created = 0
    updated = 0
    errors = []

    try:
        content = file_stream.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
    except Exception as e:
        return 0, 0, [f"Failed to read CSV: {e}"]

    valid_categories = {c for c, _ in PART_CATEGORIES}
    valid_trades = {t for t, _ in PART_TRADES}
    valid_units = {u for u, _ in UNIT_TYPES}

    for row_num, row in enumerate(reader, start=2):
        try:
            name = (row.get('name') or row.get('Name') or '').strip()
            if not name:
                errors.append(f"Row {row_num}: Missing name")
                continue

            trade = (row.get('trade') or row.get('Trade') or 'general').strip().lower()
            if trade not in valid_trades:
                trade = 'general'

            category = (row.get('category') or row.get('Category') or 'other').strip().lower()
            if category not in valid_categories:
                category = 'other'

            unit = (row.get('unit_of_measure') or row.get('Unit') or 'each').strip().lower()
            if unit not in valid_units:
                unit = 'each'

            part_number = (row.get('part_number') or row.get('Part Number') or '').strip()

            existing = None
            if part_number:
                existing = db.query(Part).filter_by(
                    organization_id=org_id, part_number=part_number
                ).first()

            if existing:
                existing.name = name
                existing.trade = trade
                existing.category = category
                existing.subcategory = (row.get('subcategory') or '').strip() or existing.subcategory
                existing.description = (row.get('description') or row.get('Description') or '').strip() or existing.description
                existing.manufacturer = (row.get('manufacturer') or row.get('Manufacturer') or '').strip() or existing.manufacturer
                existing.manufacturer_part_number = (row.get('manufacturer_part_number') or '').strip() or existing.manufacturer_part_number
                existing.preferred_vendor_name = (row.get('preferred_vendor_name') or '').strip() or existing.preferred_vendor_name
                existing.unit_of_measure = unit
                existing.cost_price = float(row.get('cost_price') or row.get('Unit Cost') or existing.cost_price or 0)
                existing.sell_price = float(row.get('sell_price') or row.get('Sell Price') or existing.sell_price or 0)
                existing.markup_percentage = float(row.get('markup_percentage') or row.get('Markup %') or existing.markup_percentage or 0)
                existing.minimum_stock_level = int(row.get('minimum_stock_level') or row.get('Reorder Point') or existing.minimum_stock_level or 0)
                existing.barcode = (row.get('barcode') or row.get('Barcode') or '').strip() or existing.barcode
                updated += 1
            else:
                if not part_number:
                    db.flush()
                    part_number = generate_part_number(db, org_id, trade)

                part = Part(
                    organization_id=org_id,
                    part_number=part_number,
                    name=name,
                    trade=trade,
                    category=category,
                    subcategory=(row.get('subcategory') or '').strip() or None,
                    description=(row.get('description') or row.get('Description') or '').strip() or None,
                    manufacturer=(row.get('manufacturer') or row.get('Manufacturer') or '').strip() or None,
                    manufacturer_part_number=(row.get('manufacturer_part_number') or '').strip() or None,
                    preferred_vendor_name=(row.get('preferred_vendor_name') or '').strip() or None,
                    unit_of_measure=unit,
                    cost_price=float(row.get('cost_price') or row.get('Unit Cost') or 0),
                    sell_price=float(row.get('sell_price') or row.get('Sell Price') or 0),
                    markup_percentage=float(row.get('markup_percentage') or row.get('Markup %') or 0),
                    minimum_stock_level=int(row.get('minimum_stock_level') or row.get('Reorder Point') or 0),
                    barcode=(row.get('barcode') or row.get('Barcode') or '').strip() or None,
                    is_active=True,
                    created_by=created_by,
                )
                db.add(part)
                created += 1

        except Exception as e:
            errors.append(f"Row {row_num}: {e}")

    if created or updated:
        db.commit()

    return created, updated, errors


def get_low_stock_alerts(db, org_id):
    """Return all parts below minimum stock level with details."""
    parts = db.query(Part).filter_by(organization_id=org_id, is_active=True).filter(
        Part.minimum_stock_level > 0
    ).all()

    alerts = []
    for part in parts:
        total = part.total_stock
        if total <= part.minimum_stock_level:
            shortage = part.minimum_stock_level - total
            alerts.append({
                'part': part,
                'total_stock': total,
                'minimum': part.minimum_stock_level,
                'shortage': shortage,
                'severity': 'critical' if total == 0 else 'warning',
            })

    return sorted(alerts, key=lambda x: (x['severity'] == 'critical', x['shortage']), reverse=True)


def get_reorder_suggestions(db, org_id):
    """Generate reorder suggestions with usage-based quantities."""
    from datetime import timezone, timedelta
    from models.job_material import JobMaterial

    alerts = get_low_stock_alerts(db, org_id)
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    suggestions = []
    for alert in alerts:
        part = alert['part']
        recent_usage = db.query(JobMaterial).filter(
            JobMaterial.part_id == part.id,
            JobMaterial.added_at >= thirty_days_ago,
            JobMaterial.quantity > 0,
        ).all()

        total_used = sum(float(m.quantity) for m in recent_usage)
        avg_daily = total_used / 30

        suggested_qty = max(
            alert['shortage'] + part.minimum_stock_level,
            int(avg_daily * 30) if avg_daily > 0 else part.minimum_stock_level * 2,
        )

        suggestions.append({
            **alert,
            'avg_daily_usage': round(avg_daily, 2),
            'suggested_reorder_qty': suggested_qty,
            'estimated_cost': round(suggested_qty * float(part.cost_price or 0), 2),
        })

    return suggestions
