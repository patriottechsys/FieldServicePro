"""Invoice routes — invoice listing, detail, creation, statements, aging, approval workflow."""

from datetime import datetime, date, timezone, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort, Response
from flask_login import login_required, current_user
from sqlalchemy import func
from models.database import get_session
from models.client import Client
from models.division import Division
from models.job import Job
from models.invoice import Invoice, InvoiceItem, InvoiceStatus, Payment
from models.technician import Technician
from web.utils.helpers import get_divisions

invoices_bp = Blueprint('invoices_bp', __name__)


@invoices_bp.route('/invoices')
@login_required
def invoices_page():
    db = get_session()
    try:
        org_id = current_user.organization_id
        status_filter = request.args.get('status', '')
        active_div = request.args.get('division', type=int)

        q = db.query(Invoice).filter_by(organization_id=org_id)
        if status_filter:
            q = q.filter_by(status=status_filter)
        if active_div:
            q = q.filter_by(division_id=active_div)

        invoices = q.order_by(Invoice.created_at.desc()).all()

        # Existing KPIs — scope to the active status filter when one is applied
        kpi_base = db.query(Invoice).filter_by(organization_id=org_id)
        if status_filter:
            kpi_base = kpi_base.filter_by(status=status_filter)

        total_outstanding = db.query(func.coalesce(func.sum(Invoice.balance_due), 0)).filter(
            Invoice.organization_id == org_id,
            Invoice.status.in_([status_filter] if status_filter else ['sent', 'viewed', 'partial', 'overdue'])
        ).scalar()
        total_overdue = db.query(func.coalesce(func.sum(Invoice.balance_due), 0)).filter(
            Invoice.organization_id == org_id,
            Invoice.status.in_([status_filter] if status_filter else ['overdue'])
        ).scalar()

        # Overview card counts & values
        invoices_past_due_count = db.query(func.count(Invoice.id)).filter(
            Invoice.organization_id == org_id,
            Invoice.status == 'overdue'
        ).scalar() or 0
        invoices_past_due_value = float(total_overdue or 0)

        invoices_draft_count = db.query(func.count(Invoice.id)).filter(
            Invoice.organization_id == org_id,
            Invoice.status == 'draft'
        ).scalar() or 0
        invoices_draft_value = db.query(func.coalesce(func.sum(Invoice.total), 0)).filter(
            Invoice.organization_id == org_id,
            Invoice.status == 'draft'
        ).scalar() or 0

        invoices_sent_count = db.query(func.count(Invoice.id)).filter(
            Invoice.organization_id == org_id,
            Invoice.status.in_(['sent', 'viewed'])
        ).scalar() or 0
        invoices_sent_value = db.query(func.coalesce(func.sum(Invoice.balance_due), 0)).filter(
            Invoice.organization_id == org_id,
            Invoice.status.in_(['sent', 'viewed'])
        ).scalar() or 0

        # Past-30-day metrics
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        sixty_days_ago = datetime.now(timezone.utc) - timedelta(days=60)

        invoices_issued_30d = db.query(func.count(Invoice.id)).filter(
            Invoice.organization_id == org_id,
            Invoice.issued_date >= thirty_days_ago
        ).scalar() or 0

        total_invoiced_30d = db.query(func.coalesce(func.sum(Invoice.total), 0)).filter(
            Invoice.organization_id == org_id,
            Invoice.issued_date >= thirty_days_ago
        ).scalar() or 0

        avg_invoice_30d = db.query(func.coalesce(func.avg(Invoice.total), 0)).filter(
            Invoice.organization_id == org_id,
            Invoice.issued_date >= thirty_days_ago
        ).scalar() or 0

        # Previous 30-day period for % change
        invoices_issued_prev = db.query(func.count(Invoice.id)).filter(
            Invoice.organization_id == org_id,
            Invoice.issued_date >= sixty_days_ago,
            Invoice.issued_date < thirty_days_ago
        ).scalar() or 0
        avg_invoice_prev = db.query(func.coalesce(func.avg(Invoice.total), 0)).filter(
            Invoice.organization_id == org_id,
            Invoice.issued_date >= sixty_days_ago,
            Invoice.issued_date < thirty_days_ago
        ).scalar() or 0

        issued_pct_change = 0
        if invoices_issued_prev > 0:
            issued_pct_change = round(((invoices_issued_30d - invoices_issued_prev) / invoices_issued_prev) * 100)
        avg_pct_change = 0
        if avg_invoice_prev > 0:
            avg_pct_change = round(((avg_invoice_30d - avg_invoice_prev) / avg_invoice_prev) * 100)

        # Payment time stats (median approximation & average) for paid invoices
        paid_invoices = db.query(Invoice).filter(
            Invoice.organization_id == org_id,
            Invoice.status == 'paid',
            Invoice.paid_date != None,
            Invoice.issued_date != None
        ).all()
        payment_days = sorted([
            (inv.paid_date - inv.issued_date).days
            for inv in paid_invoices
            if inv.paid_date and inv.issued_date
        ])
        if payment_days:
            mid = len(payment_days) // 2
            median_payment_days = payment_days[mid] if len(payment_days) % 2 else round((payment_days[mid - 1] + payment_days[mid]) / 2)
            avg_payment_days = round(sum(payment_days) / len(payment_days))
        else:
            median_payment_days = 0
            avg_payment_days = 0

        inv_list = []
        for inv in invoices:
            d = inv.to_dict()
            d['client_name'] = inv.client.display_name if inv.client else 'Unknown'
            d['subject'] = inv.job.title if inv.job else (inv.notes[:60] if inv.notes else '')
            inv_list.append(d)

        return render_template('invoices.html',
            active_page='invoices',
            user=current_user,
            divisions=get_divisions(),
            invoices=inv_list,
            total_outstanding=total_outstanding,
            total_overdue=total_overdue,
            status_filter=status_filter,
            statuses=[s.value for s in InvoiceStatus],
            invoices_past_due_count=invoices_past_due_count,
            invoices_past_due_value=invoices_past_due_value,
            invoices_draft_count=invoices_draft_count,
            invoices_draft_value=float(invoices_draft_value),
            invoices_sent_count=invoices_sent_count,
            invoices_sent_value=float(invoices_sent_value),
            invoices_issued_30d=invoices_issued_30d,
            total_invoiced_30d=float(total_invoiced_30d),
            avg_invoice_30d=float(avg_invoice_30d),
            issued_pct_change=issued_pct_change,
            avg_pct_change=avg_pct_change,
            median_payment_days=median_payment_days,
            avg_payment_days=avg_payment_days,
            active_division=active_div,
        )
    finally:
        db.close()


