"""tests/test_po_utils.py — PO capacity and balance tracking tests."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from models.database import Base, engine, get_session
from models.purchase_order import PurchaseOrder
from models.client import Client
from models.invoice import Invoice
from models.user import Organization


def setup_module():
    """Create all tables for testing."""
    Base.metadata.create_all(engine)


def _create_test_data(db):
    """Create org, client, and PO for testing."""
    org = db.query(Organization).first()
    if not org:
        org = Organization(name='Test Org')
        db.add(org)
        db.flush()

    client = Client(
        organization_id=org.id, client_type='commercial',
        company_name='Test Corp', email='test@test.com',
    )
    db.add(client)
    db.flush()

    po = PurchaseOrder(
        organization_id=org.id, po_number='PO-TEST-001',
        client_id=client.id, status='active',
        amount_authorized=10000.0, amount_used=0,
        issue_date=date.today(),
    )
    db.add(po)
    db.flush()
    return org, client, po


class TestPOCapacity:
    def test_invoice_fits_in_po(self):
        from web.utils.po_utils import check_po_capacity
        db = get_session()
        try:
            org, client, po = _create_test_data(db)
            result = check_po_capacity(db, po, 5000.0)
            assert result['can_cover'] is True
            assert result['remaining'] == 10000.0
            assert not result['errors']
        finally:
            db.rollback()
            db.close()

    def test_invoice_exceeds_po_returns_warning(self):
        from web.utils.po_utils import check_po_capacity
        db = get_session()
        try:
            org, client, po = _create_test_data(db)
            result = check_po_capacity(db, po, 12000.0)
            assert result['can_cover'] is False
            assert result['overage'] == 2000.0
            assert len(result['warnings']) > 0
        finally:
            db.rollback()
            db.close()

    def test_cancelled_po_returns_error(self):
        from web.utils.po_utils import check_po_capacity
        db = get_session()
        try:
            org, client, po = _create_test_data(db)
            po.status = 'cancelled'
            result = check_po_capacity(db, po, 100.0)
            assert not result['can_cover']
            assert any('cancelled' in e.lower() for e in result['errors'])
        finally:
            db.rollback()
            db.close()

    def test_expired_po_returns_error(self):
        from web.utils.po_utils import check_po_capacity
        db = get_session()
        try:
            org, client, po = _create_test_data(db)
            po.expiry_date = date.today() - timedelta(days=1)
            result = check_po_capacity(db, po, 100.0)
            assert not result['can_cover']
            assert any('expired' in e.lower() for e in result['errors'])
        finally:
            db.rollback()
            db.close()

    def test_near_limit_triggers_warning(self):
        from web.utils.po_utils import check_po_capacity
        db = get_session()
        try:
            org, client, po = _create_test_data(db)
            result = check_po_capacity(db, po, 9500.0)
            assert result['can_cover'] is True
            assert len(result['warnings']) > 0
        finally:
            db.rollback()
            db.close()


class TestPOBalance:
    def test_recalculate_sets_exhausted(self):
        from web.utils.po_utils import recalculate_po_balance
        db = get_session()
        try:
            org, client, po = _create_test_data(db)
            inv = Invoice(
                organization_id=org.id, po_id=po.id, client_id=client.id,
                invoice_number='INV-TEST-001', total=10000.0, status='sent',
            )
            db.add(inv)
            db.flush()
            recalculate_po_balance(db, po)
            assert po.status == 'exhausted'
        finally:
            db.rollback()
            db.close()

    def test_cancel_invoice_reactivates_po(self):
        from web.utils.po_utils import recalculate_po_balance
        db = get_session()
        try:
            org, client, po = _create_test_data(db)
            inv = Invoice(
                organization_id=org.id, po_id=po.id, client_id=client.id,
                invoice_number='INV-TEST-002', total=10000.0, status='sent',
            )
            db.add(inv)
            db.flush()
            recalculate_po_balance(db, po)
            assert po.status == 'exhausted'

            inv.status = 'void'
            db.flush()
            recalculate_po_balance(db, po)
            assert po.status == 'active'
            assert po.amount_remaining == 10000.0
        finally:
            db.rollback()
            db.close()
