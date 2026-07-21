"""Tests for input validation schemas (Phase 7)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.utils.validation import (
    validate, JobCreateSchema, ClientCreateSchema, PropertyCreateSchema,
    ClockInSchema, ClockOutSchema, ApproveEntriesSchema, RejectEntriesSchema,
    ScheduleCreateSchema, ScheduleRescheduleSchema, POCapacitySchema,
    InvoiceLinkPOSchema, InvoiceSetTermsSchema, InvoiceRejectSchema,
)


# ─── Helper ─────────────────────────────────────────────────────────────────

def _ok(schema_cls, data):
    obj, err = validate(schema_cls, data)
    assert err is None, f"Unexpected error: {err}"
    return obj


def _fail(schema_cls, data):
    obj, err = validate(schema_cls, data)
    assert obj is None, f"Expected validation failure, got: {obj}"
    assert err is not None and 'error' in err
    return err


# ─── JobCreateSchema ───────────────────────────────────────────────────────

class TestJobCreateSchema:
    def test_valid_minimal(self):
        obj = _ok(JobCreateSchema, {
            'division_id': 1, 'client_id': 1, 'title': 'Fix HVAC',
        })
        assert obj.status == 'draft'
        assert obj.priority == 'normal'
        assert obj.job_type == 'service_call'
        assert obj.estimated_amount == 0

    def test_valid_full(self):
        obj = _ok(JobCreateSchema, {
            'division_id': 1, 'client_id': 1, 'title': 'Install unit',
            'description': 'Replace old unit',
            'status': 'scheduled', 'priority': 'high',
            'job_type': 'installation',
            'scheduled_date': '2025-06-01T09:00:00',
            'technician_id': 5, 'estimated_amount': 2500.50,
            'contract_id': 3,
        })
        assert obj.title == 'Install unit'
        assert obj.estimated_amount == 2500.50

    def test_missing_division_id(self):
        _fail(JobCreateSchema, {'client_id': 1, 'title': 'Test'})

    def test_missing_client_id(self):
        _fail(JobCreateSchema, {'division_id': 1, 'title': 'Test'})

    def test_missing_title(self):
        _fail(JobCreateSchema, {'division_id': 1, 'client_id': 1})

    def test_empty_title(self):
        _fail(JobCreateSchema, {'division_id': 1, 'client_id': 1, 'title': ''})

    def test_invalid_status(self):
        _fail(JobCreateSchema, {
            'division_id': 1, 'client_id': 1, 'title': 'X',
            'status': 'INVALID',
        })

    def test_invalid_priority(self):
        _fail(JobCreateSchema, {
            'division_id': 1, 'client_id': 1, 'title': 'X',
            'priority': 'SUPER_URGENT',
        })

    def test_invalid_job_type(self):
        _fail(JobCreateSchema, {
            'division_id': 1, 'client_id': 1, 'title': 'X',
            'job_type': 'wizardry',
        })

    def test_negative_amount(self):
        _fail(JobCreateSchema, {
            'division_id': 1, 'client_id': 1, 'title': 'X',
            'estimated_amount': -100,
        })

    def test_zero_amount_ok(self):
        obj = _ok(JobCreateSchema, {
            'division_id': 1, 'client_id': 1, 'title': 'X',
            'estimated_amount': 0,
        })
        assert obj.estimated_amount == 0

    def test_invalid_division_id(self):
        _fail(JobCreateSchema, {'division_id': 0, 'client_id': 1, 'title': 'X'})


# ─── ClientCreateSchema ────────────────────────────────────────────────────

class TestClientCreateSchema:
    def test_valid_company(self):
        obj = _ok(ClientCreateSchema, {'company_name': 'ACME Corp'})
        assert obj.client_type == 'commercial'

    def test_valid_individual(self):
        obj = _ok(ClientCreateSchema, {
            'first_name': 'John', 'last_name': 'Doe',
            'client_type': 'residential',
        })
        assert obj.client_type == 'residential'

    def test_no_identifying_info(self):
        _fail(ClientCreateSchema, {'email': 'test@test.com'})

    def test_invalid_client_type(self):
        _fail(ClientCreateSchema, {
            'company_name': 'X', 'client_type': 'industrial',
        })

    def test_invalid_email(self):
        _fail(ClientCreateSchema, {
            'company_name': 'X', 'email': 'not-an-email',
        })

    def test_valid_email_none(self):
        obj = _ok(ClientCreateSchema, {'company_name': 'X'})
        assert obj.email is None

    def test_invalid_phone_too_short(self):
        _fail(ClientCreateSchema, {
            'company_name': 'X', 'phone': '123',
        })

    def test_valid_phone(self):
        obj = _ok(ClientCreateSchema, {
            'company_name': 'X', 'phone': '416-555-1234',
        })
        assert obj.phone == '416-555-1234'

    def test_invalid_postal_code(self):
        _fail(ClientCreateSchema, {
            'company_name': 'X', 'billing_postal_code': 'XYZ',
        })

    def test_valid_canadian_postal(self):
        obj = _ok(ClientCreateSchema, {
            'company_name': 'X', 'billing_postal_code': 'M5V 2T6',
        })

    def test_valid_us_zip(self):
        obj = _ok(ClientCreateSchema, {
            'company_name': 'X', 'billing_postal_code': '10001',
        })


# ─── PropertyCreateSchema ──────────────────────────────────────────────────

class TestPropertyCreateSchema:
    def test_valid(self):
        obj = _ok(PropertyCreateSchema, {'address': '123 Main St'})
        assert obj.province == 'Ontario'

    def test_missing_address(self):
        _fail(PropertyCreateSchema, {'city': 'Toronto'})


# ─── ClockInSchema ─────────────────────────────────────────────────────────

class TestClockInSchema:
    def test_valid(self):
        obj = _ok(ClockInSchema, {
            'technician_id': 1, 'job_id': 10,
        })
        assert obj.entry_type if hasattr(obj, 'entry_type') else True

    def test_missing_technician(self):
        _fail(ClockInSchema, {'job_id': 10})

    def test_missing_job(self):
        _fail(ClockInSchema, {'technician_id': 1})

    def test_zero_ids(self):
        _fail(ClockInSchema, {'technician_id': 0, 'job_id': 0})

    def test_negative_ids(self):
        _fail(ClockInSchema, {'technician_id': -1, 'job_id': -1})


# ─── ClockOutSchema ────────────────────────────────────────────────────────

class TestClockOutSchema:
    def test_valid_minimal(self):
        obj = _ok(ClockOutSchema, {'technician_id': 1})
        assert obj.entry_type == 'regular'

    def test_valid_all_fields(self):
        obj = _ok(ClockOutSchema, {
            'technician_id': 1, 'description': 'Done',
            'entry_type': 'overtime',
        })
        assert obj.entry_type == 'overtime'

    def test_invalid_entry_type(self):
        _fail(ClockOutSchema, {
            'technician_id': 1, 'entry_type': 'banana',
        })

    def test_missing_technician(self):
        _fail(ClockOutSchema, {})


# ─── ApproveEntriesSchema ─────────────────────────────────────────────────

class TestApproveEntriesSchema:
    def test_valid(self):
        obj = _ok(ApproveEntriesSchema, {'entry_ids': [1, 2, 3]})
        assert len(obj.entry_ids) == 3

    def test_empty_list(self):
        _fail(ApproveEntriesSchema, {'entry_ids': []})

    def test_missing(self):
        _fail(ApproveEntriesSchema, {})

    def test_negative_id(self):
        _fail(ApproveEntriesSchema, {'entry_ids': [1, -2]})


# ─── RejectEntriesSchema ──────────────────────────────────────────────────

class TestRejectEntriesSchema:
    def test_valid(self):
        obj = _ok(RejectEntriesSchema, {
            'entry_ids': [1, 2], 'reason': 'Wrong hours',
        })
        assert obj.reason == 'Wrong hours'

    def test_empty_reason(self):
        _fail(RejectEntriesSchema, {
            'entry_ids': [1], 'reason': '',
        })

    def test_missing_reason(self):
        _fail(RejectEntriesSchema, {'entry_ids': [1]})

    def test_missing_ids(self):
        _fail(RejectEntriesSchema, {'reason': 'x'})


# ─── ScheduleCreateSchema ─────────────────────────────────────────────────

class TestScheduleCreateSchema:
    def test_valid(self):
        obj = _ok(ScheduleCreateSchema, {
            'job_id': 1, 'start_time': '2025-06-01T09:00:00',
        })
        assert obj.end_time is None

    def test_valid_with_end(self):
        obj = _ok(ScheduleCreateSchema, {
            'job_id': 1, 'start_time': '2025-06-01T09:00:00',
            'end_time': '2025-06-01T17:00:00',
        })

    def test_missing_job_id(self):
        _fail(ScheduleCreateSchema, {'start_time': '2025-06-01T09:00:00'})

    def test_missing_start_time(self):
        _fail(ScheduleCreateSchema, {'job_id': 1})

    def test_invalid_start_time(self):
        _fail(ScheduleCreateSchema, {
            'job_id': 1, 'start_time': 'not-a-date',
        })

    def test_invalid_end_time(self):
        _fail(ScheduleCreateSchema, {
            'job_id': 1, 'start_time': '2025-06-01T09:00:00',
            'end_time': 'garbage',
        })


# ─── ScheduleRescheduleSchema ──────────────────────────────────────────────

class TestScheduleRescheduleSchema:
    def test_valid(self):
        obj = _ok(ScheduleRescheduleSchema, {
            'job_id': 1, 'new_start': '2025-06-02T10:00:00',
        })

    def test_invalid_new_start(self):
        _fail(ScheduleRescheduleSchema, {
            'job_id': 1, 'new_start': 'nope',
        })


# ─── POCapacitySchema ──────────────────────────────────────────────────────

class TestPOCapacitySchema:
    def test_valid(self):
        obj = _ok(POCapacitySchema, {'amount': 5000})
        assert obj.amount == 5000

    def test_zero_amount(self):
        obj = _ok(POCapacitySchema, {'amount': 0})
        assert obj.amount == 0

    def test_negative_amount(self):
        _fail(POCapacitySchema, {'amount': -100})

    def test_missing_amount(self):
        _fail(POCapacitySchema, {})


# ─── InvoiceLinkPOSchema ──────────────────────────────────────────────────

class TestInvoiceLinkPOSchema:
    def test_valid_null(self):
        obj = _ok(InvoiceLinkPOSchema, {'po_id': None})
        assert obj.po_id is None

    def test_valid_id(self):
        obj = _ok(InvoiceLinkPOSchema, {'po_id': 42})
        assert obj.po_id == 42

    def test_negative_id(self):
        _fail(InvoiceLinkPOSchema, {'po_id': -1})

    def test_missing_key_ok(self):
        obj = _ok(InvoiceLinkPOSchema, {})
        assert obj.po_id is None


# ─── InvoiceSetTermsSchema ─────────────────────────────────────────────────

class TestInvoiceSetTermsSchema:
    def test_valid_net30(self):
        obj = _ok(InvoiceSetTermsSchema, {'payment_terms': 'net_30'})
        assert obj.payment_terms == 'net_30'

    def test_valid_custom(self):
        obj = _ok(InvoiceSetTermsSchema, {
            'payment_terms': 'custom', 'custom_days': 20,
        })

    def test_custom_without_days(self):
        _fail(InvoiceSetTermsSchema, {'payment_terms': 'custom'})

    def test_custom_zero_days(self):
        _fail(InvoiceSetTermsSchema, {
            'payment_terms': 'custom', 'custom_days': 0,
        })

    def test_invalid_terms(self):
        _fail(InvoiceSetTermsSchema, {'payment_terms': 'net_999'})


# ─── InvoiceRejectSchema ──────────────────────────────────────────────────

class TestInvoiceRejectSchema:
    def test_valid(self):
        obj = _ok(InvoiceRejectSchema, {'reason': 'Missing receipt'})
        assert obj.reason == 'Missing receipt'

    def test_empty_reason(self):
        _fail(InvoiceRejectSchema, {'reason': ''})

    def test_missing_reason(self):
        _fail(InvoiceRejectSchema, {})

    def test_long_reason(self):
        _fail(InvoiceRejectSchema, {'reason': 'x' * 2000})