@invoices_bp.route('/invoices/new', methods=['GET', 'POST'])
@login_required
def invoice_new():
    """Create a new invoice with full commercial billing support."""
    if current_user.role not in ('owner', 'admin', 'dispatcher'):
        abort(403)

    from web.utils.payment_terms import calculate_due_date
    from web.utils.po_utils import handle_po_linking
    from models.settings import OrganizationSettings

    db = get_session()
    try:
        org_id = current_user.organization_id
        clients = db.query(Client).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Client.company_name, Client.last_name).all()
        jobs = db.query(Job).filter(
            Job.organization_id == org_id,
            Job.status.notin_(['cancelled'])
        ).order_by(Job.created_at.desc()).limit(50).all()
        divs = db.query(Division).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Division.sort_order).all()

        if request.method == 'POST':
            f = request.form
            settings = OrganizationSettings.get_or_create(db, org_id)

            # Parse dates
            invoice_date_str = f.get('invoice_date', '')
            invoice_date = date.fromisoformat(invoice_date_str) if invoice_date_str else date.today()
            terms = f.get('payment_terms', 'net_30')
            custom_days = int(f.get('custom_payment_days') or 0)
            due_date_str = f.get('due_date', '')
            if due_date_str:
                due_dt = date.fromisoformat(due_date_str)
            else:
                due_dt = calculate_due_date(invoice_date, terms, custom_days)

            client_id = int(f.get('client_id')) if f.get('client_id') else None
            client = db.query(Client).filter_by(id=client_id).first() if client_id else None

            # Build invoice
            inv = Invoice(
                organization_id=org_id,
                client_id=client_id,
                job_id=int(f.get('job_id')) if f.get('job_id') else None,
                invoice_number=settings.next_invoice_number(db),
                status=f.get('status', 'draft'),
                issued_date=datetime.combine(invoice_date, datetime.min.time()),
                due_date=datetime.combine(due_dt, datetime.min.time()) if due_dt else None,
                payment_terms=terms,
                cost_code=f.get('cost_code', '').strip() or None,
                department=f.get('department', '').strip() or None,
                billing_contact=f.get('billing_contact', '').strip() or None,
                po_number_display=f.get('po_number_display', '').strip() or None,
                notes=f.get('notes', '').strip() or None,
                approval_status='not_required',
                created_by_id=current_user.id,
            )
            db.add(inv)
            db.flush()

            # Parse line items
            descs = f.getlist('item_desc[]')
            qtys = f.getlist('item_qty[]')
            rates = f.getlist('item_rate[]')
            taxed_indices = set(f.getlist('item_tax[]'))

            subtotal = 0.0
            tax_total = 0.0
            tax_rate = 13.0
            tax_exempt = client.tax_exempt if client else False

            for i, desc in enumerate(descs):
                if not desc.strip():
                    continue
                qty = float(qtys[i] if i < len(qtys) else 1)
                rate_val = float(rates[i] if i < len(rates) else 0)
                is_taxable = str(i) in taxed_indices
                line_total = qty * rate_val
                line_tax = line_total * (tax_rate / 100) if is_taxable and not tax_exempt else 0

                item = InvoiceItem(
                    invoice_id=inv.id,
                    description=desc.strip(),
                    quantity=qty,
                    unit_price=rate_val,
                    total=line_total,
                    sort_order=i,
                )
                db.add(item)
                subtotal += line_total
                tax_total += line_tax

            inv.subtotal = subtotal
            inv.tax_rate = tax_rate
            inv.tax_amount = 0 if tax_exempt else tax_total
            inv.total = subtotal + (0 if tax_exempt else tax_total)
            inv.balance_due = inv.total
            db.flush()

            # PO linking
            try:
                warnings = handle_po_linking(db, inv, f.get('po_id'))
                for w in warnings:
                    flash(w, 'warning')
            except ValueError as exc:
                db.rollback()
                flash(str(exc), 'danger')
                return redirect(url_for('invoices_bp.invoice_new'))

            # Approval status
            if client and settings.requires_approval(inv.total, client.client_type):
                inv.approval_status = 'pending'

            db.commit()

            if inv.approval_status == 'pending':
                flash(f'Invoice {inv.invoice_number} created and awaiting approval.', 'info')
            else:
                flash(f'Invoice {inv.invoice_number} created.', 'success')
            return redirect(url_for('invoices_bp.invoice_detail', invoice_id=inv.id))

        # GET
        return render_template('invoice_new.html',
            active_page='invoices', user=current_user, divisions=get_divisions(),
            clients=clients,
            jobs=jobs,
            all_divisions=[d.to_dict() for d in divs],
            invoice=None,
            today=date.today(),
        )
    finally:
        db.close()


