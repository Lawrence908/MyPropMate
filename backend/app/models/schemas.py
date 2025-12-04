"""Pydantic models for request/response validation."""

from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr


# ===================
# Property Models
# ===================

class PropertyBase(BaseModel):
    name: str
    address: str
    city: str
    province: str = "AB"
    postal_code: Optional[str] = None
    phone: Optional[str] = None


class PropertyCreate(PropertyBase):
    pass


class Property(PropertyBase):
    id: str
    user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ===================
# Tenant Models
# ===================

class TenantBase(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    unit: Optional[str] = None
    monthly_rent: float
    parking_fee: float = 0


class TenantCreate(TenantBase):
    property_id: str


class Tenant(TenantBase):
    id: str
    property_id: str
    lease_start: Optional[date] = None
    lease_end: Optional[date] = None
    next_due_month: Optional[str] = None
    last_invoice_no: int = 0
    invoice_ninja_client_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class TenantWithProperty(Tenant):
    properties: Optional[Property] = None


# ===================
# Payment Models
# ===================

class PaymentBase(BaseModel):
    amount: float
    payment_date: date
    period: str


class PaymentCreate(PaymentBase):
    tenant_id: str
    email_id: Optional[str] = None
    notes: Optional[str] = None


class Payment(PaymentBase):
    id: str
    tenant_id: str
    status: str = "completed"
    invoice_ninja_invoice_id: Optional[str] = None
    email_sent: bool = False
    email_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class PaymentWithTenant(Payment):
    tenants: Optional[Tenant] = None


# ===================
# Email Parsing Models
# ===================

class ParsedInteracEmail(BaseModel):
    """Parsed data from an Interac e-Transfer email."""
    email_id: str
    sender_name: str
    amount: float
    payment_date: date
    message_line: Optional[str] = None
    raw_subject: str


# ===================
# Invoice Ninja Models
# ===================

class InvoiceNinjaClient(BaseModel):
    """Invoice Ninja client representation."""
    id: str
    name: str
    email: Optional[str] = None


class InvoiceNinjaInvoice(BaseModel):
    """Invoice Ninja invoice representation."""
    id: str
    number: str
    amount: float
    status: str
    public_url: Optional[str] = None

