"""Client routes — client listing, detail, creation, statements, notes, communications."""

from datetime import datetime, date, timezone, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from models.database import get_session
from models.user import User
from models.client import Client, ClientNote, ClientCommunication, Property
from models.job import Job
from models.invoice import Invoice, Payment
from models.quote import Quote
from models.contract import Contract
from web.utils.helpers import get_divisions

clients_bp = Blueprint('clients_bp', __name__)


def _get_client_communications(db, client_id):
    try:
        from models.communication import CommunicationLog
        return db.query(CommunicationLog).filter_by(client_id=client_id).order_by(CommunicationLog.communication_date.desc()).limit(20).all()
    except Exception:
        return []


def _count_client_communications(db, client_id):
    try:
        from models.communication import CommunicationLog
        from sqlalchemy import func as _f
        return db.query(_f.count(CommunicationLog.id)).filter_by(client_id=client_id).scalar() or 0
    except Exception:
        return 0


@clients_bp.route('/clients')
@login_required
def clients_page():
    db = get_session()
    try:
        org_id = current_user.organization_id
        client_type = request.args.get('type', '')

        q = db.query(Client).filter_by(organization_id=org_id, is_active=True)
        if client_type:
            q = q.filter_by(client_type=client_type)

        clients = q.order_by(Client.company_name, Client.last_name).all()

        return render_template('clients.html',
            active_page='clients',
            user=current_user,
            divisions=get_divisions(),
            clients=[c.to_dict() for c in clients],
            client_type_filter=client_type,
        )
    finally:
        db.close()


