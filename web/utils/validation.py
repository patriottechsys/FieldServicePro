"""
Input validation schemas using Pydantic 2.
Centralizes all validation logic for POST/PUT API endpoints.
Returns standardized error responses.
"""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Helpers ────────────────────────────────────────────────────────────────

def validate(schema_cls, data: dict):
    """Validate data against a Pydantic schema.
    Returns (parsed_obj, None) on success or (None, error_dict) on failure.
    Usage:
        obj, err = validate(JobCreateSchema, request.get_json())
        if err:
            return jsonify(err), 400
    """
    try:
        return schema_cls.model_validate(data), None
    except Exception as e:
        return None, _format_error(e)


def _format_error(exc: Exception) -> dict:
    if hasattr(exc, 'errors'):
        msgs = []
        for err in exc.errors():
            loc = ' → '.join(str(l) for l in err.get('loc', []))
            msg = err.get('msg', 'Invalid')
            msgs.append(f"{loc}: {msg}" if loc else msg)
        return {'error': 'Validation failed', 'details': msgs}
    return {'error': str(exc)}


# ─── Invoice Schemas ────────────────────────────────────────────────────────

class InvoiceLinkPOSchema(BaseModel):
    po_id: Optional[int] = None

    @field_validator('po_id')
    @classmethod
    def valid_po_id(cls, v):
        if v is not None and v <= 0:
            raise ValueError('PO ID must be positive')
        return v


class InvoiceSetTermsSchema(BaseModel):
    payment_terms: str = 'net_30'
    custom_days: Optional[int] = None

    @field_validator('payment_terms')
    @classmethod
    def valid_terms(cls, v):
        allowed = {'due_on_receipt', 'net_15', 'net_30', 'net_45', 'net_60', 'net_90', 'custom'}
        if v not in allowed:
            raise ValueError(f'Invalid payment terms. Allowed: {", ".join(sorted(allowed))}')
        return v

    @model_validator(mode='after')
    def check_custom_days(self):
        if self.payment_terms == 'custom':
            if self.custom_days is None or self.custom_days <= 0:
                raise ValueError('custom_days must be a positive integer when payment_terms is "custom"')
        return self


class InvoiceRejectSchema(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)


# ─── Job Schemas ────────────────────────────────────────────────────────────

class JobCreateSchema(BaseModel):
    division_id: int = Field(..., gt=0)
    client_id: int = Field(..., gt=0)
    property_id: Optional[int] = None
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = ''
    status: str = 'draft'
    priority: str = 'normal'
    job_type: str = 'service_call'
    scheduled_date: Optional[str] = None
    technician_id: Optional[int] = None
    estimated_amount: float = 0
    is_callback: bool = False
    original_job_id: Optional[int] = None
    contract_id: Optional[int] = None

    @field_validator('status')
    @classmethod
    def valid_status(cls, v):
        allowed = {'draft', 'scheduled', 'in_progress', 'on_hold', 'completed', 'cancelled'}
        if v not in allowed:
            raise ValueError(f'Invalid status. Allowed: {", ".join(sorted(allowed))}')
        return v

    @field_validator('priority')
    @classmethod
    def valid_priority(cls, v):
        allowed = {'low', 'normal', 'high', 'urgent'}
        if v not in allowed:
            raise ValueError(f'Invalid priority. Allowed: {", ".join(sorted(allowed))}')
        return v

    @field_validator('job_type')
    @classmethod
    def valid_job_type(cls, v):
        allowed = {'service_call', 'maintenance', 'installation', 'repair', 'inspection', 'emergency'}
        if v not in allowed:
            raise ValueError(f'Invalid job type. Allowed: {", ".join(sorted(allowed))}')
        return v

    @field_validator('estimated_amount')
    @classmethod
    def non_negative_amount(cls, v):
        if v < 0:
            raise ValueError('Estimated amount cannot be negative')
        return v


class JobUpdateStatusSchema(BaseModel):
    status: str

    @field_validator('status')
    @classmethod
    def valid_status(cls, v):
        allowed = {'draft', 'scheduled', 'in_progress', 'on_hold', 'completed', 'cancelled'}
        if v not in allowed:
            raise ValueError(f'Invalid status. Allowed: {", ".join(sorted(allowed))}')
        return v


# ─── Client Schemas ─────────────────────────────────────────────────────────