@invoices_bp.route('/api/invoices/prefill-materials/<int:job_id>')
@login_required
def invoice_prefill_materials(job_id):
    """Return billable verified materials as JSON for invoice line item prefill."""
    db = get_session()
    try:
        job = db.query(Job).filter_by(id=job_id, organization_id=current_user.organization_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        from web.utils.materials_utils import get_billable_materials_for_invoice
        items = get_billable_materials_for_invoice(db, job_id)
        return jsonify(items)
    finally:
        db.close()


@invoices_bp.route('/invoices/<int:invoice_id>')
@login_required
def invoice_detail(invoice_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        inv = db.query(Invoice).filter_by(id=invoice_id, organization_id=org_id).first()
        if not inv:
            flash('Invoice not found', 'error')
            return redirect(url_for('invoices_bp.invoices_page'))

        client = inv.client
        prop = None
        property_address = ''
        if inv.job and inv.job.property:
            prop = inv.job.property
            property_address = prop.display_address

        items = db.query(InvoiceItem).filter_by(invoice_id=inv.id).order_by(InvoiceItem.sort_order).all()

        return render_template('invoice_detail.html',
            active_page='invoices', user=current_user, divisions=get_divisions(),
            invoice=inv.to_dict(),
            invoice_obj=inv,
            client=client.to_dict() if client else {},
            client_name=client.display_name if client else 'Unknown',
            property_address=property_address,
            invoice_items=[item.to_dict() for item in items],
        )
    finally:
        db.close()


# ========== Bulk Statements ==========

@invoices_bp.route('/invoices/statements')
@login_required
def bulk_statements():
    """Bulk client statements — commercial clients with outstanding balances."""
    from models.client import Client
    db = get_session()
    try:
        org_id = current_user.organization_id
        today = date.today()
        start_date = request.args.get('start_date')

        if start_date:
            try:
                start_date = date.fromisoformat(start_date)
            except ValueError:
                start_date = None

        if not start_date:
            if today.month == 1:
                start_date = date(today.year - 1, 12, 1)
            else:
                start_date = date(today.year, today.month - 1, 1)

        # Commercial clients with outstanding balances in the date range
        from sqlalchemy import distinct
        inv_q = db.query(distinct(Invoice.client_id)).filter(
            Invoice.organization_id == org_id,
            Invoice.status.in_(['sent', 'overdue', 'partial']),
            Invoice.created_at >= datetime(start_date.year, start_date.month, start_date.day),
            Invoice.created_at <= datetime(today.year, today.month, today.day, 23, 59, 59),
        )
        client_ids_with_balance = inv_q.all()
        client_ids = [r[0] for r in client_ids_with_balance]

        clients_with_balance = db.query(Client).filter(
            Client.id.in_(client_ids),
            Client.organization_id == org_id,
        ).order_by(Client.company_name, Client.last_name).all()

        client_totals = []
        for client in clients_with_balance:
            outstanding = db.query(func.coalesce(func.sum(Invoice.balance_due), 0)).filter(
                Invoice.client_id == client.id,
                Invoice.status.in_(['sent', 'overdue', 'partial']),
                Invoice.created_at >= datetime(start_date.year, start_date.month, start_date.day),
                Invoice.created_at <= datetime(today.year, today.month, today.day, 23, 59, 59),
            ).scalar() or 0
            client_totals.append({
                'client': client,
                'outstanding': float(outstanding),
                'billing_email': client.billing_email or client.email,
            })

        return render_template('invoices/bulk_statements.html',
            active_page='statements', user=current_user, divisions=get_divisions(),
            client_totals=client_totals,
            start_date=start_date, end_date=today,
        )
    finally:
        db.close()


# ========== AR Aging Report ==========

@invoices_bp.route('/invoices/aging')
@login_required
def aging_report():
    if current_user.role == 'technician':
        abort(403)
    from collections import defaultdict
    db = get_session()
    try:
        org_id = current_user.organization_id

        f_client_id = request.args.get('client_id', type=int)
        f_division_id = request.args.get('division_id', type=int)
        f_overdue = request.args.get('overdue_only', 'false').lower() == 'true'
        f_sort = request.args.get('sort', 'total')
        f_dir = request.args.get('dir', 'desc')

        q = db.query(Invoice).filter(
            Invoice.organization_id == org_id,
            Invoice.status.in_(['sent', 'overdue', 'partial'])
        )
        if f_client_id:
            q = q.filter(Invoice.client_id == f_client_id)

        invoices = q.all()
        today = date.today()

        def _build_row():
            return {'client': None, 'current': 0.0, 'days_1_30': 0.0,
                    'days_31_60': 0.0, 'days_61_90': 0.0, 'days_90_plus': 0.0,
                    'total': 0.0, 'invoice_count': 0}

        rows = defaultdict(_build_row)
        for inv in invoices:
            if not inv.due_date:
                continue
            remaining = float(inv.balance_due or 0)
            if remaining <= 0:
                continue

            row = rows[inv.client_id]
            row['client'] = inv.client
            row['total'] += remaining
            row['invoice_count'] += 1

            bucket = inv.aging_bucket
            if bucket == 'current':
                row['current'] += remaining
            elif bucket == '1_30':
                row['days_1_30'] += remaining
            elif bucket == '31_60':
                row['days_31_60'] += remaining
            elif bucket == '61_90':
                row['days_61_90'] += remaining
            else:
                row['days_90_plus'] += remaining

        aging_data = list(rows.values())

        if f_overdue:
            aging_data = [r for r in aging_data
                          if r['days_1_30'] + r['days_31_60'] + r['days_61_90'] + r['days_90_plus'] > 0]

        sort_map = {
            'client': lambda r: (r['client'].display_name or '').lower() if r['client'] else '',
            'total': lambda r: r['total'],
            'current': lambda r: r['current'],
            'days_1_30': lambda r: r['days_1_30'],
            'days_31_60': lambda r: r['days_31_60'],
            'days_61_90': lambda r: r['days_61_90'],
            'days_90_plus': lambda r: r['days_90_plus'],
        }
        aging_data.sort(key=sort_map.get(f_sort, sort_map['total']), reverse=(f_dir == 'desc'))

        totals = {k: sum(r[k] for r in aging_data) for k in
                  ['current', 'days_1_30', 'days_31_60', 'days_61_90', 'days_90_plus', 'total']}

        clients = db.query(Client).filter_by(
            organization_id=org_id, is_active=True
        ).order_by(Client.company_name, Client.last_name).all()

        return render_template('invoices/aging_report.html',
            active_page='aging', user=current_user, divisions=get_divisions(),
            aging_data=aging_data, totals=totals, clients=clients,
            filters={'client_id': f_client_id, 'division_id': f_division_id,
                     'overdue_only': f_overdue, 'sort': f_sort, 'dir': f_dir},
            today=today,
        )
    finally:
        db.close()


# ========== Invoice Approval Workflow ==========

@invoices_bp.route('/invoices/approvals')
@login_required
def approval_queue():
    from models.settings import OrganizationSettings
    db = get_session()
    try:
        org_id = current_user.organization_id
        settings = OrganizationSettings.get_or_create(db, org_id)
        if current_user.role not in settings.approval_role_list:
            abort(403)

        pending = db.query(Invoice).filter(
            Invoice.organization_id == org_id,
            Invoice.approval_status == 'pending'
        ).order_by(Invoice.created_at.asc()).all()

        now = datetime.now(timezone.utc)
        pending_data = []
        for inv in pending:
            d = inv.to_dict()
            d['client_name'] = inv.client.display_name if inv.client else 'Unknown'
            d['job_title'] = inv.job.title if inv.job else None
            d['days_waiting'] = (now - inv.created_at).days if inv.created_at else 0
            pending_data.append(d)

        return render_template('invoices/approval_queue.html',
            active_page='approvals', user=current_user, divisions=get_divisions(),
            pending_invoices=pending_data,
            settings=settings.to_dict(),
        )
    finally:
        db.close()


@invoices_bp.route('/invoices/<int:invoice_id>/approve', methods=['POST'])
@login_required
def approve_invoice(invoice_id):
    from models.settings import OrganizationSettings
    db = get_session()
    try:
        org_id = current_user.organization_id
        settings = OrganizationSettings.get_or_create(db, org_id)
        if current_user.role not in settings.approval_role_list:
            return jsonify({'error': 'Unauthorized'}), 403

        invoice = db.query(Invoice).filter_by(id=invoice_id, organization_id=org_id).first()
        if not invoice:
            return jsonify({'error': 'Invoice not found'}), 404
        if invoice.approval_status != 'pending':
            return jsonify({'error': 'Invoice is not pending approval'}), 400

        invoice.approval_status = 'approved'
        invoice.approved_by = current_user.id
        invoice.approved_at = datetime.now(timezone.utc)
        invoice.rejection_reason = None
        db.commit()

        try:
            from web.utils.notification_service import NotificationService
            NotificationService.notify('item_approved', invoice, triggered_by=current_user)
        except Exception:
            pass

        if request.is_json:
            return jsonify({'success': True, 'invoice_number': invoice.invoice_number})

        flash(f'Invoice {invoice.invoice_number} approved.', 'success')
        return redirect(request.referrer or url_for('invoices_bp.approval_queue'))
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        db.close()


@invoices_bp.route('/invoices/<int:invoice_id>/reject', methods=['POST'])
@login_required
def reject_invoice(invoice_id):
    from models.settings import OrganizationSettings
    db = get_session()
    try:
        org_id = current_user.organization_id
        settings = OrganizationSettings.get_or_create(db, org_id)
        if current_user.role not in settings.approval_role_list:
            return jsonify({'error': 'Unauthorized'}), 403

        invoice = db.query(Invoice).filter_by(id=invoice_id, organization_id=org_id).first()
        if not invoice:
            return jsonify({'error': 'Invoice not found'}), 404

        data = request.get_json(force=True, silent=True) or {}
        reason = (data.get('reason') or '').strip()
        if not reason:
            return jsonify({'error': 'A rejection reason is required.'}), 400

        invoice.approval_status = 'rejected'
        invoice.rejection_reason = reason
        invoice.status = 'draft'
        db.commit()

        try:
            from web.utils.notification_service import NotificationService
            NotificationService.notify('item_rejected', invoice, triggered_by=current_user,
                                       extra_context={'reason': reason})
        except Exception:
            pass

        if request.is_json:
            return jsonify({'success': True, 'invoice_number': invoice.invoice_number})

        flash(f'Invoice {invoice.invoice_number} rejected and returned to draft.', 'warning')
        return redirect(request.referrer or url_for('invoices_bp.approval_queue'))
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        db.close()


# ========== API: Invoice PO Linking ==========

@invoices_bp.route('/api/invoices/<int:invoice_id>/link-po', methods=['POST'])
@login_required
def api_invoice_link_po(invoice_id):
    """Link or unlink a PO to an invoice. POST { po_id: int|null }"""
    from web.utils.po_utils import handle_po_linking
    from web.utils.validation import validate, InvoiceLinkPOSchema
    db = get_session()
    try:
        org_id = current_user.organization_id
        invoice = db.query(Invoice).filter_by(id=invoice_id, organization_id=org_id).first()
        if not invoice:
            return jsonify({'success': False, 'error': 'Invoice not found'}), 404

        data = request.get_json(force=True)
        obj, err = validate(InvoiceLinkPOSchema, data)
        if err:
            return jsonify(err), 400
        new_po_id = obj.po_id

        try:
            warnings = handle_po_linking(db, invoice, new_po_id)
            db.commit()
            return jsonify({
                'success': True,
                'warnings': warnings,
                'po_number': invoice.po_number_display,
            })
        except ValueError as exc:
            db.rollback()
            return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()


@invoices_bp.route('/api/invoices/<int:invoice_id>/set-terms', methods=['POST'])
@login_required
def api_invoice_set_terms(invoice_id):
    """Set payment terms and recalculate due date. POST { payment_terms, custom_days }"""
    from web.utils.payment_terms import calculate_due_date
    from web.utils.validation import validate, InvoiceSetTermsSchema
    db = get_session()
    try:
        org_id = current_user.organization_id
        invoice = db.query(Invoice).filter_by(id=invoice_id, organization_id=org_id).first()
        if not invoice:
            return jsonify({'success': False, 'error': 'Invoice not found'}), 404

        data = request.get_json(force=True)
        obj, err = validate(InvoiceSetTermsSchema, data)
        if err:
            return jsonify(err), 400
        invoice.payment_terms = obj.payment_terms
        invoice.calculate_due_date()
        db.commit()
        return jsonify({
            'success': True,
            'due_date': invoice.due_date.isoformat() if invoice.due_date else None,
            'payment_terms': invoice.payment_terms,
        })
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()


# ========== API: Billing / Payment Terms ==========

@invoices_bp.route('/api/payment-terms/due-date', methods=['GET'])
@login_required
def api_due_date():
    """AJAX: calculate due date from invoice_date + terms."""
    from web.utils.payment_terms import calculate_due_date, PAYMENT_TERMS_LABELS

    invoice_date_str = request.args.get('invoice_date', '')
    terms = request.args.get('terms', 'net_30')
    custom_days = request.args.get('custom_days', None)

    try:
        if invoice_date_str:
            inv_date = date.fromisoformat(invoice_date_str)
        else:
            inv_date = date.today()
        due = calculate_due_date(inv_date, terms, custom_days)
        return jsonify({
            'due_date': due.isoformat(),
            'due_date_display': due.strftime('%B %d, %Y'),
            'label': PAYMENT_TERMS_LABELS.get(terms, terms),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@invoices_bp.route('/api/client/<int:client_id>/billing-defaults', methods=['GET'])
@invoices_bp.route('/api/clients/<int:client_id>/billing', methods=['GET'])
@login_required
def api_client_billing_defaults(client_id):
    """AJAX: Return client billing defaults for invoice form auto-population."""
    from web.utils.payment_terms import get_terms_for_client

    db = get_session()
    try:
        client = db.query(Client).filter_by(
            id=client_id, organization_id=current_user.organization_id
        ).first()
        if not client:
            return jsonify({'error': 'Client not found'}), 404

        defaults = get_terms_for_client(client)

        # Outstanding balance
        outstanding = db.query(func.coalesce(func.sum(Invoice.balance_due), 0)).filter(
            Invoice.client_id == client_id,
            Invoice.status.in_(['sent', 'overdue', 'partial'])
        ).scalar() or 0

        credit_limit = float(client.credit_limit) if client.credit_limit else None
        available_credit = (credit_limit - float(outstanding)) if credit_limit else None

        return jsonify({
            'payment_terms': defaults['terms'],
            'custom_days': defaults['custom_days'],
            'due_date': defaults['due_date'].isoformat(),
            'due_date_display': defaults['due_date'].strftime('%B %d, %Y'),
            'require_po': client.require_po,
            'tax_exempt': client.tax_exempt,
            'tax_exempt_number': client.tax_exempt_number,
            'billing_contact_name': client.billing_contact_name,
            'billing_email': client.billing_email,
            'credit_limit': credit_limit,
            'outstanding_balance': float(outstanding),
            'available_credit': available_credit,
            'is_commercial': client.client_type == 'commercial',
        })
    finally:
        db.close()