@clients_bp.route('/clients/<int:client_id>')
@login_required
def client_detail(client_id):
    db = get_session()
    try:

        org_id = current_user.organization_id
        division_filter = request.args.get('division')
        division_filter = int(division_filter) if division_filter else None

        client = db.query(Client).filter_by(id=client_id, organization_id=org_id).first()
        if not client:
            flash('Client not found', 'error')
            return redirect(url_for('clients_bp.clients_page'))

        # Properties
        properties = [p.to_dict() for p in client.properties if p.is_active]

        # Contacts
        contacts = [c.to_dict() for c in client.contacts]

        # Base queries filtered to this client
        from sqlalchemy.orm import joinedload
        jobs_q = db.query(Job).filter_by(client_id=client_id).options(
            joinedload(Job.division),
            joinedload(Job.technician),
            joinedload(Job.property),
        )
        quotes_q = db.query(Quote).filter_by(client_id=client_id)
        invoices_q = db.query(Invoice).filter_by(client_id=client_id)

        if division_filter:
            jobs_q = jobs_q.filter_by(division_id=division_filter)
            quotes_q = quotes_q.filter_by(division_id=division_filter)

        # Active work: scheduled or in_progress
        active_jobs = jobs_q.filter(Job.status.in_(['scheduled', 'in_progress'])).order_by(Job.scheduled_date).all()
        # Needs attention: draft or on_hold
        needs_attention_jobs = jobs_q.filter(Job.status.in_(['draft', 'on_hold'])).order_by(Job.created_at.desc()).all()
        # Completed / past jobs
        completed_jobs = jobs_q.filter(Job.status.in_(['completed', 'invoiced'])).order_by(Job.completed_at.desc()).all()
        # All jobs for the "All Jobs" tab
        all_jobs = jobs_q.order_by(Job.created_at.desc()).all()

        def enrich_job(job):
            jd = job.to_dict()
            jd['division_name'] = job.division.name if job.division else ''
            jd['division_color'] = job.division.color if job.division else '#666'
            jd['technician_name'] = job.technician.full_name if job.technician else 'Unassigned'
            jd['property_address'] = job.property.display_address if job.property else ''
            return jd

        # Quotes
        quotes = quotes_q.order_by(Quote.created_at.desc()).all()
        quote_list = []
        for q in quotes:
            qd = q.to_dict()
            qd['division_name'] = q.division.name if q.division else ''
            qd['division_color'] = q.division.color if q.division else '#666'
            quote_list.append(qd)

        # Invoices
        invoices = invoices_q.order_by(Invoice.created_at.desc()).all()
        inv_list = [inv.to_dict() for inv in invoices]

        # Financial summary
        total_invoiced = db.query(func.coalesce(func.sum(Invoice.total), 0)).filter_by(client_id=client_id).scalar()
        total_outstanding = db.query(func.coalesce(func.sum(Invoice.balance_due), 0)).filter(
            Invoice.client_id == client_id,
            Invoice.status.in_(['sent', 'viewed', 'partial', 'overdue'])
        ).scalar()

        # Division list for this client's jobs (for filter pills)
        client_division_ids = db.query(Job.division_id).filter_by(client_id=client_id).distinct().all()
        from models import Division
        client_divisions = db.query(Division).filter(
            Division.id.in_([d[0] for d in client_division_ids if d[0]])
        ).order_by(Division.sort_order).all()

        # Client notes (starred first, then by date)
        notes = db.query(ClientNote).filter_by(client_id=client_id).order_by(
            ClientNote.is_starred.desc(), ClientNote.created_at.desc()
        ).all()
        note_list = []
        for note in notes:
            nd = note.to_dict()
            author = db.query(User).filter_by(id=note.user_id).first() if note.user_id else None
            nd['author_name'] = author.full_name if author else 'System'
            nd['author_initials'] = (
                (author.first_name[0] + (author.last_name[0] if author.last_name else ''))
                if author and author.first_name else '?'
            ).upper()
            note_list.append(nd)

        # Communications log
        comms = db.query(ClientCommunication).filter_by(client_id=client_id).order_by(
            ClientCommunication.created_at.desc()
        ).limit(50).all()
        comm_list = []
        for comm in comms:
            cd = comm.to_dict()
            author = db.query(User).filter_by(id=comm.user_id).first() if comm.user_id else None
            cd['author_name'] = author.full_name if author else 'System'
            comm_list.append(cd)

        # Communication stats
        comm_total = db.query(func.count(ClientCommunication.id)).filter_by(client_id=client_id).scalar()
        comm_sent = db.query(func.count(ClientCommunication.id)).filter(
            ClientCommunication.client_id == client_id,
            ClientCommunication.status.in_(['sent', 'delivered', 'opened'])
        ).scalar()
        comm_opened = db.query(func.count(ClientCommunication.id)).filter_by(client_id=client_id, status='opened').scalar()

        # Billing history (last 10 invoices for sidebar)
        billing_history = invoices_q.order_by(Invoice.created_at.desc()).limit(10).all()
        billing_list = [inv.to_dict() for inv in billing_history]

        # Contracts for this client
        client_contracts = db.query(Contract).filter_by(client_id=client_id)\
                             .order_by(Contract.status, Contract.start_date.desc()).all()

        # SLA compliance for this client
        client_jobs_with_sla = db.query(Job).filter(
            Job.client_id == client_id,
            Job.sla_id.isnot(None),
            Job.actual_resolution_time.isnot(None)
        ).all()
        sla_compliance_pct = None
        if client_jobs_with_sla:
            met = sum(1 for j in client_jobs_with_sla if j.sla_resolution_met)
            sla_compliance_pct = round(met / len(client_jobs_with_sla) * 100, 1)

        # Purchase Orders for this client
        from models.purchase_order import PurchaseOrder
        client_pos = db.query(PurchaseOrder).filter_by(client_id=client_id)\
                       .order_by(PurchaseOrder.created_at.desc()).all()

        # Aging snapshot
        outstanding_invs = db.query(Invoice).filter(
            Invoice.client_id == client_id,
            Invoice.organization_id == org_id,
            Invoice.status.in_(['sent', 'overdue', 'partial']),
        ).all()
        aging = {'current': 0.0, 'days_1_30': 0.0, 'days_31_60': 0.0,
                 'days_61_90': 0.0, 'days_90_plus': 0.0, 'total': 0.0}
        for inv in outstanding_invs:
            bal = float(inv.balance_due or 0)
            if bal <= 0:
                continue
            bucket = inv.aging_bucket
            col = {'current': 'current', '1_30': 'days_1_30', '31_60': 'days_31_60',
                   '61_90': 'days_61_90', '90_plus': 'days_90_plus'}.get(bucket, 'current')
            aging[col] += bal
            aging['total'] += bal

        credit_available = None
        if client.credit_limit:
            credit_available = float(client.credit_limit) - aging['total']

        today_date = date.today()
        if today_date.month == 1:
            default_stmt_start = date(today_date.year - 1, 12, 1)
        else:
            default_stmt_start = date(today_date.year, today_date.month - 1, 1)

        return render_template('client_detail.html',
            active_page='clients',
            user=current_user,
            divisions=get_divisions(),
            client=client.to_dict(),
            client_obj=client,
            properties=properties,
            contacts=contacts,
            active_jobs=[enrich_job(j) for j in active_jobs],
            needs_attention_jobs=[enrich_job(j) for j in needs_attention_jobs],
            completed_jobs=[enrich_job(j) for j in completed_jobs],
            all_jobs=[enrich_job(j) for j in all_jobs],
            quotes=quote_list,
            invoices=inv_list,
            total_invoiced=total_invoiced,
            total_outstanding=total_outstanding,
            client_divisions=[d.to_dict() for d in client_divisions],
            active_division=division_filter,
            client_notes=note_list,
            communications=comm_list,
            comm_total=comm_total,
            comm_sent=comm_sent,
            comm_opened=comm_opened,
            billing_history=billing_list,
            contracts=client_contracts,
            sla_compliance_pct=sla_compliance_pct,
            purchase_orders=client_pos,
            aging=aging,
            credit_available=credit_available,
            today=today_date,
            default_stmt_start=default_stmt_start,
            default_stmt_end=today_date,
            client_projects=client.projects if hasattr(client, 'projects') else [],
            active_warranties=client.warranties if hasattr(client, 'warranties') else [],
            client_callbacks=client.callbacks if hasattr(client, 'callbacks') else [],
            client_communications=_get_client_communications(db, client_id),
            client_comm_count=_count_client_communications(db, client_id),
        )
    finally:
        db.close()


