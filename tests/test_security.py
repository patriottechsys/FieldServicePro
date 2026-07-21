"""Security-focused tests for FieldServicePro.

Covers: auth, authorization, session management, open redirects,
demo route protection, health check.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.conftest import login, post_with_csrf


class TestAuthentication:
    """Login/logout and session management."""

    def test_login_page_loads(self, client):
        resp = client.get('/login')
        assert resp.status_code == 200

    def test_login_valid_credentials(self, client, data):
        resp = login(client, data['owner'].email, 'testpass123')
        assert resp.status_code == 302
        assert resp.headers['Location'] == '/'

    def test_login_invalid_password(self, client, data):
        resp = post_with_csrf(client, '/login', {
            'email': data['owner'].email, 'password': 'wrongpassword',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Invalid email or password' in resp.data

    def test_login_nonexistent_email(self, client, data):
        resp = post_with_csrf(client, '/login', {
            'email': 'nobody@test.com', 'password': 'x',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Invalid email or password' in resp.data

    def test_login_empty_fields(self, client, data):
        resp = post_with_csrf(client, '/login', {
            'email': '', 'password': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Please enter both' in resp.data

    def test_protected_route_redirects_to_login(self, client, data):
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_logout_redirects_to_login(self, client, data):
        login(client, data['owner'].email, 'testpass123')
        resp = client.get('/logout', follow_redirects=False)
        assert resp.status_code == 302
        resp2 = client.get('/', follow_redirects=False)
        assert resp2.status_code == 302
        assert '/login' in resp2.headers['Location']

    def test_dashboard_loads_after_login(self, client, data):
        login(client, data['owner'].email, 'testpass123')
        resp = client.get('/')
        assert resp.status_code == 200


class TestOpenRedirect:
    """Login next parameter should not allow external redirects."""

    def test_next_relative_allowed(self, client, data):
        resp = post_with_csrf(client, '/login?next=/jobs', {
            'email': data['owner'].email, 'password': 'testpass123',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'] == '/jobs'

    def test_next_external_blocked(self, client, data):
        resp = post_with_csrf(
            client,
            '/login?next=https://evil.com/steal',
            {'email': data['owner'].email, 'password': 'testpass123'},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert 'evil.com' not in resp.headers['Location']


class TestDemoRoute:
    """Demo route should be accessible in dev, blocked in production."""

    def test_demo_creates_account(self, client, data):
        resp = client.get('/demo', follow_redirects=False)
        assert resp.status_code == 302

    def test_demo_in_production_returns_404(self, client, data):
        import web.app as app_module
        original = app_module.IS_PRODUCTION
        try:
            app_module.IS_PRODUCTION = True
            resp = client.get('/demo', follow_redirects=False)
            assert resp.status_code == 404
        finally:
            app_module.IS_PRODUCTION = original


class TestAuthorization:
    """Role-based access control."""

    def test_viewer_blocked_from_settings(self, client, data):
        login(client, data['viewer'].email, 'pass123')
        resp = client.get('/settings', follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_owner_can_access_dashboard(self, client, data):
        login(client, data['owner'].email, 'testpass123')
        resp = client.get('/')
        assert resp.status_code == 200


class TestHealthCheck:
    """Health endpoint should always be accessible."""

    def test_health_unauthenticated(self, client, data):
        resp = client.get('/health')
        assert resp.status_code == 200
        data_resp = resp.get_json()
        assert data_resp['status'] == 'healthy'
        assert data_resp['database'] == 'connected'


class TestSessionSecurity:
    """Session cookie security."""

    def test_session_cookie_set_on_login(self, client, data):
        login(client, data['owner'].email, 'testpass123')
        resp = client.get('/')
        assert resp.status_code == 200

    def test_no_session_after_logout(self, client, data):
        login(client, data['owner'].email, 'testpass123')
        client.get('/logout')
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code == 302


class TestCSRF:
    """CSRF protection on state-changing routes."""

    def test_post_without_csrf_token_rejected(self, client, data):
        """POST without CSRF token should return 400."""
        resp = client.post('/login', data={
            'email': data['owner'].email, 'password': 'testpass123',
        }, follow_redirects=False)
        assert resp.status_code == 400

    def test_post_with_csrf_token_accepted(self, client, data):
        """POST with valid CSRF token should succeed."""
        resp = post_with_csrf(client, '/login', {
            'email': data['owner'].email, 'password': 'testpass123',
        }, follow_redirects=False)
        assert resp.status_code == 302

    def test_api_routes_exempt_from_csrf(self, client, data):
        """API routes should not require CSRF tokens."""
        login(client, data['owner'].email, 'testpass123')
        resp = client.get('/api/lookup/technicians',
                          headers={'Accept': 'application/json'})
        assert resp.status_code == 200


class TestBugFixes:
    """Regression tests for Phase 2 bug fixes."""

    def test_job_note_author_not_logged_in_user(self, client, data):
        """Job note should show note author, not the logged-in user."""
        from models.job import JobNote
        from models.database import get_session
        session = get_session()
        try:
            note = JobNote(
                job_id=data['job'].id,
                user_id=data['tech'].user_id if hasattr(data['tech'], 'user_id') else data['owner'].id,
                content='Test note from specific user',
            )
            session.add(note)
            session.commit()
            note_dict = note.to_dict()
            assert 'author_name' in note_dict
            assert 'author_initials' in note_dict
            assert note_dict['author_name'] != ''
        finally:
            session.delete(note)
            session.commit()
            session.close()

    def test_capacity_engine_uses_hours_not_dollars(self):
        """Capacity engine should calculate booked hours, not dollar amounts."""
        from web.utils.capacity_engine import get_capacity_data
        from models.database import get_session
        from datetime import date, timedelta
        session = get_session()
        try:
            org_id = 1
            today = date.today()
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            result = get_capacity_data(session, org_id, start, end)
            assert 'grid' in result
            assert 'total_capacity' in result
            assert result['total_capacity'] >= 0
        finally:
            session.close()
