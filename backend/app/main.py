"""MyPropMate FastAPI entry point.

Drives the active pipeline: IMAP -> parse -> SQLite -> Excel/PDF -> SMTP.
The processor is synchronous (blocking IMAP + LibreOffice), so scheduled and
request-triggered runs are offloaded to a worker thread.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings, get_settings
from app.pipeline.processor import PaymentProcessor
from app.pipeline.store import Store, seed_from_json


scheduler = AsyncIOScheduler()


def get_store(settings: Settings = Depends(get_settings)) -> Store:
    """Per-request SQLite store (cheap to open; closed after the request)."""
    store = Store(settings.db_path)
    try:
        yield store
    finally:
        store.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Seed tenants from the JSON file on startup.
    store = Store(settings.db_path)
    try:
        n = seed_from_json(store, settings.tenants_seed_path)
        print(f"Seeded/updated {n} tenants from {settings.tenants_seed_path}")
    finally:
        store.close()

    processor = PaymentProcessor(settings)

    async def poll_inbox():
        try:
            summary = await asyncio.to_thread(processor.process_new_payments)
            print(f"Poll complete: {summary['processed']} processed, "
                  f"{summary['skipped']} skipped, {summary['failed']} failed")
        except Exception as exc:  # keep the scheduler alive
            print(f"Error polling inbox: {exc}")

    scheduler.add_job(
        poll_inbox,
        "interval",
        minutes=settings.poll_interval_minutes,
        id="inbox_poll",
        replace_existing=True,
    )
    scheduler.start()
    print(f"Started inbox polling every {settings.poll_interval_minutes} minutes")

    yield

    scheduler.shutdown()
    print("Scheduler shut down")


app = FastAPI(
    title="MyPropMate API",
    description="Rent receipt automation (IMAP -> Excel/PDF -> SMTP)",
    version="0.2.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "mypropmate-api"}


@app.get("/")
async def root():
    return {"name": "MyPropMate API", "version": "0.2.0", "docs": "/docs"}


@app.get("/api/tenants")
async def list_tenants(store: Store = Depends(get_store)):
    rows = store.conn.execute(
        "SELECT display_name, monthly_rent, parking_fee, phone, email, last_invoice_no "
        "FROM tenants ORDER BY display_name"
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/payments")
async def list_payments(store: Store = Depends(get_store)):
    rows = store.conn.execute(
        "SELECT reference_number, sender_name, amount, period, payment_date, "
        "invoice_no, receipt_path, emailed, created_at "
        "FROM payments ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/tenants/reseed")
async def reseed_tenants(
    settings: Settings = Depends(get_settings), store: Store = Depends(get_store)
):
    n = seed_from_json(store, settings.tenants_seed_path)
    return {"status": "ok", "seeded": n}


@app.post("/api/payments/process")
async def trigger_payment_processing(settings: Settings = Depends(get_settings)):
    """Run one poll immediately (offloaded to a worker thread)."""
    processor = PaymentProcessor(settings)
    result = await asyncio.to_thread(processor.process_new_payments)
    return {"status": "processed", "result": result}