@clients_bp.route('/clients/new')
@login_required
def client_new_page():
    return render_template('client_new.html',
        active_page='clients',
        user=current_user,
        divisions=get_divisions(),
    )


@clients_bp.route('/clients/<int:client_id>/edit')
@login_required
def client_edit_page(client_id):
    db = get_session()
    try:
        org_id = current_user.organization_id
        client = db.query(Client).filter_by(id=client_id, organization_id=org_id).first()
        if not client:
            flash('Client not found', 'error')
            return redirect(url_for('clients_bp.clients_page'))
        return render_template('client_new.html',
            active_page='clients',
            user=current_user,
            divisions=get_divisions(),
            edit_client=client,
        )
    finally:
        db.close()


# ========== Client Statements ==========

@clients_bp.route('/clients/<int:client_id>/statement')
@login_required
def client_statement(client_id):
    """Generate statement for a single client."""
    if current_user.role == 'technician':
        abort(403)
    db = get_session()
    try:
        org_id = current_user.organization_id
        client = db.query(Client).filter_by(id=client_id, organization_id=org_id).first()
        if not client:
            flash('Client not found', 'error')
            return redirect(url_for('clients_bp.clients_page'))

        today = date.today()

        # Default to previous month
        if today.month == 1:
            def_start = date(today.year - 1, 12, 1)
        else:
            def_start = date(today.year, today.month - 1, 1)
        def_end = date(today.year, today.month, 1) - timedelta(days=1)

        start_str = request.args.get('start_date', def_start.isoformat())
        end_str = request.args.get('end_date', def_end.isoformat())
        try:
            start_date = date.fromisoformat(start_str)
            end_date = date.fromisoformat(end_str)
        except ValueError:
            flash('Invalid date range.', 'danger')
            return redirect(url_for('clients_bp.client_detail', client_id=client_id))

        # Invoices in period
        invoices_in_period = db.query(Invoice).filter(
            Invoice.client_id == client_id,
            Invoice.organization_id == org_id,
            Invoice.issued_date >= datetime.combine(start_date, datetime.min.time()),
            Invoice.issued_date <= datetime.combine(end_date, datetime.max.time()),
            Invoice.status != 'void',
        ).order_by(Invoice.issued_date).all()

        # Opening balance
        prior_invoices = db.query(Invoice).filter(
            Invoice.client_id == client_id,
            Invoice.organization_id == org_id,
            Invoice.issued_date < datetime.combine(start_date, datetime.min.time()),
            Invoice.status.in_(['sent', 'overdue', 'partial']),
        ).all()
        opening_balance = sum(float(inv.balance_due or 0) for inv in prior_invoices)

        # Payments in period
        payments_in_period = db.query(Payment).join(Invoice).filter(
            Invoice.client_id == client_id,
            Invoice.organization_id == org_id,
            Payment.payment_date >= datetime.combine(start_date, datetime.min.time()),
            Payment.payment_date <= datetime.combine(end_date, datetime.max.time()),
        ).order_by(Payment.payment_date).all()

        new_charges = sum(float(inv.total or 0) for inv in invoices_in_period)
        payments_rcvd = sum(float(p.amount or 0) for p in payments_in_period)
        closing_balance = opening_balance + new_charges - payments_rcvd

        # Aging summary
        outstanding = db.query(Invoice).filter(
            Invoice.client_id == client_id,
            Invoice.organization_id == org_id,
            Invoice.status.in_(['sent', 'overdue', 'partial']),
        ).all()
        aging = {'current': 0.0, 'days_1_30': 0.0, 'days_31_60': 0.0,
                 'days_61_90': 0.0, 'days_90_plus': 0.0, 'total': 0.0}
        for inv in outstanding:
            bal = float(inv.balance_due or 0)
            if bal <= 0:
                continue
            bucket = inv.aging_bucket
            col = {'current': 'current', '1_30': 'days_1_30', '31_60': 'days_31_60',
                   '61_90': 'days_61_90', '90_plus': 'days_90_plus'}.get(bucket, 'current')
            aging[col] += bal
            aging['total'] += bal

        from models.settings import OrganizationSettings
        settings = OrganizationSettings.get_or_create(db, org_id)

        ctx = dict(
            client=client, start_date=start_date, end_date=end_date,
            invoices=invoices_in_period, payments=payments_in_period,
            opening_balance=opening_balance, new_charges=new_charges,
            payments_received=payments_rcvd, closing_balance=closing_balance,
            aging=aging, today=today, settings=settings,
            active_page='clients', user=current_user, divisions=get_divisions(),
        )

        fmt = request.args.get('format', 'html')
        if fmt == 'pdf':
            html_content = render_template('clients/statement.html', **ctx, print_mode=True)
            try:
                from weasyprint import HTML as WPHtml
                pdf_bytes = WPHtml(string=html_content).write_pdf()
                return Response(
                    pdf_bytes, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="statement_{client_id}_{end_str}.pdf"'},
                )
            except ImportError:
                flash('PDF generation requires WeasyPrint. Install with: pip install weasyprint', 'warning')

        return render_template('clients/statement.html', **ctx, print_mode=False)
    finally:
        db.close()


