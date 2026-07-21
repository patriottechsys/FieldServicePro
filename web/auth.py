"""Authentication routes."""

import os
import secrets
from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    User, Organization, Division, get_session,
    Client, Property, ClientContact, ClientNote, ClientCommunication,
    Job, JobNote, Quote, QuoteItem,
    Invoice, InvoiceItem, Technician, Payment,
)

auth_bp = Blueprint('auth', __name__)

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'


@login_manager.user_loader
def load_user(user_id):
    db_session = get_session()
    try:
        return db_session.query(User).filter_by(id=int(user_id)).first()
    finally:
        db_session.close()


def generate_token():
    return secrets.token_urlsafe(32)


def role_required(*roles):
    """
    Decorator: restrict route to users with one of the given roles.
    Usage: @role_required('owner', 'admin')
    Must be placed AFTER @login_required in decorator stack.
    """
    from functools import wraps
    from flask import abort
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to continue.', 'warning')
                return redirect(url_for('auth.login'))
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)

        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return render_template('auth/login.html')

        db_session = get_session()
        try:
            user = db_session.query(User).filter_by(email=email).first()

            if not user or not user.check_password(password):
                flash('Invalid email or password.', 'error')
                return render_template('auth/login.html')

            if not user.is_active:
                flash('Your account has been deactivated.', 'error')
                return render_template('auth/login.html')

            user.last_login = datetime.now(timezone.utc)
            db_session.commit()
            login_user(user, remember=remember)

            next_page = request.args.get('next')
            if next_page and ('://' in next_page or next_page.startswith('//')):
                next_page = None
            return redirect(next_page or url_for('dashboard'))
        finally:
            db_session.close()

    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        company_name = request.form.get('company_name', '').strip()

        errors = []
        if not email:
            errors.append('Email is required.')
        if not password:
            errors.append('Password is required.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if password != confirm_password:
            errors.append('Passwords do not match.')
        if not first_name:
            errors.append('First name is required.')
        if not company_name:
            errors.append('Company name is required.')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('auth/register.html')

        db_session = get_session()
        try:
            existing = db_session.query(User).filter_by(email=email).first()
            if existing:
                flash('An account with this email already exists.', 'error')
                return render_template('auth/register.html')

            org = Organization(name=company_name)
            db_session.add(org)
            db_session.flush()

            # Seed default divisions
            defaults = [
                Division(organization_id=org.id, name='Plumbing', code='PLB', color='#2563eb', icon='bi-droplet-fill', sort_order=1),
                Division(organization_id=org.id, name='HVAC', code='HVAC', color='#059669', icon='bi-thermometer-half', sort_order=2),
                Division(organization_id=org.id, name='Electrical', code='ELEC', color='#f59e0b', icon='bi-lightning-fill', sort_order=3),
                Division(organization_id=org.id, name='General Contracting', code='GC', color='#8b5cf6', icon='bi-hammer', sort_order=4),
            ]
            db_session.add_all(defaults)

            user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                organization_id=org.id,
                role='owner',
                verification_token=generate_token(),
            )
            user.set_password(password)
            db_session.add(user)
            db_session.commit()

            login_user(user)
            flash('Account created! Welcome to FieldServicePro.', 'success')
            return redirect(url_for('dashboard'))

        except Exception:
            db_session.rollback()
            flash('An error occurred. Please try again.', 'error')
            return render_template('auth/register.html')
        finally:
            db_session.close()

    return render_template('auth/register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if email:
            db_session = get_session()
            try:
                user = db_session.query(User).filter_by(email=email).first()
                if user:
                    user.reset_token = generate_token()
                    user.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=24)
                    db_session.commit()
            finally:
                db_session.close()

        flash('If an account exists with this email, you will receive a password reset link.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/demo')
