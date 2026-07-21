"""Quote routes — quote listing, creation, and client search."""

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func
from models.database import get_session
from models.client import Client
from models.quote import Quote, QuoteItem, QuoteStatus
from web.utils.helpers import get_divisions, get_active_division

quotes_bp = Blueprint('quotes_bp', __name__)


@quotes_bp.route('/quotes')
@login_required
def quotes_page():
    db = get_session()
    try:
        org_id = current_user.organization_id
        active_div = get_active_division(request)

        status_filter = request.args.get('status', '')

        q = db.query(Quote).filter_by(organization_id=org_id)
        if active_div:
            q = q.filter_by(division_id=active_div)
        if status_filter:
            q = q.filter_by(status=status_filter)

        from sqlalchemy.orm import joinedload
        quotes = q.options(
            joinedload(Quote.client),
            joinedload(Quote.division),
        ).order_by(Quote.created_at.desc()).all()

        quote_list = []
        for quote in quotes:
            qd = quote.to_dict()
            qd['client_name'] = quote.client.display_name if quote.client else 'Unknown'
            qd['division_name'] = quote.division.name if quote.division else ''
            qd['division_color'] = quote.division.color if quote.division else '#666'
            quote_list.append(qd)

        return render_template('quotes.html',
            active_page='quotes',
            user=current_user,
            divisions=get_divisions(),
            active_division=active_div,
            quotes=quote_list,
            statuses=[s.value for s in QuoteStatus],
            status_filter=status_filter,
        )
    finally:
        db.close()


@quotes_bp.route('/quotes/new')
@login_required
def quote_new_page():
    db = get_session()
    try:
        org_id = current_user.organization_id
        max_num = db.query(func.max(Quote.id)).filter_by(organization_id=org_id).scalar() or 0
        next_quote_number = f"QTE-{max_num + 1:05d}"
        return render_template('quote_new.html',
            active_page='quotes',
            user=current_user,
            divisions=get_divisions(),
            next_quote_number=next_quote_number,
        )
    finally:
        db.close()


@quotes_bp.route('/api/clients/search')
@login_required
def search_clients():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'clients': []})
    db = get_session()
    try:
        org_id = current_user.organization_id
        search = f"%{q}%"
        clients = db.query(Client).filter(
            Client.organization_id == org_id,
            Client.is_active == True,
            (Client.company_name.ilike(search) |
             Client.first_name.ilike(search) |
             Client.last_name.ilike(search) |
             Client.email.ilike(search))
        ).limit(10).all()
        return jsonify({'clients': [c.to_dict() for c in clients]})
    finally:
        db.close()


@quotes_bp.route('/api/quotes', methods=['POST'])
@login_required
def create_quote():
    from flask import request as req
    data = req.get_json()
    db = get_session()
    try:
        max_num = db.query(func.max(Quote.id)).filter_by(organization_id=current_user.organization_id).scalar() or 0
        quote_number = f"QTE-{max_num + 1:05d}"

        quote = Quote(
            organization_id=current_user.organization_id,
            division_id=data['division_id'],
            client_id=data['client_id'],
            property_id=data.get('property_id'),
            quote_number=quote_number,
            title=data['title'],
            description=data.get('description', ''),
            template_name=data.get('template_name'),
            created_by_id=current_user.id,
        )
        db.add(quote)
        db.flush()

        subtotal = 0
        for i, item_data in enumerate(data.get('items', [])):
            item_total = float(item_data.get('quantity', 1)) * float(item_data.get('unit_price', 0))
            item = QuoteItem(
                quote_id=quote.id,
                description=item_data['description'],
                quantity=float(item_data.get('quantity', 1)),
                unit_price=float(item_data.get('unit_price', 0)),
                total=item_total,
                sort_order=i,
            )
            db.add(item)
            subtotal += item_total

        discount = float(data.get('discount', 0))
        quote.subtotal = subtotal
        quote.discount = discount
        after_discount = max(0, subtotal - discount)
        quote.tax_amount = after_discount * ((quote.tax_rate or 13.0) / 100)
        quote.total = after_discount + quote.tax_amount
        if data.get('status'):
            quote.status = data['status']
        if data.get('notes'):
            quote.notes = data['notes']
        db.commit()

        if data.get('status') == 'sent':
            try:
                from web.utils.notification_service import NotificationService
                NotificationService.notify('quote_sent', quote, triggered_by=current_user)
            except Exception:
                pass

        return jsonify({'success': True, 'quote': quote.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()
