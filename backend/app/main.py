"""MyPropMate FastAPI Application Entry Point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings, get_settings
from app.db.supabase import SupabaseClient, get_supabase
from app.services.gmail_watcher import GmailWatcher
from app.services.payment_processor import PaymentProcessor


# Scheduler instance
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events."""
    settings = get_settings()
    
    # Start the Gmail polling scheduler
    processor = PaymentProcessor(settings)
    
    async def poll_gmail():
        """Scheduled task to poll Gmail for new payments."""
        try:
            await processor.process_new_payments()
        except Exception as e:
            print(f"Error polling Gmail: {e}")
    
    scheduler.add_job(
        poll_gmail,
        'interval',
        minutes=settings.poll_interval_minutes,
        id='gmail_poll',
        replace_existing=True
    )
    scheduler.start()
    print(f"Started Gmail polling every {settings.poll_interval_minutes} minutes")
    
    yield
    
    # Shutdown
    scheduler.shutdown()
    print("Scheduler shut down")


app = FastAPI(
    title="MyPropMate API",
    description="Property management and rent receipt automation",
    version="0.1.0",
    lifespan=lifespan
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "mypropmate-api"}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "MyPropMate API",
        "version": "0.1.0",
        "docs": "/docs"
    }


# ===================
# Property Endpoints
# ===================

@app.get("/api/properties")
async def list_properties(db: SupabaseClient = Depends(get_supabase)):
    """List all properties."""
    return await db.get_properties()


@app.post("/api/properties")
async def create_property(
    name: str,
    address: str,
    city: str,
    province: str = "AB",
    postal_code: str = None,
    phone: str = None,
    db: SupabaseClient = Depends(get_supabase)
):
    """Create a new property."""
    return await db.create_property(
        name=name,
        address=address,
        city=city,
        province=province,
        postal_code=postal_code,
        phone=phone
    )


# ===================
# Tenant Endpoints
# ===================

@app.get("/api/tenants")
async def list_tenants(db: SupabaseClient = Depends(get_supabase)):
    """List all tenants."""
    return await db.get_tenants()


@app.get("/api/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, db: SupabaseClient = Depends(get_supabase)):
    """Get a specific tenant."""
    return await db.get_tenant_by_id(tenant_id)


@app.post("/api/tenants")
async def create_tenant(
    property_id: str,
    name: str,
    email: str,
    monthly_rent: float,
    unit: str = None,
    phone: str = None,
    parking_fee: float = 0,
    db: SupabaseClient = Depends(get_supabase)
):
    """Create a new tenant."""
    return await db.create_tenant(
        property_id=property_id,
        name=name,
        email=email,
        monthly_rent=monthly_rent,
        unit=unit,
        phone=phone,
        parking_fee=parking_fee
    )


# ===================
# Payment Endpoints
# ===================

@app.get("/api/payments")
async def list_payments(
    tenant_id: str = None,
    db: SupabaseClient = Depends(get_supabase)
):
    """List payments, optionally filtered by tenant."""
    return await db.get_payments(tenant_id=tenant_id)


@app.post("/api/payments/process")
async def trigger_payment_processing(settings: Settings = Depends(get_settings)):
    """Manually trigger payment processing (polls Gmail now)."""
    processor = PaymentProcessor(settings)
    result = await processor.process_new_payments()
    return {"status": "processed", "result": result}


# ===================
# Manual Receipt Endpoint
# ===================

@app.post("/api/receipts/send")
async def send_receipt(
    tenant_id: str,
    amount: float,
    period: str,
    settings: Settings = Depends(get_settings),
    db: SupabaseClient = Depends(get_supabase)
):
    """Manually send a receipt to a tenant."""
    from app.services.invoice_ninja import InvoiceNinjaClient
    
    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        return {"error": "Tenant not found"}
    
    ninja = InvoiceNinjaClient(settings)
    result = await ninja.create_and_send_invoice(
        tenant=tenant,
        amount=amount,
        period=period
    )
    
    return {"status": "sent", "invoice": result}