def demo():
    """Create a demo account pre-loaded with realistic FieldServicePro data."""
    import web.app as app_module
    if getattr(app_module, 'IS_PRODUCTION', False):
        return ('Demo is not available in production.', 404)
    if current_user.is_authenticated:
        logout_user()

    db = get_session()
    try:
        # Check if demo account already exists — reset on ?reset=1&token=<DEMO_RESET_TOKEN>
        demo_user = db.query(User).filter_by(email='demo@fieldservicepro.app').first()
        # Reset is only honored when the caller supplies the operator-only token.
        # Without a valid token, fall through to the "log in to existing demo" path.
        expected_token = os.environ.get('DEMO_RESET_TOKEN')
        provided_token = request.args.get('token')
        reset_requested = request.args.get('reset') == '1'
        reset_authorized = bool(expected_token) and provided_token == expected_token
        if demo_user and not (reset_requested and reset_authorized):
            login_user(demo_user)
            flash('Welcome back to the demo!', 'success')
            return redirect(url_for('dashboard'))
        elif demo_user:
            # Wipe old demo org cascade
            org_id = demo_user.organization_id
            db.query(Payment).filter(Payment.invoice_id.in_(
                db.query(Invoice.id).filter_by(organization_id=org_id)
            )).delete(synchronize_session=False)
            db.query(InvoiceItem).filter(InvoiceItem.invoice_id.in_(
                db.query(Invoice.id).filter_by(organization_id=org_id)
            )).delete(synchronize_session=False)
            db.query(Invoice).filter_by(organization_id=org_id).delete()
            db.query(QuoteItem).filter(QuoteItem.quote_id.in_(
                db.query(Quote.id).filter_by(organization_id=org_id)
            )).delete(synchronize_session=False)
            db.query(Quote).filter_by(organization_id=org_id).delete()
            db.query(JobNote).filter(JobNote.job_id.in_(
                db.query(Job.id).filter_by(organization_id=org_id)
            )).delete(synchronize_session=False)
            db.query(Job).filter_by(organization_id=org_id).delete()
            db.query(ClientCommunication).filter(ClientCommunication.client_id.in_(
                db.query(Client.id).filter_by(organization_id=org_id)
            )).delete(synchronize_session=False)
            db.query(ClientNote).filter(ClientNote.client_id.in_(
                db.query(Client.id).filter_by(organization_id=org_id)
            )).delete(synchronize_session=False)
            db.query(ClientContact).filter(ClientContact.client_id.in_(
                db.query(Client.id).filter_by(organization_id=org_id)
            )).delete(synchronize_session=False)
            db.query(Property).filter(Property.client_id.in_(
                db.query(Client.id).filter_by(organization_id=org_id)
            )).delete(synchronize_session=False)
            db.query(Client).filter_by(organization_id=org_id).delete()
            db.query(Technician).filter_by(organization_id=org_id).delete()
            db.query(Division).filter_by(organization_id=org_id).delete()
            db.query(User).filter_by(organization_id=org_id).delete()
            db.query(Organization).filter_by(id=org_id).delete()
            db.commit()

        # --- Create org ---
        org = Organization(
            name='Demo Field Service Co.',
            phone='(519) 555-0100',
            email='demo@fieldservicepro.app',
            city='Kitchener',
            province='Ontario',
            postal_code='N2G 1A1',
        )
        db.add(org)
        db.flush()

        # --- Divisions ---
        div_plb = Division(organization_id=org.id, name='Plumbing', code='PLB', color='#2563eb', icon='bi-droplet-fill', sort_order=1)
        div_hvac = Division(organization_id=org.id, name='HVAC', code='HVAC', color='#059669', icon='bi-thermometer-half', sort_order=2)
        div_elec = Division(organization_id=org.id, name='Electrical', code='ELEC', color='#f59e0b', icon='bi-lightning-fill', sort_order=3)
        div_gc = Division(organization_id=org.id, name='General Contracting', code='GC', color='#8b5cf6', icon='bi-hammer', sort_order=4)
        db.add_all([div_plb, div_hvac, div_elec, div_gc])
        db.flush()

        # --- Demo user ---
        user = User(
            email='demo@fieldservicepro.app',
            first_name='Ricky',
            last_name='F.',
            organization_id=org.id,
            role='owner',
        )
        user.set_password('demo1234')
        db.add(user)
        db.flush()

        # --- Technicians ---
        techs = [
            Technician(organization_id=org.id, division_id=div_plb.id, first_name='Dave', last_name='Morrison', phone='(519) 555-0201', mobile='(519) 555-0201', color='#2563eb', hourly_rate=85),
            Technician(organization_id=org.id, division_id=div_plb.id, first_name='Ryan', last_name='Patel', phone='(519) 555-0202', mobile='(519) 555-0202', color='#3b82f6', hourly_rate=75),
            Technician(organization_id=org.id, division_id=div_hvac.id, first_name='Mike', last_name='Chen', phone='(519) 555-0203', mobile='(519) 555-0203', color='#059669', hourly_rate=90),
            Technician(organization_id=org.id, division_id=div_hvac.id, first_name='James', last_name='Wilson', phone='(519) 555-0204', mobile='(519) 555-0204', color='#10b981', hourly_rate=80),
            Technician(organization_id=org.id, division_id=div_elec.id, first_name='Sarah', last_name='Thompson', phone='(519) 555-0205', mobile='(519) 555-0205', color='#f59e0b', hourly_rate=95),
            Technician(organization_id=org.id, division_id=div_gc.id, first_name='Carlos', last_name='Rivera', phone='(519) 555-0206', mobile='(519) 555-0206', color='#8b5cf6', hourly_rate=70),
            Technician(organization_id=org.id, division_id=div_plb.id, first_name='Alex', last_name='Nguyen', phone='(519) 555-0207', mobile='(519) 555-0207', color='#1d4ed8', hourly_rate=78),
            Technician(organization_id=org.id, division_id=div_hvac.id, first_name='Jordan', last_name='Blake', phone='(519) 555-0208', mobile='(519) 555-0208', color='#047857', hourly_rate=82),
            Technician(organization_id=org.id, division_id=div_elec.id, first_name='Marc', last_name='Lee', phone='(519) 555-0209', mobile='(519) 555-0209', color='#d97706', hourly_rate=88),
            Technician(organization_id=org.id, division_id=div_gc.id, first_name='Tyler', last_name='Brandt', phone='(519) 555-0210', mobile='(519) 555-0210', color='#7c3aed', hourly_rate=72),
        ]
        db.add_all(techs)
        db.flush()

        # --- Clients (seed data) ---
        clients_data = [
            {'type': 'commercial', 'company': 'Kingsley Management Inc.', 'first': 'Andrea', 'last': 'Kingsley', 'email': 'andrea@kingsleymgmt.ca', 'phone': '(519) 555-1001', 'city': 'Kitchener'},
            {'type': 'commercial', 'company': 'Centurion Property Management', 'first': 'Brian', 'last': 'Holtz', 'email': 'bholtz@centurionpm.ca', 'phone': '(519) 555-1002', 'city': 'Waterloo'},
            {'type': 'commercial', 'company': 'CMC Condo Management', 'first': 'Lisa', 'last': 'Park', 'email': 'lpark@cmccondo.ca', 'phone': '(519) 555-1003', 'city': 'Cambridge'},
            {'type': 'commercial', 'company': 'Winmar Property Restoration', 'first': 'Derek', 'last': 'Foster', 'email': 'dfoster@winmar.ca', 'phone': '(519) 555-1004', 'city': 'Guelph'},
            {'type': 'commercial', 'company': 'Terra Corp Developments', 'first': 'Nina', 'last': 'Sharma', 'email': 'nsharma@terracorp.ca', 'phone': '(519) 555-1005', 'city': 'Kitchener'},
            {'type': 'residential', 'company': None, 'first': 'John', 'last': 'McTavish', 'email': 'jmctavish@gmail.com', 'phone': '(519) 555-2001', 'city': 'Waterloo'},
            {'type': 'residential', 'company': None, 'first': 'Priya', 'last': 'Desai', 'email': 'priya.desai@outlook.com', 'phone': '(519) 555-2002', 'city': 'Kitchener'},
            {'type': 'residential', 'company': None, 'first': 'Tom', 'last': 'Brewster', 'email': 'tbrewster@rogers.com', 'phone': '(519) 555-2003', 'city': 'Cambridge'},
            {'type': 'residential', 'company': None, 'first': 'Emily', 'last': 'Fung', 'email': 'efung@bell.net', 'phone': '(519) 555-2004', 'city': 'Guelph'},
            {'type': 'commercial', 'company': 'Grand River Housing Corp', 'first': 'Mark', 'last': 'Baxter', 'email': 'mbaxter@grhc.ca', 'phone': '(519) 555-1006', 'city': 'Kitchener'},
            # --- Additional clients ---
            {'type': 'commercial', 'company': 'Conestoga College Facilities', 'first': 'Janice', 'last': 'Wu', 'email': 'jwu@conestogac.on.ca', 'phone': '(519) 555-1007', 'city': 'Kitchener'},
            {'type': 'commercial', 'company': 'Schlegel Villages Inc.', 'first': 'Robert', 'last': 'Doherty', 'email': 'rdoherty@schlegelvillages.com', 'phone': '(519) 555-1008', 'city': 'Waterloo'},
            {'type': 'commercial', 'company': 'Perimeter Development Corp', 'first': 'Samantha', 'last': 'Giles', 'email': 'sgiles@perimeterdev.ca', 'phone': '(519) 555-1009', 'city': 'Cambridge'},
            {'type': 'commercial', 'company': 'KW Property Management Group', 'first': 'Victor', 'last': 'Tran', 'email': 'vtran@kwpmg.ca', 'phone': '(519) 555-1010', 'city': 'Kitchener'},
            {'type': 'commercial', 'company': 'Catalyst137', 'first': 'Heather', 'last': 'Flynn', 'email': 'hflynn@catalyst137.com', 'phone': '(519) 555-1011', 'city': 'Kitchener'},
            {'type': 'residential', 'company': None, 'first': 'Greg', 'last': 'Muller', 'email': 'gmuller@gmail.com', 'phone': '(519) 555-2005', 'city': 'Waterloo'},
            {'type': 'residential', 'company': None, 'first': 'Sandra', 'last': 'Kim', 'email': 'skim@outlook.com', 'phone': '(519) 555-2006', 'city': 'Kitchener'},
            {'type': 'residential', 'company': None, 'first': 'Michael', 'last': 'O\'Brien', 'email': 'mobrien@rogers.com', 'phone': '(519) 555-2007', 'city': 'Cambridge'},
            {'type': 'residential', 'company': None, 'first': 'Angela', 'last': 'Petrova', 'email': 'apetrova@bell.net', 'phone': '(519) 555-2008', 'city': 'Guelph'},
            {'type': 'residential', 'company': None, 'first': 'David', 'last': 'Henderson', 'email': 'dhenderson@gmail.com', 'phone': '(519) 555-2009', 'city': 'Kitchener'},
        ]
        client_objs = []
        for c in clients_data:
            client = Client(
                organization_id=org.id, client_type=c['type'], company_name=c['company'],
                first_name=c['first'], last_name=c['last'], email=c['email'],
                phone=c['phone'], billing_city=c['city'], billing_province='Ontario',
            )
            db.add(client)
            client_objs.append(client)
        db.flush()

        # --- Properties (for commercial clients) ---
        properties_data = [
            (0, [  # Kingsley
                {'name': 'Kingsley Tower A', 'address': '100 King St W', 'city': 'Kitchener', 'type': 'condo'},
                {'name': 'Kingsley Tower B', 'address': '102 King St W', 'city': 'Kitchener', 'type': 'condo'},
                {'name': 'Victoria Park Residences', 'address': '45 Victoria St S', 'city': 'Kitchener', 'type': 'commercial'},
            ]),
            (1, [  # Centurion
                {'name': 'Bridgeport Lofts', 'address': '200 Bridgeport Rd E', 'city': 'Waterloo', 'type': 'condo'},
                {'name': 'University Commons', 'address': '300 University Ave W', 'city': 'Waterloo', 'type': 'commercial'},
            ]),
            (2, [  # CMC
                {'name': 'Hespeler Heights', 'address': '50 Hespeler Rd', 'city': 'Cambridge', 'type': 'condo'},
            ]),
            (3, [  # Winmar
                {'name': 'Winmar Workshop', 'address': '15 Industrial Dr', 'city': 'Guelph', 'type': 'industrial'},
            ]),
            (4, [  # Terra Corp
                {'name': 'Terra Towers', 'address': '500 Fischer-Hallman Rd', 'city': 'Kitchener', 'type': 'commercial'},
                {'name': 'Pioneer Park Homes', 'address': '88 Pioneer Dr', 'city': 'Kitchener', 'type': 'residential'},
            ]),
            (9, [  # Grand River Housing
                {'name': 'GRHC Building 1', 'address': '75 Queen St N', 'city': 'Kitchener', 'type': 'commercial'},
                {'name': 'GRHC Building 2', 'address': '77 Queen St N', 'city': 'Kitchener', 'type': 'commercial'},
            ]),
            (10, [  # Conestoga College
                {'name': 'Doon Campus — Main Building', 'address': '299 Doon Valley Dr', 'city': 'Kitchener', 'type': 'commercial'},
                {'name': 'Doon Campus — Trades Wing', 'address': '299 Doon Valley Dr, Bldg B', 'city': 'Kitchener', 'type': 'commercial'},
                {'name': 'Waterloo Campus', 'address': '108 University Ave E', 'city': 'Waterloo', 'type': 'commercial'},
            ]),
            (11, [  # Schlegel Villages
                {'name': 'Winston Park Retirement', 'address': '695 Block Line Rd', 'city': 'Kitchener', 'type': 'commercial'},
                {'name': 'The Village at University Gates', 'address': '250 Laurelwood Dr', 'city': 'Waterloo', 'type': 'commercial'},
            ]),
            (12, [  # Perimeter Development
                {'name': 'Eagle Landing Condos', 'address': '330 Phillip St', 'city': 'Waterloo', 'type': 'condo'},
                {'name': 'Grand Flats Phase 1', 'address': '12 Brewers Lane', 'city': 'Cambridge', 'type': 'condo'},
                {'name': 'Grand Flats Phase 2', 'address': '14 Brewers Lane', 'city': 'Cambridge', 'type': 'condo'},
            ]),
            (13, [  # KW Property Management
                {'name': 'Weber Place', 'address': '440 Weber St N', 'city': 'Waterloo', 'type': 'commercial'},
                {'name': 'Frederick Mall Office', 'address': '385 Frederick St', 'city': 'Kitchener', 'type': 'commercial'},
                {'name': 'Belmont Village Retail', 'address': '15 Belmont Ave W', 'city': 'Kitchener', 'type': 'commercial'},
            ]),
            (14, [  # Catalyst137
                {'name': 'Catalyst137 Main', 'address': '137 Glasgow St N', 'city': 'Kitchener', 'type': 'industrial'},
            ]),
        ]
        prop_objs = {}
        for client_idx, props in properties_data:
            prop_objs[client_idx] = []
            for p in props:
                prop = Property(
                    client_id=client_objs[client_idx].id, name=p['name'],
                    address=p['address'], city=p['city'], province='Ontario',
                    property_type=p['type'],
                )
                db.add(prop)
                prop_objs[client_idx].append(prop)
        db.flush()

        # --- Jobs (realistic mix of statuses) ---
        now = datetime.now(timezone.utc)
        jobs_data = [
            # Plumbing jobs
            {'div': div_plb.id, 'client': 0, 'prop_idx': 0, 'tech': 0, 'title': 'Backflow preventer annual test — Tower A', 'type': 'inspection', 'status': 'completed', 'est': 450, 'actual': 450, 'sched': now - timedelta(days=5), 'completed': now - timedelta(days=5)},
            {'div': div_plb.id, 'client': 0, 'prop_idx': 1, 'tech': 0, 'title': 'Kitchen stack repair — Unit 1204', 'type': 'repair', 'status': 'in_progress', 'est': 1800, 'actual': 0, 'sched': now - timedelta(hours=3), 'completed': None},
            {'div': div_plb.id, 'client': 1, 'prop_idx': 0, 'tech': 1, 'title': 'Water softener installation — Bridgeport Lofts', 'type': 'installation', 'status': 'scheduled', 'est': 2200, 'actual': 0, 'sched': now + timedelta(days=1), 'completed': None},
            {'div': div_plb.id, 'client': 5, 'prop_idx': None, 'tech': 1, 'title': 'Leaking basement pipe', 'type': 'emergency', 'status': 'scheduled', 'est': 600, 'actual': 0, 'sched': now + timedelta(hours=4), 'completed': None},
            {'div': div_plb.id, 'client': 2, 'prop_idx': 0, 'tech': 0, 'title': 'Curb stop assessment Phase 1', 'type': 'inspection', 'status': 'completed', 'est': 850, 'actual': 850, 'sched': now - timedelta(days=12), 'completed': now - timedelta(days=12)},
            {'div': div_plb.id, 'client': 2, 'prop_idx': 0, 'tech': 0, 'title': 'Curb stop assessment Phase 2', 'type': 'inspection', 'status': 'completed', 'est': 1200, 'actual': 1200, 'sched': now - timedelta(days=8), 'completed': now - timedelta(days=8)},
            {'div': div_plb.id, 'client': 6, 'prop_idx': None, 'tech': 1, 'title': 'Hot water tank replacement', 'type': 'installation', 'status': 'invoiced', 'est': 3500, 'actual': 3650, 'sched': now - timedelta(days=15), 'completed': now - timedelta(days=14)},
            {'div': div_plb.id, 'client': 4, 'prop_idx': 0, 'tech': 0, 'title': 'Drinking fountain install — lobby', 'type': 'installation', 'status': 'scheduled', 'est': 1500, 'actual': 0, 'sched': now + timedelta(days=3), 'completed': None},
            # HVAC jobs
            {'div': div_hvac.id, 'client': 0, 'prop_idx': 2, 'tech': 2, 'title': 'Boiler annual service — Victoria Park', 'type': 'maintenance', 'status': 'completed', 'est': 750, 'actual': 750, 'sched': now - timedelta(days=3), 'completed': now - timedelta(days=3)},
            {'div': div_hvac.id, 'client': 1, 'prop_idx': 1, 'tech': 2, 'title': 'RTU replacement — University Commons roof', 'type': 'installation', 'status': 'in_progress', 'est': 12500, 'actual': 0, 'sched': now - timedelta(days=1), 'completed': None},
            {'div': div_hvac.id, 'client': 7, 'prop_idx': None, 'tech': 3, 'title': 'Furnace not heating — emergency', 'type': 'emergency', 'status': 'completed', 'est': 400, 'actual': 525, 'sched': now - timedelta(days=2), 'completed': now - timedelta(days=2)},
            {'div': div_hvac.id, 'client': 4, 'prop_idx': 1, 'tech': 3, 'title': 'Hydronic heating system — Pioneer Park', 'type': 'installation', 'status': 'scheduled', 'est': 8500, 'actual': 0, 'sched': now + timedelta(days=5), 'completed': None},
            {'div': div_hvac.id, 'client': 9, 'prop_idx': 0, 'tech': 2, 'title': 'HVAC duct cleaning — GRHC Bldg 1', 'type': 'maintenance', 'status': 'scheduled', 'est': 2800, 'actual': 0, 'sched': now + timedelta(days=2), 'completed': None},
            # Electrical jobs
            {'div': div_elec.id, 'client': 0, 'prop_idx': 0, 'tech': 4, 'title': 'Panel upgrade 100A to 200A — Tower A', 'type': 'installation', 'status': 'completed', 'est': 4200, 'actual': 4200, 'sched': now - timedelta(days=7), 'completed': now - timedelta(days=6)},
            {'div': div_elec.id, 'client': 3, 'prop_idx': 0, 'tech': 4, 'title': 'Emergency lighting inspection', 'type': 'inspection', 'status': 'completed', 'est': 650, 'actual': 650, 'sched': now - timedelta(days=4), 'completed': now - timedelta(days=4)},
            {'div': div_elec.id, 'client': 8, 'prop_idx': None, 'tech': 4, 'title': 'EV charger installation — residential', 'type': 'installation', 'status': 'scheduled', 'est': 2800, 'actual': 0, 'sched': now + timedelta(days=4), 'completed': None},
            {'div': div_elec.id, 'client': 9, 'prop_idx': 1, 'tech': 4, 'title': 'Parking lot lighting retrofit — LED', 'type': 'installation', 'status': 'draft', 'est': 6500, 'actual': 0, 'sched': None, 'completed': None},
            # GC jobs
            {'div': div_gc.id, 'client': 3, 'prop_idx': 0, 'tech': 5, 'title': 'Washroom renovation — Winmar Workshop', 'type': 'installation', 'status': 'in_progress', 'est': 15000, 'actual': 0, 'sched': now - timedelta(days=10), 'completed': None},
            {'div': div_gc.id, 'client': 4, 'prop_idx': 0, 'tech': 5, 'title': 'Lobby drywall + paint — Terra Towers', 'type': 'repair', 'status': 'completed', 'est': 3200, 'actual': 3400, 'sched': now - timedelta(days=20), 'completed': now - timedelta(days=18)},
            {'div': div_gc.id, 'client': 9, 'prop_idx': 0, 'tech': 5, 'title': 'Accessibility ramp build — GRHC', 'type': 'installation', 'status': 'scheduled', 'est': 7500, 'actual': 0, 'sched': now + timedelta(days=7), 'completed': None},
            # === ADDITIONAL JOBS — Conestoga College ===
            {'div': div_plb.id, 'client': 10, 'prop_idx': 0, 'tech': 0, 'title': 'Washroom fixture replacement — Main Bldg 3rd floor', 'type': 'repair', 'status': 'completed', 'est': 2400, 'actual': 2350, 'sched': now - timedelta(days=9), 'completed': now - timedelta(days=8)},
            {'div': div_plb.id, 'client': 10, 'prop_idx': 1, 'tech': 6, 'title': 'Backflow preventer test — Trades Wing', 'type': 'inspection', 'status': 'completed', 'est': 375, 'actual': 375, 'sched': now - timedelta(days=6), 'completed': now - timedelta(days=6)},
            {'div': div_hvac.id, 'client': 10, 'prop_idx': 0, 'tech': 2, 'title': 'Rooftop unit seasonal startup — Main Bldg', 'type': 'maintenance', 'status': 'scheduled', 'est': 1800, 'actual': 0, 'sched': now + timedelta(days=2), 'completed': None},
            {'div': div_elec.id, 'client': 10, 'prop_idx': 2, 'tech': 8, 'title': 'Emergency exit sign replacement — Waterloo Campus', 'type': 'repair', 'status': 'completed', 'est': 950, 'actual': 920, 'sched': now - timedelta(days=4), 'completed': now - timedelta(days=4)},
            # === Schlegel Villages ===
            {'div': div_plb.id, 'client': 11, 'prop_idx': 0, 'tech': 1, 'title': 'Hot water recirculation pump — Winston Park', 'type': 'repair', 'status': 'completed', 'est': 1650, 'actual': 1700, 'sched': now - timedelta(days=11), 'completed': now - timedelta(days=10)},
            {'div': div_hvac.id, 'client': 11, 'prop_idx': 0, 'tech': 7, 'title': 'Boiler maintenance — Winston Park', 'type': 'maintenance', 'status': 'completed', 'est': 900, 'actual': 900, 'sched': now - timedelta(days=7), 'completed': now - timedelta(days=7)},
            {'div': div_hvac.id, 'client': 11, 'prop_idx': 1, 'tech': 2, 'title': 'AC unit not cooling — Village at U Gates rm 204', 'type': 'emergency', 'status': 'in_progress', 'est': 550, 'actual': 0, 'sched': now - timedelta(hours=5), 'completed': None},
            {'div': div_elec.id, 'client': 11, 'prop_idx': 1, 'tech': 4, 'title': 'Generator transfer switch test — U Gates', 'type': 'inspection', 'status': 'scheduled', 'est': 1200, 'actual': 0, 'sched': now + timedelta(days=3), 'completed': None},
            {'div': div_gc.id, 'client': 11, 'prop_idx': 0, 'tech': 9, 'title': 'Dining hall ceiling tile replacement', 'type': 'repair', 'status': 'completed', 'est': 2800, 'actual': 2650, 'sched': now - timedelta(days=14), 'completed': now - timedelta(days=13)},
            # === Perimeter Development ===
            {'div': div_plb.id, 'client': 12, 'prop_idx': 0, 'tech': 6, 'title': 'Sump pump install — Eagle Landing parking', 'type': 'installation', 'status': 'completed', 'est': 3200, 'actual': 3450, 'sched': now - timedelta(days=16), 'completed': now - timedelta(days=15)},
            {'div': div_plb.id, 'client': 12, 'prop_idx': 1, 'tech': 0, 'title': 'Main water shut-off valve replacement — Grand Flats P1', 'type': 'repair', 'status': 'completed', 'est': 1100, 'actual': 1100, 'sched': now - timedelta(days=13), 'completed': now - timedelta(days=13)},
            {'div': div_plb.id, 'client': 12, 'prop_idx': 2, 'tech': 1, 'title': 'Rough-in plumbing — Grand Flats P2 units 301-310', 'type': 'installation', 'status': 'in_progress', 'est': 18500, 'actual': 0, 'sched': now - timedelta(days=5), 'completed': None},
            {'div': div_hvac.id, 'client': 12, 'prop_idx': 0, 'tech': 3, 'title': 'Make-up air unit commissioning — Eagle Landing', 'type': 'installation', 'status': 'scheduled', 'est': 4200, 'actual': 0, 'sched': now + timedelta(days=6), 'completed': None},
            {'div': div_elec.id, 'client': 12, 'prop_idx': 2, 'tech': 4, 'title': 'Electrical rough-in — Grand Flats P2 units 301-310', 'type': 'installation', 'status': 'in_progress', 'est': 22000, 'actual': 0, 'sched': now - timedelta(days=4), 'completed': None},
            # === KW Property Management ===
            {'div': div_plb.id, 'client': 13, 'prop_idx': 0, 'tech': 0, 'title': 'Burst pipe repair — Weber Place 2nd floor', 'type': 'emergency', 'status': 'completed', 'est': 800, 'actual': 1150, 'sched': now - timedelta(days=3), 'completed': now - timedelta(days=3)},
            {'div': div_plb.id, 'client': 13, 'prop_idx': 1, 'tech': 6, 'title': 'Annual backflow test — Frederick Mall', 'type': 'inspection', 'status': 'completed', 'est': 450, 'actual': 450, 'sched': now - timedelta(days=18), 'completed': now - timedelta(days=18)},
            {'div': div_hvac.id, 'client': 13, 'prop_idx': 2, 'tech': 7, 'title': 'Rooftop unit replacement — Belmont Retail', 'type': 'installation', 'status': 'scheduled', 'est': 9800, 'actual': 0, 'sched': now + timedelta(days=8), 'completed': None},
            {'div': div_elec.id, 'client': 13, 'prop_idx': 0, 'tech': 8, 'title': 'Fire alarm panel upgrade — Weber Place', 'type': 'installation', 'status': 'draft', 'est': 7200, 'actual': 0, 'sched': None, 'completed': None},
            {'div': div_gc.id, 'client': 13, 'prop_idx': 1, 'tech': 5, 'title': 'Storefront glass replacement — Frederick Mall', 'type': 'repair', 'status': 'completed', 'est': 4500, 'actual': 4800, 'sched': now - timedelta(days=22), 'completed': now - timedelta(days=20)},
            # === Catalyst137 ===
            {'div': div_elec.id, 'client': 14, 'prop_idx': 0, 'tech': 4, 'title': 'High-voltage panel upgrade — Catalyst137', 'type': 'installation', 'status': 'in_progress', 'est': 14000, 'actual': 0, 'sched': now - timedelta(days=3), 'completed': None},
            {'div': div_plb.id, 'client': 14, 'prop_idx': 0, 'tech': 0, 'title': 'Industrial floor drain cleaning', 'type': 'maintenance', 'status': 'completed', 'est': 650, 'actual': 650, 'sched': now - timedelta(days=8), 'completed': now - timedelta(days=8)},
            {'div': div_gc.id, 'client': 14, 'prop_idx': 0, 'tech': 9, 'title': 'Loading dock door replacement', 'type': 'installation', 'status': 'scheduled', 'est': 5800, 'actual': 0, 'sched': now + timedelta(days=10), 'completed': None},
            # === Additional residential jobs ===
            {'div': div_plb.id, 'client': 15, 'prop_idx': None, 'tech': 1, 'title': 'Bathroom rough-in for basement reno', 'type': 'installation', 'status': 'completed', 'est': 4200, 'actual': 4500, 'sched': now - timedelta(days=19), 'completed': now - timedelta(days=17)},
            {'div': div_hvac.id, 'client': 16, 'prop_idx': None, 'tech': 3, 'title': 'Furnace replacement — high efficiency', 'type': 'installation', 'status': 'completed', 'est': 5500, 'actual': 5500, 'sched': now - timedelta(days=12), 'completed': now - timedelta(days=11)},
            {'div': div_elec.id, 'client': 17, 'prop_idx': None, 'tech': 8, 'title': 'Whole-home rewire — knob and tube removal', 'type': 'installation', 'status': 'in_progress', 'est': 12000, 'actual': 0, 'sched': now - timedelta(days=6), 'completed': None},
            {'div': div_plb.id, 'client': 18, 'prop_idx': None, 'tech': 6, 'title': 'Kitchen faucet + disposal install', 'type': 'installation', 'status': 'completed', 'est': 550, 'actual': 550, 'sched': now - timedelta(days=2), 'completed': now - timedelta(days=2)},
            {'div': div_hvac.id, 'client': 19, 'prop_idx': None, 'tech': 7, 'title': 'Ductless mini-split installation', 'type': 'installation', 'status': 'scheduled', 'est': 4800, 'actual': 0, 'sched': now + timedelta(days=5), 'completed': None},
            {'div': div_gc.id, 'client': 15, 'prop_idx': None, 'tech': 9, 'title': 'Basement framing + drywall', 'type': 'installation', 'status': 'completed', 'est': 8500, 'actual': 9200, 'sched': now - timedelta(days=25), 'completed': now - timedelta(days=20)},
            {'div': div_elec.id, 'client': 19, 'prop_idx': None, 'tech': 4, 'title': 'Panel upgrade 100A to 200A — residential', 'type': 'installation', 'status': 'scheduled', 'est': 3800, 'actual': 0, 'sched': now + timedelta(days=5), 'completed': None},
        ]
        job_objs = []
        for i, j in enumerate(jobs_data):
            prop_id = None
            if j['prop_idx'] is not None and j['client'] in prop_objs:
                props_list = prop_objs[j['client']]
                if j['prop_idx'] < len(props_list):
                    prop_id = props_list[j['prop_idx']].id

            job = Job(
                organization_id=org.id, division_id=j['div'],
                client_id=client_objs[j['client']].id, property_id=prop_id,
                job_number=f"JOB-{i+1:05d}", title=j['title'],
                job_type=j['type'], status=j['status'], priority='urgent' if j['type'] == 'emergency' else 'normal',
                estimated_amount=j['est'], actual_amount=j['actual'],
                scheduled_date=j['sched'], completed_at=j['completed'],
                started_at=j['sched'] if j['status'] in ('in_progress', 'completed', 'invoiced') else None,
                assigned_technician_id=techs[j['tech']].id, created_by_id=user.id,
            )
            db.add(job)
            job_objs.append(job)
        db.flush()

        # --- Quotes ---
        quotes_data = [
            {'div': div_plb.id, 'client': 1, 'title': 'BFP testing — all Centurion properties', 'template': 'BFP', 'status': 'sent', 'items': [('Backflow preventer test x 12 units', 12, 75), ('Report & certification', 1, 150)]},
            {'div': div_plb.id, 'client': 4, 'title': 'Water softener — Terra Towers', 'template': 'Water Softener', 'status': 'approved', 'items': [('Commercial water softener unit', 1, 3200), ('Installation labour', 8, 85), ('Piping & fittings', 1, 450)]},
            {'div': div_hvac.id, 'client': 9, 'title': 'Boiler replacement — GRHC Bldg 2', 'template': 'Boiler Service', 'status': 'draft', 'items': [('Commercial boiler unit (Navien NCB-240)', 1, 8500), ('Installation & piping', 1, 4500), ('Permits & inspection', 1, 750)]},
            {'div': div_elec.id, 'client': 0, 'title': 'EV charging stations — Tower A parking', 'template': None, 'status': 'sent', 'items': [('Level 2 EV charger x 6', 6, 1800), ('Electrical panel upgrade', 1, 3500), ('Installation labour', 40, 95), ('Permits', 1, 500)]},
            {'div': div_gc.id, 'client': 3, 'title': 'Office renovation — Winmar 2nd floor', 'template': None, 'status': 'declined', 'items': [('Demolition', 1, 2500), ('Framing & drywall', 1, 8000), ('Electrical rough-in', 1, 3500), ('Flooring', 1, 4000), ('Paint & finish', 1, 2000)]},
            {'div': div_plb.id, 'client': 2, 'title': 'Curb stop assessment Phase 3', 'template': 'Curb Stop Assessment', 'status': 'sent', 'items': [('Assessment & excavation', 1, 1800), ('Valve replacement (if needed)', 4, 350), ('Restoration', 1, 600)]},
            # Additional quotes
            {'div': div_hvac.id, 'client': 10, 'title': 'RTU replacement — Conestoga Trades Wing', 'template': None, 'status': 'approved', 'items': [('Carrier 10-ton RTU', 1, 12500), ('Crane rental', 1, 2800), ('Installation labour', 32, 90), ('Ductwork modification', 1, 1800), ('Controls & commissioning', 1, 2200)]},
            {'div': div_plb.id, 'client': 11, 'title': 'Domestic water booster pump — Winston Park', 'template': None, 'status': 'sent', 'items': [('Grundfos booster pump system', 1, 6500), ('Installation & piping', 1, 3200), ('Testing & balancing', 1, 800)]},
            {'div': div_elec.id, 'client': 12, 'title': 'EV charging — Eagle Landing parking garage (20 stalls)', 'template': None, 'status': 'draft', 'items': [('Level 2 EV charger x 20', 20, 1650), ('Electrical distribution panel', 1, 8500), ('Conduit & wiring', 20, 450), ('Labour', 80, 95), ('Permits & inspection', 1, 1200)]},
            {'div': div_gc.id, 'client': 13, 'title': 'Lobby renovation — Weber Place', 'template': None, 'status': 'sent', 'items': [('Demolition & disposal', 1, 3500), ('Framing & drywall', 1, 6000), ('Flooring — porcelain tile', 1, 4800), ('Millwork — reception desk', 1, 7500), ('Paint & finish', 1, 2200)]},
            {'div': div_plb.id, 'client': 14, 'title': 'Compressed air system — Catalyst137', 'template': None, 'status': 'approved', 'items': [('Atlas Copco compressor', 1, 9800), ('Piping & distribution', 1, 4500), ('Installation labour', 24, 85)]},
            {'div': div_hvac.id, 'client': 13, 'title': 'VRF system — Belmont Village Retail', 'template': None, 'status': 'sent', 'items': [('Mitsubishi VRF outdoor unit', 2, 8500), ('Indoor cassette units x 8', 8, 1800), ('Refrigerant piping', 1, 6500), ('Controls', 1, 3200), ('Labour', 60, 90)]},
        ]
        for i, q in enumerate(quotes_data):
            subtotal = sum(item[1] * item[2] for item in q['items'])
            tax = subtotal * 0.13
            quote = Quote(
                organization_id=org.id, division_id=q['div'],
                client_id=client_objs[q['client']].id,
                quote_number=f"QTE-{i+1:05d}", title=q['title'],
                template_name=q['template'], status=q['status'],
                subtotal=subtotal, tax_rate=13.0, tax_amount=tax, total=subtotal + tax,
                issued_date=now - timedelta(days=i * 3 + 2) if q['status'] != 'draft' else None,
                valid_until=now + timedelta(days=30 - i * 3),
                created_by_id=user.id,
            )
            db.add(quote)
            db.flush()
            for sort, item in enumerate(q['items']):
                db.add(QuoteItem(
                    quote_id=quote.id, description=item[0],
                    quantity=item[1], unit_price=item[2], total=item[1] * item[2],
                    sort_order=sort,
                ))

        # --- Invoices (from completed/invoiced jobs) ---
        invoices_data = [
            {'client': 0, 'job_idx': 0, 'total': 450, 'status': 'paid', 'days_ago': 4, 'paid': 450},
            {'client': 2, 'job_idx': 4, 'total': 850, 'status': 'paid', 'days_ago': 10, 'paid': 850},
            {'client': 2, 'job_idx': 5, 'total': 1200, 'status': 'sent', 'days_ago': 6, 'paid': 0},
            {'client': 6, 'job_idx': 6, 'total': 3650, 'status': 'overdue', 'days_ago': 14, 'paid': 0},
            {'client': 0, 'job_idx': 8, 'total': 750, 'status': 'sent', 'days_ago': 2, 'paid': 0},
            {'client': 7, 'job_idx': 10, 'total': 525, 'status': 'paid', 'days_ago': 1, 'paid': 525},
            {'client': 0, 'job_idx': 13, 'total': 4200, 'status': 'partial', 'days_ago': 5, 'paid': 2000},
            {'client': 3, 'job_idx': 14, 'total': 650, 'status': 'sent', 'days_ago': 3, 'paid': 0},
            {'client': 4, 'job_idx': 18, 'total': 3400, 'status': 'overdue', 'days_ago': 16, 'paid': 0},
            # Additional invoices for new jobs (indices match jobs_data order, 0-based)
            {'client': 10, 'job_idx': 20, 'total': 2350, 'status': 'sent', 'days_ago': 7, 'paid': 0},       # Washroom fixture
            {'client': 10, 'job_idx': 21, 'total': 375, 'status': 'paid', 'days_ago': 5, 'paid': 375},       # Backflow test Trades Wing
            {'client': 10, 'job_idx': 23, 'total': 920, 'status': 'paid', 'days_ago': 3, 'paid': 920},       # Emergency exit signs
            {'client': 11, 'job_idx': 24, 'total': 1700, 'status': 'paid', 'days_ago': 9, 'paid': 1700},     # Hot water recirc pump
            {'client': 11, 'job_idx': 25, 'total': 900, 'status': 'sent', 'days_ago': 6, 'paid': 0},         # Boiler maintenance
            {'client': 11, 'job_idx': 28, 'total': 2650, 'status': 'paid', 'days_ago': 12, 'paid': 2650},    # Dining hall ceiling
            {'client': 12, 'job_idx': 29, 'total': 3450, 'status': 'overdue', 'days_ago': 14, 'paid': 0},    # Sump pump
            {'client': 12, 'job_idx': 30, 'total': 1100, 'status': 'paid', 'days_ago': 12, 'paid': 1100},    # Water shut-off valve
            {'client': 13, 'job_idx': 34, 'total': 1150, 'status': 'sent', 'days_ago': 2, 'paid': 0},        # Burst pipe
            {'client': 13, 'job_idx': 35, 'total': 450, 'status': 'paid', 'days_ago': 17, 'paid': 450},      # Backflow Frederick Mall
            {'client': 13, 'job_idx': 38, 'total': 4800, 'status': 'partial', 'days_ago': 19, 'paid': 2400}, # Storefront glass
            {'client': 14, 'job_idx': 40, 'total': 650, 'status': 'paid', 'days_ago': 7, 'paid': 650},       # Floor drain
            {'client': 15, 'job_idx': 42, 'total': 4500, 'status': 'paid', 'days_ago': 16, 'paid': 4500},    # Bathroom rough-in
            {'client': 16, 'job_idx': 43, 'total': 5500, 'status': 'paid', 'days_ago': 10, 'paid': 5500},    # Furnace replacement
            {'client': 18, 'job_idx': 45, 'total': 550, 'status': 'sent', 'days_ago': 1, 'paid': 0},         # Kitchen faucet
            {'client': 15, 'job_idx': 47, 'total': 9200, 'status': 'partial', 'days_ago': 18, 'paid': 5000}, # Basement framing
        ]
        for i, inv in enumerate(invoices_data):
            subtotal = inv['total'] / 1.13
            tax = inv['total'] - subtotal
            invoice = Invoice(
                organization_id=org.id,
                client_id=client_objs[inv['client']].id,
                job_id=job_objs[inv['job_idx']].id,
                invoice_number=f"INV-{i+1:05d}",
                status=inv['status'],
                subtotal=round(subtotal, 2), tax_rate=13.0,
                tax_amount=round(tax, 2), total=inv['total'],
                amount_paid=inv['paid'],
                balance_due=inv['total'] - inv['paid'],
                issued_date=now - timedelta(days=inv['days_ago']),
                due_date=now - timedelta(days=inv['days_ago']) + timedelta(days=30),
                paid_date=now - timedelta(days=inv['days_ago'] - 1) if inv['status'] == 'paid' else None,
                created_by_id=user.id,
            )
            db.add(invoice)
            db.flush()

            db.add(InvoiceItem(
                invoice_id=invoice.id,
                description=job_objs[inv['job_idx']].title,
                quantity=1, unit_price=round(subtotal, 2), total=round(subtotal, 2),
            ))

            if inv['paid'] > 0:
                db.add(Payment(
                    invoice_id=invoice.id, amount=inv['paid'],
                    payment_method='e-transfer' if inv['paid'] < 1000 else 'cheque',
                    payment_date=now - timedelta(days=inv['days_ago'] - 1),
                ))

        # --- Client Notes ---
        notes_data = [
            (0, True, "Kingsley Management — all buildings keyless code 07500. Ask Andrea for unit-specific codes."),
            (0, True, "KEY LOCATION:\nTower A — Garage Code: 0901\nTower B — Key Cafe Code: 9815\nKey Cafe has keys for Tower A and Tower B lobbies."),
            (0, False, "Andrea prefers email communication. Always CC building super for Tower A jobs."),
            (1, True, "Centurion — Brian Holtz is main contact. For Bridgeport Lofts, ask for Dana Mackay (Sr. Project Manager)."),
            (1, False, "Centurion pays NET 30 via cheque. Invoice must reference PO number."),
            (2, False, "CMC — Lisa Park handles all approvals. No work without written approval via email."),
            (3, False, "Winmar — always park in visitor lot. Workshop has restricted access after 6pm."),
            (4, True, "Terra Corp — Nina Sharma is new PM as of Jan 2026. Previous contact was replaced."),
            (9, False, "GRHC — Mark Baxter is very responsive. Prefers phone calls over email for urgent items."),
            (9, False, "GRHC Building 2 boiler room access requires escort from building manager."),
            (10, True, "Conestoga College — all work needs purchase order number. Contact Janice Wu for PO. Parking pass required from security office."),
            (10, False, "Trades Wing has restricted access — must sign in at front desk and wear visitor badge."),
            (11, True, "Schlegel Villages — work in resident areas must be scheduled around meal times (7-9am, 12-1pm, 5-7pm). No loud work during quiet hours."),
            (11, False, "Winston Park — maintenance office has spare keys. Ask for Bill (building maintenance lead)."),
            (12, True, "Perimeter Dev — Grand Flats Phase 2 is active construction. Hard hats + steel toe required. Site super is Danny Ko."),
            (12, False, "Eagle Landing — condo board meets 3rd Tuesday monthly. Any common-area work over $5K needs board approval."),
            (13, True, "KW PMG — Victor Tran is very detail-oriented. Always provide photo documentation before and after work."),
            (13, False, "Frederick Mall — loading dock access only before 9am and after 6pm to avoid retail foot traffic."),
            (14, False, "Catalyst137 — high-security facility. Background check required for new techs. Lock-out/tag-out procedures mandatory."),
            (15, False, "Greg Muller — very handy, does a lot of his own work. Prefers if we explain what we're doing as we go."),
            (19, False, "David Henderson — recently purchased home. May need additional work as he discovers issues."),
        ]
        for client_idx, starred, content in notes_data:
            db.add(ClientNote(
                client_id=client_objs[client_idx].id, user_id=user.id,
                content=content, is_starred=starred,
                created_at=now - timedelta(days=30 + client_idx * 5),
            ))

        # --- Client Communications ---
        comms_data = [
            (0, 'email', 'outbound', 'Invoice from FieldServicePro — Backflow preventer test — Tower A', 'sent', 4),
            (0, 'email', 'outbound', 'Quote: EV charging stations — Tower A parking', 'opened', 8),
            (0, 'phone', 'inbound', 'Andrea called re: kitchen stack leak Unit 1204 — urgent', 'sent', 1),
            (1, 'email', 'outbound', 'Quote: BFP testing — all Centurion properties', 'opened', 10),
            (1, 'email', 'outbound', 'Scheduling water softener install — Bridgeport Lofts', 'sent', 3),
            (2, 'email', 'outbound', 'Invoice from FieldServicePro — Curb stop Phase 1', 'opened', 10),
            (2, 'email', 'outbound', 'Invoice from FieldServicePro — Curb stop Phase 2', 'sent', 6),
            (2, 'email', 'outbound', 'Quote: Curb stop Phase 3', 'sent', 5),
            (3, 'email', 'outbound', 'Invoice from FieldServicePro — Emergency lighting inspection', 'sent', 3),
            (3, 'phone', 'outbound', 'Called Derek re: washroom reno timeline update', 'sent', 2),
            (4, 'email', 'outbound', 'Invoice from FieldServicePro — Lobby drywall & paint', 'sent', 16),
            (4, 'email', 'outbound', 'Follow-up: overdue invoice INV-00009 — $3,400', 'sent', 5),
            (6, 'email', 'outbound', 'Invoice from FieldServicePro — Hot water tank replacement', 'sent', 14),
            (6, 'phone', 'outbound', 'Called Priya re: overdue invoice follow-up', 'sent', 7),
            (7, 'phone', 'inbound', 'Tom called — furnace emergency, no heat', 'sent', 2),
            (7, 'email', 'outbound', 'Invoice from FieldServicePro — Emergency furnace repair', 'opened', 1),
            (9, 'email', 'outbound', 'Quote: Boiler replacement — GRHC Bldg 2', 'sent', 7),
            (9, 'email', 'outbound', 'Scheduling HVAC duct cleaning — GRHC Bldg 1', 'sent', 4),
            (9, 'phone', 'inbound', 'Mark called re: accessibility ramp timeline', 'sent', 1),
            # New client comms
            (10, 'email', 'outbound', 'Invoice from FieldServicePro — Washroom fixture replacement', 'sent', 7),
            (10, 'email', 'outbound', 'Invoice from FieldServicePro — Backflow preventer test — Trades Wing', 'opened', 5),
            (10, 'email', 'outbound', 'Scheduling RTU seasonal startup — Main Bldg', 'sent', 3),
            (10, 'phone', 'inbound', 'Janice called re: emergency exit signs — Waterloo Campus', 'sent', 5),
            (11, 'email', 'outbound', 'Invoice from FieldServicePro — Hot water recirc pump', 'opened', 9),
            (11, 'email', 'outbound', 'Invoice from FieldServicePro — Boiler maintenance', 'sent', 6),
            (11, 'phone', 'inbound', 'Robert called — AC not working in room 204, residents complaining', 'sent', 0),
            (11, 'email', 'outbound', 'Invoice from FieldServicePro — Dining hall ceiling tiles', 'opened', 12),
            (12, 'email', 'outbound', 'Invoice from FieldServicePro — Sump pump installation', 'sent', 14),
            (12, 'email', 'outbound', 'Follow-up: overdue invoice — Eagle Landing sump pump', 'sent', 5),
            (12, 'email', 'outbound', 'Quote: EV charging — Eagle Landing garage', 'sent', 4),
            (12, 'phone', 'outbound', 'Called Samantha re: Grand Flats Phase 2 rough-in progress', 'sent', 2),
            (13, 'email', 'outbound', 'Invoice from FieldServicePro — Burst pipe emergency — Weber Place', 'sent', 2),
            (13, 'email', 'outbound', 'Invoice from FieldServicePro — Backflow test — Frederick Mall', 'opened', 17),
            (13, 'email', 'outbound', 'Quote: Lobby renovation — Weber Place', 'sent', 6),
            (13, 'phone', 'inbound', 'Victor called — burst pipe emergency, Weber Place 2nd floor', 'sent', 3),
            (14, 'email', 'outbound', 'Invoice from FieldServicePro — Floor drain cleaning', 'opened', 7),
            (14, 'email', 'outbound', 'Quote: Compressed air system', 'opened', 5),
            (14, 'phone', 'outbound', 'Called Heather re: high-voltage panel schedule', 'sent', 3),
            (15, 'email', 'outbound', 'Invoice from FieldServicePro — Bathroom rough-in', 'opened', 16),
            (15, 'email', 'outbound', 'Invoice from FieldServicePro — Basement framing & drywall', 'sent', 18),
            (16, 'email', 'outbound', 'Invoice from FieldServicePro — Furnace replacement', 'opened', 10),
            (18, 'email', 'outbound', 'Invoice from FieldServicePro — Kitchen faucet install', 'sent', 1),
        ]
        for client_idx, ctype, direction, subject, status, days_ago in comms_data:
            db.add(ClientCommunication(
                client_id=client_objs[client_idx].id, user_id=user.id,
                comm_type=ctype, direction=direction, subject=subject,
                status=status, sent_at=now - timedelta(days=days_ago),
                created_at=now - timedelta(days=days_ago),
            ))

        db.commit()
        login_user(user)
        flash('Welcome to the FieldServicePro demo! Explore the app with pre-loaded data.', 'success')
        return redirect(url_for('dashboard'))

    except Exception as e:
        db.rollback()
        flash(f'Error setting up demo: {str(e)}', 'error')
        return redirect(url_for('auth.login'))
    finally:
        db.close()