class ClientCreateSchema(BaseModel):
    client_type: str = 'commercial'
    company_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    billing_address: Optional[str] = None
    billing_city: Optional[str] = None
    billing_province: Optional[str] = 'Ontario'
    billing_postal_code: Optional[str] = None
    notes: Optional[str] = None

    @field_validator('client_type')
    @classmethod
    def valid_client_type(cls, v):
        allowed = {'commercial', 'residential'}
        if v not in allowed:
            raise ValueError(f'Invalid client type. Allowed: {", ".join(sorted(allowed))}')
        return v

    @model_validator(mode='after')
    def check_identifying_info(self):
        if not self.company_name and not self.first_name and not self.last_name:
            raise ValueError('At least one of company_name, first_name, or last_name is required')
        return self

    @field_validator('email')
    @classmethod
    def valid_email(cls, v):
        if v and '@' not in v:
            raise ValueError('Invalid email address')
        return v

    @field_validator('phone')
    @classmethod
    def valid_phone(cls, v):
        if v:
            digits = ''.join(c for c in v if c.isdigit())
            if len(digits) < 7 or len(digits) > 15:
                raise ValueError('Phone number must have 7-15 digits')
        return v

    @field_validator('billing_postal_code')
    @classmethod
    def valid_postal_code(cls, v):
        if v:
            import re
            v = v.strip().upper()
            if not re.match(r'^[A-Z]\d[A-Z]\s?\d[A-Z]\d$', v) and not re.match(r'^\d{5}(-\d{4})?$', v):
                raise ValueError('Invalid postal/ZIP code format')
        return v


class PropertyCreateSchema(BaseModel):
    name: Optional[str] = None
    address: str = Field(..., min_length=1)
    city: Optional[str] = None
    province: Optional[str] = 'Ontario'
    postal_code: Optional[str] = None
    unit_number: Optional[str] = None
    property_type: Optional[str] = None
    notes: Optional[str] = None


# ─── Time Tracking Schemas ─────────────────────────────────────────────────

class ClockInSchema(BaseModel):
    technician_id: int = Field(..., gt=0)
    job_id: int = Field(..., gt=0)
    phase_id: Optional[int] = None
    notes: Optional[str] = None


class ClockOutSchema(BaseModel):
    technician_id: int = Field(..., gt=0)
    description: Optional[str] = None
    entry_type: str = 'regular'

    @field_validator('entry_type')
    @classmethod
    def valid_entry_type(cls, v):
        allowed = {'regular', 'overtime', 'travel', 'break'}
        if v not in allowed:
            raise ValueError(f'Invalid entry type. Allowed: {", ".join(sorted(allowed))}')
        return v


class ApproveEntriesSchema(BaseModel):
    entry_ids: list[int] = Field(..., min_length=1)

    @field_validator('entry_ids')
    @classmethod
    def valid_ids(cls, v):
        if any(i <= 0 for i in v):
            raise ValueError('All entry IDs must be positive')
        return v


class RejectEntriesSchema(BaseModel):
    entry_ids: list[int] = Field(..., min_length=1)
    reason: str = Field(..., min_length=1, max_length=500)

    @field_validator('entry_ids')
    @classmethod
    def valid_ids(cls, v):
        if any(i <= 0 for i in v):
            raise ValueError('All entry IDs must be positive')
        return v


# ─── Schedule Schemas ──────────────────────────────────────────────────────

class ScheduleCreateSchema(BaseModel):
    job_id: int = Field(..., gt=0)
    technician_id: Optional[int] = None
    start_time: str = Field(..., min_length=1)
    end_time: Optional[str] = None

    @field_validator('start_time')
    @classmethod
    def valid_start_time(cls, v):
        try:
            datetime.fromisoformat(v.replace('Z', ''))
        except ValueError:
            raise ValueError('Invalid start_time format. Use ISO 8601.')
        return v

    @model_validator(mode='after')
    def validate_end_time(self):
        if self.end_time:
            try:
                datetime.fromisoformat(self.end_time.replace('Z', ''))
            except ValueError:
                raise ValueError('Invalid end_time format. Use ISO 8601.')
        return self


class ScheduleRescheduleSchema(BaseModel):
    job_id: int = Field(..., gt=0)
    new_start: str = Field(..., min_length=1)
    new_end: Optional[str] = None

    @field_validator('new_start')
    @classmethod
    def valid_new_start(cls, v):
        try:
            datetime.fromisoformat(v.replace('Z', ''))
        except ValueError:
            raise ValueError('Invalid new_start format. Use ISO 8601.')
        return v

    @model_validator(mode='after')
    def validate_new_end(self):
        if self.new_end:
            try:
                datetime.fromisoformat(self.new_end.replace('Z', ''))
            except ValueError:
                raise ValueError('Invalid new_end format. Use ISO 8601.')
        return self


# ─── PO Schemas ─────────────────────────────────────────────────────────────

class POCapacitySchema(BaseModel):
    amount: float = Field(..., ge=0)
    exclude_invoice_id: Optional[int] = None


# ─── Checklist Schemas ─────────────────────────────────────────────────────

class ChecklistItemUpdateSchema(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None

    @field_validator('status')
    @classmethod
    def valid_status(cls, v):
        if v is not None:
            allowed = {'pending', 'passed', 'failed', 'na'}
            if v not in allowed:
                raise ValueError(f'Invalid status. Allowed: {", ".join(sorted(allowed))}')
        return v
