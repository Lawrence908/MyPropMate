"""Invoice Ninja API client for creating invoices and sending receipts."""

import httpx
from typing import Dict, Any, Optional
from datetime import date

from app.config import Settings


class InvoiceNinjaClient:
    """Client for Invoice Ninja API v5."""
    
    def __init__(self, settings: Settings):
        self.base_url = settings.invoiceninja_url.rstrip("/")
        self.api_key = settings.invoiceninja_api_key
        self.headers = {
            "X-Api-Token": self.api_key,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json"
        }
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Make an API request to Invoice Ninja."""
        url = f"{self.base_url}/api/v1{endpoint}"
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    # ===================
    # Client Operations
    # ===================
    
    async def find_client_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find an existing client by email."""
        try:
            result = await self._request(
                "GET",
                f"/clients?email={email}"
            )
            clients = result.get("data", [])
            return clients[0] if clients else None
        except Exception:
            return None
    
    async def create_client(
        self,
        name: str,
        email: str,
        phone: str = None,
        address: str = None,
        city: str = None,
        state: str = None,
        postal_code: str = None
    ) -> Dict[str, Any]:
        """Create a new client in Invoice Ninja."""
        data = {
            "name": name,
            "contacts": [
                {
                    "first_name": name.split()[0] if name else "",
                    "last_name": " ".join(name.split()[1:]) if len(name.split()) > 1 else "",
                    "email": email,
                    "phone": phone or ""
                }
            ],
            "address1": address or "",
            "city": city or "",
            "state": state or "",
            "postal_code": postal_code or ""
        }
        
        result = await self._request("POST", "/clients", data)
        return result.get("data", {})
    
    async def get_or_create_client(
        self,
        name: str,
        email: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get existing client by email or create a new one."""
        existing = await self.find_client_by_email(email)
        if existing:
            return existing
        return await self.create_client(name=name, email=email, **kwargs)
    
    # ===================
    # Product Operations
    # ===================
    
    async def get_or_create_product(
        self,
        product_key: str,
        notes: str,
        price: float
    ) -> Dict[str, Any]:
        """Get or create a product (line item type)."""
        # Try to find existing product
        try:
            result = await self._request("GET", f"/products?product_key={product_key}")
            products = result.get("data", [])
            if products:
                return products[0]
        except Exception:
            pass
        
        # Create new product
        data = {
            "product_key": product_key,
            "notes": notes,
            "price": price
        }
        result = await self._request("POST", "/products", data)
        return result.get("data", {})
    
    # ===================
    # Invoice Operations
    # ===================
    
    async def create_invoice(
        self,
        client_id: str,
        line_items: list,
        invoice_date: date = None,
        due_date: date = None,
        public_notes: str = None
    ) -> Dict[str, Any]:
        """Create a new invoice."""
        if invoice_date is None:
            invoice_date = date.today()
        if due_date is None:
            due_date = invoice_date
        
        data = {
            "client_id": client_id,
            "date": invoice_date.isoformat(),
            "due_date": due_date.isoformat(),
            "line_items": line_items,
            "public_notes": public_notes or "",
            "auto_bill_enabled": False
        }
        
        result = await self._request("POST", "/invoices", data)
        return result.get("data", {})
    
    async def mark_invoice_paid(
        self,
        invoice_id: str,
        amount: float,
        payment_date: date = None
    ) -> Dict[str, Any]:
        """Record a payment against an invoice."""
        if payment_date is None:
            payment_date = date.today()
        
        data = {
            "invoices": [
                {
                    "invoice_id": invoice_id,
                    "amount": amount
                }
            ],
            "date": payment_date.isoformat(),
            "type_id": "1"  # Manual/Cash payment
        }
        
        result = await self._request("POST", "/payments", data)
        return result.get("data", {})
    
    async def send_invoice_email(self, invoice_id: str) -> Dict[str, Any]:
        """Send invoice via email to the client."""
        # Invoice Ninja uses action endpoint for emailing
        data = {
            "action": "email",
            "entity": "invoice",
            "entity_id": invoice_id
        }
        
        # The email endpoint
        result = await self._request(
            "POST",
            f"/invoices/{invoice_id}/email"
        )
        return result
    
    # ===================
    # High-Level Operations
    # ===================
    
    async def create_and_send_invoice(
        self,
        tenant: Dict[str, Any],
        amount: float,
        period: str,
        payment_date: date = None
    ) -> Dict[str, Any]:
        """
        Create an invoice for a tenant's rent payment and email it.
        
        This is the main method used by the payment processor.
        """
        if payment_date is None:
            payment_date = date.today()
        
        # Get property info from tenant
        property_info = tenant.get("properties", {}) or {}
        
        # Get or create client in Invoice Ninja
        client = await self.get_or_create_client(
            name=tenant["name"],
            email=tenant["email"],
            phone=tenant.get("phone"),
            address=property_info.get("address"),
            city=property_info.get("city"),
            state=property_info.get("province"),
            postal_code=property_info.get("postal_code")
        )
        client_id = client["id"]
        
        # Build line items
        line_items = []
        
        # Monthly rent
        monthly_rent = float(tenant.get("monthly_rent", 0))
        if monthly_rent > 0:
            line_items.append({
                "product_key": "RENT",
                "notes": f"Monthly Rent - {period}",
                "quantity": 1,
                "cost": monthly_rent
            })
        
        # Parking fee
        parking_fee = float(tenant.get("parking_fee", 0) or 0)
        if parking_fee > 0:
            line_items.append({
                "product_key": "PARKING",
                "notes": f"Parking Fee - {period}",
                "quantity": 1,
                "cost": parking_fee
            })
        
        # Create the invoice
        unit = tenant.get("unit", "")
        unit_text = f" (Unit {unit})" if unit else ""
        
        invoice = await self.create_invoice(
            client_id=client_id,
            line_items=line_items,
            invoice_date=payment_date,
            due_date=payment_date,
            public_notes=f"Rent Receipt{unit_text} for {period}"
        )
        invoice_id = invoice["id"]
        
        # Mark as paid
        await self.mark_invoice_paid(
            invoice_id=invoice_id,
            amount=amount,
            payment_date=payment_date
        )
        
        # Send email
        await self.send_invoice_email(invoice_id)
        
        return {
            "client_id": client_id,
            "invoice_id": invoice_id,
            "invoice_number": invoice.get("number"),
            "amount": amount,
            "emailed": True
        }

