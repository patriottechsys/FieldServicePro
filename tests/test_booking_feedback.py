"""Tests for Online Booking and Customer Feedback."""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_booking_blueprint_registered():
    """Booking blueprint is registered."""
    from web.app import app
    assert 'booking' in app.blueprints


def test_feedback_blueprint_registered():
    """Feedback blueprint is registered."""
    from web.app import app
    assert 'feedback' in app.blueprints


def test_booking_routes_exist():
    """Key booking routes exist."""
    from web.app import app
    rules = [rule.rule for rule in app.url_map.iter_rules()]
    assert '/book/' in rules
    assert '/book/submit' in rules
    assert '/book/embed' in rules


def test_feedback_routes_exist():
    """Key feedback routes exist."""
    from web.app import app
    rules = [rule.rule for rule in app.url_map.iter_rules()]
    assert '/feedback/dashboard' in rules
    assert '/feedback/list' in rules
    assert '/feedback/pending' in rules
    assert '/feedback/templates' in rules
    assert '/feedback/follow-ups' in rules


def test_nps_category():
    """NPS category computed correctly."""
    from models.feedback_survey import FeedbackSurvey
    s = FeedbackSurvey(nps_score=10)
    assert s.nps_category == 'promoter'
    s.nps_score = 7
    assert s.nps_category == 'passive'
    s.nps_score = 5
    assert s.nps_category == 'detractor'
    s.nps_score = None
    assert s.nps_category is None


def test_star_display():
    """Star display property."""
    from models.feedback_survey import FeedbackSurvey
    s = FeedbackSurvey(overall_rating=3)
    assert s.star_display == '\u2605\u2605\u2605\u2606\u2606'


def test_avg_category_rating():
    """Average category rating computed."""
    from models.feedback_survey import FeedbackSurvey
    s = FeedbackSurvey(
        quality_rating=4, punctuality_rating=5,
        communication_rating=3, professionalism_rating=4,
        value_rating=None,
    )
    assert s.avg_category_rating == 4.0


def test_response_time_hours():
    """Response time computed."""
    from models.feedback_survey import FeedbackSurvey
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    s = FeedbackSurvey(sent_at=now - timedelta(hours=4), completed_at=now)
    assert s.response_time_hours == 4.0


def test_is_expired():
    """Expiry check."""
    from models.feedback_survey import FeedbackSurvey
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    s = FeedbackSurvey(expires_at=now - timedelta(days=1))
    assert s.is_expired is True
    s.expires_at = now + timedelta(days=1)
    assert s.is_expired is False


def test_booking_validation():
    """Booking form validation."""
    from web.utils.booking_utils import validate_booking_submission
    # Missing fields
    errors, valid = validate_booking_submission({})
    assert not valid
    assert len(errors) >= 5

    # Honeypot
    errors, valid = validate_booking_submission({
        'website': 'http://spam.com',
        'service_type': 'plumbing', 'description': 'test',
        'street_address': '123 Main', 'city': 'Test',
        'first_name': 'A', 'last_name': 'B',
        'phone': '555', 'email': 'a@b.com',
    })
    assert not valid
    assert 'Spam' in errors[0]


def test_booking_css_exists():
    """Booking CSS exists."""
    assert os.path.exists(os.path.join('web', 'static', 'css', 'booking.css'))


def test_booking_js_exists():
    """Booking JS exists."""
    assert os.path.exists(os.path.join('web', 'static', 'js', 'booking.js'))


def test_feedback_utils_import():
    """Feedback utils import cleanly."""
    from web.utils.feedback_utils import get_feedback_stats, compute_nps, auto_send_survey
    assert callable(get_feedback_stats)
    assert callable(compute_nps)
    assert callable(auto_send_survey)


def test_survey_template_model():
    """SurveyTemplate model."""
    from models.feedback_survey import SurveyTemplate
    t = SurveyTemplate(name='Test', include_quality=True, include_nps=False)
    assert t.name == 'Test'
    assert t.include_quality is True
    assert t.include_nps is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