@clients_bp.route('/clients/<int:client_id>/statement/email', methods=['POST'])
@login_required
def email_statement(client_id):
    """Email statement to client (placeholder — requires email utility)."""
    db = get_session()
    try:
        client = db.query(Client).filter_by(
            id=client_id, organization_id=current_user.organization_id
        ).first()
        if not client:
            return jsonify({'error': 'Client not found'}), 404

        billing_email = client.billing_email or client.email
        if not billing_email:
            return jsonify({'error': 'No billing email on file for this client.'}), 400

        # Email sending would go here — placeholder response
        return jsonify({
            'success': True,
            'sent_to': billing_email,
            'message': 'Statement email queued (email service not yet configured).',
        })
    finally:
        db.close()


# ========== Client API ==========

@clients_bp.route('/api/clients/new', methods=['POST'])
@login_required
def create_client_full():
    """Create a client + property from the full-page form."""
    db = get_session()
    try:
        # Build client
        client = Client(
            organization_id=current_user.organization_id,
            client_type=request.form.get('client_type', 'commercial'),
            company_name=request.form.get('company_name') or None,
            first_name=request.form.get('first_name') or None,
            last_name=request.form.get('last_name') or None,
            email=request.form.get('email') or None,
            phone=request.form.get('phone') or None,
            notes=request.form.get('title_prefix') or None,
        )

        # Billing address
        billing_same = request.form.get('billing_same') == 'on'
        if billing_same:
            client.billing_address = request.form.get('street1', '')
            street2 = request.form.get('street2', '')
            if street2:
                client.billing_address += ', ' + street2
            client.billing_city = request.form.get('city') or None
            client.billing_province = request.form.get('province', 'Ontario')
            client.billing_postal_code = request.form.get('postal_code') or None
        else:
            client.billing_address = request.form.get('billing_street1', '')
            billing_street2 = request.form.get('billing_street2', '')
            if billing_street2:
                client.billing_address += ', ' + billing_street2
            client.billing_city = request.form.get('billing_city') or None
            client.billing_province = request.form.get('billing_province', 'Ontario')
            client.billing_postal_code = request.form.get('billing_postal_code') or None

        db.add(client)
        db.flush()

        # Build property
        street1 = request.form.get('street1', '').strip()
        if street1:
            address = street1
            street2 = request.form.get('street2', '').strip()
            if street2:
                address += ', ' + street2

            # Custom property fields stored as structured text in notes
            custom_fields = []
            for label, key in [
                ('Billing Dept Contact', 'billing_dept_contact'),
                ('Site Super', 'site_super'),
                ('Buzzer Code', 'buzzer_code'),
                ('Property Owner', 'property_owner'),
                ('Property Manager', 'property_manager'),
            ]:
                val = request.form.get(key, '').strip()
                if val:
                    custom_fields.append(f"{label}: {val}")
            prop_notes = '\n'.join(custom_fields) if custom_fields else None

            prop = Property(
                client_id=client.id,
                name=request.form.get('company_name') or f"{request.form.get('first_name', '')} {request.form.get('last_name', '')}".strip(),
                address=address,
                city=request.form.get('city') or None,
                province=request.form.get('province', 'Ontario'),
                postal_code=request.form.get('postal_code') or None,
                property_type=request.form.get('client_type', 'commercial'),
                notes=prop_notes,
            )
            db.add(prop)

        db.commit()

        if request.form.get('action') == 'save_and_new':
            flash('Client created successfully.', 'success')
            return redirect(url_for('clients_bp.client_new_page'))

        return redirect(url_for('clients_bp.client_detail', client_id=client.id))
    except Exception as e:
        db.rollback()
        flash(f'Error creating client: {e}', 'error')
        return redirect(url_for('clients_bp.client_new_page'))
    finally:
        db.close()


