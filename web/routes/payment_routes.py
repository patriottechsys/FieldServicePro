"""Routes for payment records."""
from datetime import timezone, datetime, timedelta
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import desc, func
from models.database import get_session
from models.invoice import Invoice, Payment
from models.client import Client
from models.division import Division

payments_bp = Blueprint('payments', __name__)


def _get_divisions():
    db = get_session()
    try:
        return db.query(Division).filter_by(
            organization_id=current_user.organization_id, is_active=True
        ).order_by(Division.sort_order).all()
    finally:
        db.close()


@payments_bp.route('/payments')
@login_required
def payment_list():
    db = get_session()
    try:
        org_id = current_user.organization_id

        # Base query: payments joined to invoices in this org
        query = db.query(Payment).join(Invoice).filter(
            Invoice.organization_id == org_id
        )

        # Filters
        method = request.args.get('method', '')
        search = request.args.get('search', '').strip()
        date_range = request.args.get('range', '')

        if method:
            query = query.filter(Payment.payment_method == method)

        if date_range:
            days = int(date_range)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.filter(Payment.payment_date >= cutoff)

        payments = query.order_by(desc(Payment.payment_date)).all()

        # Build display list with client info
        payment_list = []
        for p in payments:
            inv = p.invoice
            client_name = ''
            if inv and inv.client:
                client_name = inv.client.display_name
            payment_list.append({
                'id': p.id,
                'payment_date': p.payment_date,
                'amount': float(p.amount or 0),
                'payment_method': p.payment_method,
                'reference_number': p.reference_number,
                'notes': p.notes,
                'invoice_id': p.invoice_id,
                'invoice_number': inv.invoice_number if inv else '',
                'client_name': client_name,
            })

        # Client-side search filtering uses data attributes, but let's also
        # filter server-side if search is provided
        if search:
            s = search.lower()
            payment_list = [
                p for p in payment_list
                if s in (p['invoice_number'] or '').lower()
                or s in (p['client_name'] or '').lower()
                or s in (p['reference_number'] or '').lower()
            ]

        # Stats
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        total_all_time = float(db.query(func.coalesce(func.sum(Payment.amount), 0)).join(
            Invoice).filter(Invoice.organization_id == org_id).scalar() or 0)

        total_this_month = float(db.query(func.coalesce(func.sum(Payment.amount), 0)).join(
            Invoice).filter(
            Invoice.organization_id == org_id,
            Payment.payment_date >= month_start
        ).scalar() or 0)

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        total_today = float(db.query(func.coalesce(func.sum(Payment.amount), 0)).join(
            Invoice).filter(
            Invoice.organization_id == org_id,
            Payment.payment_date >= today_start
        ).scalar() or 0)

        payments_today_count = db.query(Payment).join(Invoice).filter(
            Invoice.organization_id == org_id,
            Payment.payment_date >= today_start
        ).count()

        return render_template('payments/payment_list.html',
            active_page='payments',
            user=current_user,
            divisions=_get_divisions(),
            payments=payment_list,
            total_all_time=total_all_time,
            total_this_month=total_this_month,
            total_today=total_today,
            payments_today_count=payments_today_count,
            filter_method=method,
            filter_range=date_range,
            search=search,
        )
    finally:
        db.close()
