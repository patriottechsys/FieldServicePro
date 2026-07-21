"""Shared test fixtures for FieldServicePro."""

import os
import sys
import pytest
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-production')
os.environ.setdefault('FLASK_ENV', 'testing')


@pytest.fixture(scope='session')
def app():
    """Create application for testing."""
    from web.app import app as flask_app
    flask_app.config['TESTING'] = True
    return flask_app


@pytest.fixture(scope='function')
def client(app):
    """Unauthenticated test client."""
    with app.test_client() as c:
        yield c


@pytest.fixture(scope='function')
def _db(app):
    """Provide a session and clean up test data after each test."""
    from models.database import get_session
    session = get_session()
    yield session
    # Delete all test data (order matters due to FK constraints)
    try:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(text(f'DELETE FROM {table.name}'))
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


# Need Base for cleanup
from models.database import Base


def _create_test_data(session):
    """Create org, user, divisions, tech, client, job. Returns dict."""
    import uuid
    from models import (
        Organization, Division, User, Technician, Client, Job,
    )

    suffix = uuid.uuid4().hex[:8]

    org = Organization(name=f'Test Co {suffix}', phone='555-0000',
                       email=f'test-{suffix}@test.com',
                       city='Testville', province='Ontario')
    session.add(org)
    session.flush()

    div_plb = Division(organization_id=org.id, name='Plumbing', code='PLB',
                       color='#2563eb', sort_order=1)
    div_hvac = Division(organization_id=org.id, name='HVAC', code='HVAC',
                        color='#059669', sort_order=2)
    session.add_all([div_plb, div_hvac])
    session.flush()

    owner = User(email=f'owner-{suffix}@test.com', first_name='Test',
                 last_name='Owner', organization_id=org.id, role='owner')
    owner.set_password('testpass123')
    session.add(owner)

    viewer = User(email=f'viewer-{suffix}@test.com', first_name='View',
                  last_name='Only', organization_id=org.id, role='viewer')
    viewer.set_password('pass123')
    session.add(viewer)

    tech = Technician(organization_id=org.id, division_id=div_plb.id,
                      first_name='Test', last_name='Tech', phone='555-0001',
                      hourly_rate=85)
    session.add(tech)

    client_obj = Client(organization_id=org.id, client_type='residential',
                        first_name='Test', last_name='Client',
                        email=f'client-{suffix}@test.com',
                        phone='555-0002', billing_city='Testville',
                        billing_province='Ontario')
    session.add(client_obj)
    session.flush()

    job = Job(organization_id=org.id, division_id=div_plb.id,
              client_id=client_obj.id, job_number=f'JOB-{suffix}',
              title='Test Job', job_type='service_call', status='draft',
              priority='normal', estimated_amount=1000,
              assigned_technician_id=tech.id, created_by_id=owner.id)
    session.add(job)
    session.commit()

    return {
        'org': org, 'div_plb': div_plb, 'div_hvac': div_hvac,
        'owner': owner, 'viewer': viewer, 'tech': tech,
        'client_obj': client_obj, 'job': job,
    }


@pytest.fixture(scope='function')
def data(_db):
    """Create and commit test data, return dict of objects."""
    return _create_test_data(_db)


def login(client, email, password):
    """Helper to log in via the test client. Handles CSRF automatically."""
    import re
    resp = client.get('/login')
    match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', resp.data.decode())
    token = match.group(1) if match else ''
    return client.post('/login', data={
        'email': email, 'password': password, 'csrf_token': token,
    }, follow_redirects=False)


def get_csrf_token(client):
    """Extract CSRF token from a page's meta tag."""
    import re
    resp = client.get('/login')
    match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', resp.data.decode())
    return match.group(1) if match else ''


def post_with_csrf(client, url, data=None, **kwargs):
    """POST with CSRF token included automatically."""
    token = get_csrf_token(client)
    post_data = dict(data or {})
    post_data['csrf_token'] = token
    return client.post(url, data=post_data, **kwargs)