@clients_bp.route('/api/clients', methods=['POST'])
@login_required
def create_client():
    from web.utils.validation import validate, ClientCreateSchema
    data = request.get_json()
    obj, err = validate(ClientCreateSchema, data or {})
    if err:
        return jsonify(err), 400
    db = get_session()
    try:
        client = Client(
            organization_id=current_user.organization_id,
            client_type=obj.client_type,
            company_name=obj.company_name,
            first_name=obj.first_name,
            last_name=obj.last_name,
            email=obj.email,
            phone=obj.phone,
            billing_address=obj.billing_address,
            billing_city=obj.billing_city,
            billing_province=obj.billing_province,
            billing_postal_code=obj.billing_postal_code,
            notes=obj.notes,
        )
        db.add(client)
        db.commit()
        return jsonify({'success': True, 'client': client.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()


@clients_bp.route('/api/clients/<int:client_id>/properties', methods=['POST'])
@login_required
def add_property(client_id):
    from web.utils.validation import validate, PropertyCreateSchema
    data = request.get_json()
    obj, err = validate(PropertyCreateSchema, data or {})
    if err:
        return jsonify(err), 400
    db = get_session()
    try:
        client = db.query(Client).filter_by(id=client_id, organization_id=current_user.organization_id).first()
        if not client:
            return jsonify({'success': False, 'error': 'Client not found'}), 404
        prop = Property(
            client_id=client_id,
            name=obj.name,
            address=obj.address,
            city=obj.city,
            province=obj.province,
            postal_code=obj.postal_code,
            unit_number=obj.unit_number,
            property_type=obj.property_type,
            notes=obj.notes,
        )
        db.add(prop)
        db.commit()
        return jsonify({'success': True, 'property': prop.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()


# ========== CLIENT NOTES ==========

@clients_bp.route('/api/clients/<int:client_id>/notes', methods=['POST'])
@login_required
def create_client_note(client_id):
    data = request.get_json()
    db = get_session()
    try:
        note = ClientNote(
            client_id=client_id,
            user_id=current_user.id,
            content=data['content'],
        )
        db.add(note)
        db.commit()
        nd = note.to_dict()
        nd['author_name'] = current_user.full_name
        nd['author_initials'] = (
            current_user.first_name[0] + (current_user.last_name[0] if current_user.last_name else '')
        ).upper() if current_user.first_name else '?'
        return jsonify({'success': True, 'note': nd})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()


@clients_bp.route('/api/clients/<int:client_id>/notes/<int:note_id>/star', methods=['PUT'])
@login_required
def toggle_note_star(client_id, note_id):
    db = get_session()
    try:
        client = db.query(Client).filter_by(id=client_id, organization_id=current_user.organization_id).first()
        if not client:
            return jsonify({'success': False, 'error': 'Client not found'}), 404
        note = db.query(ClientNote).filter_by(id=note_id, client_id=client_id).first()
        if not note:
            return jsonify({'success': False, 'error': 'Note not found'}), 404
        note.is_starred = not note.is_starred
        db.commit()
        return jsonify({'success': True, 'is_starred': note.is_starred})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()


@clients_bp.route('/api/clients/<int:client_id>/notes/<int:note_id>', methods=['DELETE'])
@login_required
def delete_client_note(client_id, note_id):
    db = get_session()
    try:
        client = db.query(Client).filter_by(id=client_id, organization_id=current_user.organization_id).first()
        if not client:
            return jsonify({'success': False, 'error': 'Client not found'}), 404
        note = db.query(ClientNote).filter_by(id=note_id, client_id=client_id).first()
        if not note:
            return jsonify({'success': False, 'error': 'Note not found'}), 404
        db.delete(note)
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()


# ========== CLIENT COMMUNICATIONS ==========

@clients_bp.route('/api/clients/<int:client_id>/communications', methods=['POST'])
@login_required
def log_communication(client_id):
    data = request.get_json()
    db = get_session()
    try:
        comm = ClientCommunication(
            client_id=client_id,
            user_id=current_user.id,
            comm_type=data.get('comm_type', 'email'),
            direction=data.get('direction', 'outbound'),
            subject=data.get('subject'),
            body=data.get('body'),
            recipient_email=data.get('recipient_email'),
            status=data.get('status', 'sent'),
            related_job_id=data.get('related_job_id'),
            related_invoice_id=data.get('related_invoice_id'),
            sent_at=datetime.now(timezone.utc) if data.get('status') != 'draft' else None,
        )
        db.add(comm)
        db.commit()
        cd = comm.to_dict()
        cd['author_name'] = current_user.full_name
        return jsonify({'success': True, 'communication': cd})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        db.close()
