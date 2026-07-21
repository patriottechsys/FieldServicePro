"""Shared helper functions used across route modules."""

from flask_login import current_user
from models.database import get_session
from models.division import Division


def get_divisions():
    """Get all active divisions for the current user's org."""
    db = get_session()
    try:
        divisions = db.query(Division).filter_by(
            organization_id=current_user.organization_id,
            is_active=True
        ).order_by(Division.sort_order).all()
        return [d.to_dict() for d in divisions]
    finally:
        db.close()


def get_active_division(request):
    """Get the currently selected division from query param or session."""
    division_id = request.args.get('division')
    return int(division_id) if division_id else None
