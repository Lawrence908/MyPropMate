"""Supabase database client for MyPropMate."""

from typing import Optional, List, Dict, Any
from datetime import date
from supabase import create_client, Client

from app.config import get_settings


class SupabaseClient:
    """Wrapper around Supabase client with MyPropMate-specific methods."""
    
    def __init__(self):
        settings = get_settings()
        self.client: Client = create_client(
            settings.supabase_url,
            settings.supabase_key
        )
    
    # ===================
    # Properties
    # ===================
    
    async def get_properties(self) -> List[Dict[str, Any]]:
        """Get all properties."""
        response = self.client.table("properties").select("*").execute()
        return response.data
    
    async def create_property(
        self,
        name: str,
        address: str,
        city: str,
        province: str = "AB",
        postal_code: str = None,
        phone: str = None
    ) -> Dict[str, Any]:
        """Create a new property."""
        data = {
            "name": name,
            "address": address,
            "city": city,
            "province": province,
            "postal_code": postal_code,
            "phone": phone
        }
        response = self.client.table("properties").insert(data).execute()
        return response.data[0] if response.data else None
    
    # ===================
    # Tenants
    # ===================
    
    async def get_tenants(self) -> List[Dict[str, Any]]:
        """Get all tenants with their property info."""
        response = self.client.table("tenants").select(
            "*, properties(name, address)"
        ).execute()
        return response.data
    
    async def get_tenant_by_id(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a tenant by ID."""
        response = self.client.table("tenants").select(
            "*, properties(name, address, city, province, phone)"
        ).eq("id", tenant_id).execute()
        return response.data[0] if response.data else None
    
    async def get_tenant_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a tenant by name (case-insensitive)."""
        response = self.client.table("tenants").select(
            "*, properties(name, address, city, province, phone)"
        ).ilike("name", name).execute()
        return response.data[0] if response.data else None
    
    async def create_tenant(
        self,
        property_id: str,
        name: str,
        email: str,
        monthly_rent: float,
        unit: str = None,
        phone: str = None,
        parking_fee: float = 0
    ) -> Dict[str, Any]:
        """Create a new tenant."""
        # Calculate next due month (current month)
        today = date.today()
        next_due = f"{today.year}-{str(today.month).zfill(2)}"
        
        data = {
            "property_id": property_id,
            "name": name,
            "email": email,
            "monthly_rent": monthly_rent,
            "unit": unit,
            "phone": phone,
            "parking_fee": parking_fee,
            "next_due_month": next_due,
            "last_invoice_no": 0
        }
        response = self.client.table("tenants").insert(data).execute()
        return response.data[0] if response.data else None
    
    async def update_tenant_after_payment(
        self,
        tenant_id: str,
        new_invoice_no: int,
        new_next_due: str,
        invoice_ninja_client_id: str = None
    ) -> Dict[str, Any]:
        """Update tenant after processing a payment."""
        data = {
            "last_invoice_no": new_invoice_no,
            "next_due_month": new_next_due
        }
        if invoice_ninja_client_id:
            data["invoice_ninja_client_id"] = invoice_ninja_client_id
        
        response = self.client.table("tenants").update(data).eq(
            "id", tenant_id
        ).execute()
        return response.data[0] if response.data else None
    
    # ===================
    # Payments
    # ===================
    
    async def get_payments(
        self,
        tenant_id: str = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get payments, optionally filtered by tenant."""
        query = self.client.table("payments").select(
            "*, tenants(name, email)"
        ).order("payment_date", desc=True).limit(limit)
        
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        
        response = query.execute()
        return response.data
    
    async def check_duplicate_payment(self, email_id: str) -> bool:
        """Check if a payment with this email ID already exists."""
        response = self.client.table("payments").select("id").eq(
            "email_id", email_id
        ).execute()
        return len(response.data) > 0
    
    async def create_payment(
        self,
        tenant_id: str,
        amount: float,
        payment_date: date,
        period: str,
        email_id: str = None,
        invoice_ninja_invoice_id: str = None,
        notes: str = None
    ) -> Dict[str, Any]:
        """Record a new payment."""
        data = {
            "tenant_id": tenant_id,
            "amount": amount,
            "payment_date": payment_date.isoformat(),
            "period": period,
            "status": "completed",
            "email_id": email_id,
            "invoice_ninja_invoice_id": invoice_ninja_invoice_id,
            "email_sent": False,
            "notes": notes
        }
        response = self.client.table("payments").insert(data).execute()
        return response.data[0] if response.data else None
    
    async def mark_payment_emailed(self, payment_id: str) -> Dict[str, Any]:
        """Mark a payment as having had its receipt emailed."""
        response = self.client.table("payments").update(
            {"email_sent": True}
        ).eq("id", payment_id).execute()
        return response.data[0] if response.data else None


# Dependency injection
_supabase_client: Optional[SupabaseClient] = None


def get_supabase() -> SupabaseClient:
    """Get or create Supabase client instance."""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = SupabaseClient()
    return _supabase_client



