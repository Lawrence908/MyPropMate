"""MyPropMate FastAPI entry point.

Drives the active pipeline: IMAP -> parse -> SQLite -> Excel/PDF -> SMTP.

Two operating modes:
  * Telegram off: a poll preps AND emails receipts automatically.
  * Telegram on:  a poll preps receipts and asks for confirmation in Telegram;
    receipts are only emailed when you tap "Confirm & Send".

The processor is synchronous (blocking IMAP + LibreOffice + SMTP), so all of its
calls are offloaded to worker threads.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings, get_settings
from app.pipeline.backup import run_backup
from app.pipeline.processor import PaymentProcessor
from app.pipeline.store import Store, seed_from_json
from app.pipeline.telegram import TelegramBot
from app.portfolio import store as portfolio_store
from app.portfolio.routes import router as portfolio_router


scheduler = AsyncIOScheduler()


def get_store(settings: Settings = Depends(get_settings)) -> Store:
    store = Store(settings.db_path)
    try:
        yield store
    finally:
        store.close()


def _build_bot(settings: Settings) -> Optional[TelegramBot]:
    if settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramBot(settings.telegram_bot_token, settings.telegram_chat_id)
    return None


async def _prep_and_notify(processor: PaymentProcessor, bot: TelegramBot) -> None:
    """Prep new payments (no email) and post each to Telegram for confirmation."""
    summary = await asyncio.to_thread(processor.process_new_payments, send_email=False)
    for d in summary["details"]:
        try:
            if d.get("receipt") and d.get("invoice_no") is not None:
                await asyncio.to_thread(bot.send_payment_notification, d)
            elif "failed" in d:
                await asyncio.to_thread(
                    bot.send_message,
                    f"⚠️ Payment needs attention\nRef <code>{d.get('ref')}</code>\n{d['failed']}",
                )
        except Exception as exc:
            print(f"Telegram notify error for {d.get('ref')}: {exc}")
    if summary["processed"] or summary["failed"]:
        print(f"Prep: {summary['processed']} awaiting confirmation, {summary['failed']} flagged")


def _handle_callback(processor: PaymentProcessor, bot: TelegramBot, cq: dict) -> None:
    data = cq.get("data", "")
    message_id = cq.get("message", {}).get("message_id")
    no_buttons = {"inline_keyboard": []}
    action, _, ref = data.partition(":")
    if action == "confirm":
        res = processor.send_one(ref)
        if res.get("status") == "sent":
            bot.answer_callback(cq["id"], "Receipt sent ✅")
            caption = f"✅ Sent to {res['to']}"
        else:
            bot.answer_callback(cq["id"], f"Not sent: {res.get('status')}")
            caption = f"ℹ️ {res.get('status')}"
        if message_id:
            bot.edit_caption(message_id, caption, reply_markup=no_buttons)
    elif action == "hold":
        bot.answer_callback(cq["id"], "Held ⏸")
        if message_id:
            bot.edit_caption(message_id, "⏸ Held — not sent", reply_markup=no_buttons)


async def _telegram_listener(processor: PaymentProcessor, bot: TelegramBot) -> None:
    """Long-poll Telegram for Confirm/Hold taps until cancelled."""
    offset: Optional[int] = None
    print("Telegram listener started")
    while True:
        try:
            updates = await asyncio.to_thread(bot.get_updates, offset, 25)
            for upd in updates:
                offset = upd["update_id"] + 1
                cq = upd.get("callback_query")
                if cq:
                    await asyncio.to_thread(_handle_callback, processor, bot, cq)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            print(f"Telegram listener error: {exc}")
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    store = Store(settings.db_path)
    try:
        n = seed_from_json(store, settings.tenants_seed_path)
        print(f"Seeded/updated {n} tenants from {settings.tenants_seed_path}")
        portfolio_store.ensure_schema(store.conn)
    finally:
        store.close()

    processor = PaymentProcessor(settings)
    bot = _build_bot(settings)
    app.state.processor = processor
    app.state.bot = bot

    listener_task = None
    if bot is not None:
        try:
            me = await asyncio.to_thread(bot.get_me)
            print(f"Telegram bot connected: @{me['result']['username']}")
            await asyncio.to_thread(bot.send_message, "\U0001f7e2 MyPropMate is online.")
        except Exception as exc:
            print(f"Telegram connect failed: {exc}")
        listener_task = asyncio.create_task(_telegram_listener(processor, bot))

    async def poll_job():
        try:
            if bot is not None:
                await _prep_and_notify(processor, bot)
            else:
                summary = await asyncio.to_thread(processor.process_new_payments)
                print(f"Poll: {summary['processed']} processed, "
                      f"{summary['skipped']} skipped, {summary['failed']} failed")
        except Exception as exc:
            print(f"Error in poll job: {exc}")

    def _do_backup() -> str:
        st = Store(settings.db_path)
        try:
            return run_backup(st, settings.backup_dir, settings.backup_retention)
        finally:
            st.close()

    async def backup_job():
        try:
            path = await asyncio.to_thread(_do_backup)
            print(f"DB backup written: {path}")
        except Exception as exc:
            print(f"Backup failed: {exc}")

    scheduler.add_job(
        poll_job, "interval", minutes=settings.poll_interval_minutes,
        id="inbox_poll", replace_existing=True,
    )
    scheduler.add_job(
        backup_job, "interval", hours=settings.backup_interval_hours,
        id="db_backup", replace_existing=True,
    )
    scheduler.start()
    print(f"Started inbox polling every {settings.poll_interval_minutes} minutes "
          f"({'Telegram confirm' if bot else 'auto-send'} mode)")

    # One backup on startup so there is always a fresh copy.
    await backup_job()

    yield

    scheduler.shutdown()
    if listener_task is not None:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
    print("Scheduler shut down")


app = FastAPI(
    title="MyPropMate API",
    description="Rent receipt automation (IMAP -> Excel/PDF -> SMTP)",
    version="0.4.0",
    lifespan=lifespan,
)
app.include_router(portfolio_router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "mypropmate-api"}


@app.get("/api")
async def api_root():
    return {"name": "MyPropMate API", "version": "0.4.0", "docs": "/docs"}


@app.get("/api/tenants")
async def list_tenants(store: Store = Depends(get_store)):
    rows = store.conn.execute(
        "SELECT id, display_name, monthly_rent, parking_fee, phone, email, "
        "last_invoice_no, property_id FROM tenants ORDER BY display_name"
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/payments")
async def list_payments(store: Store = Depends(get_store)):
    rows = store.conn.execute(
        "SELECT p.reference_number, p.sender_name, p.amount, p.period, p.payment_date, "
        "p.invoice_no, p.receipt_path, p.emailed, p.created_at, p.tenant_id, "
        "t.display_name AS tenant_name, t.property_id "
        "FROM payments p LEFT JOIN tenants t ON t.id = p.tenant_id "
        "ORDER BY p.created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/tenants/reseed")
async def reseed_tenants(
    settings: Settings = Depends(get_settings), store: Store = Depends(get_store)
):
    n = seed_from_json(store, settings.tenants_seed_path)
    return {"status": "ok", "seeded": n}


@app.post("/api/payments/process")
async def trigger_payment_processing():
    """Run one poll immediately (prep+notify in Telegram mode, else prep+send)."""
    processor: PaymentProcessor = app.state.processor
    bot: Optional[TelegramBot] = app.state.bot
    if bot is not None:
        await _prep_and_notify(processor, bot)
        return {"status": "prepped", "mode": "telegram-confirm"}
    result = await asyncio.to_thread(processor.process_new_payments)
    return {"status": "processed", "result": result}


@app.get("/api/payments/{reference_number}/receipt")
async def get_receipt(
    reference_number: str,
    settings: Settings = Depends(get_settings),
    store: Store = Depends(get_store),
):
    """Serve the rendered receipt so it can be checked before confirming."""
    row = store.conn.execute(
        "SELECT receipt_path FROM payments WHERE reference_number = ?", (reference_number,)
    ).fetchone()
    if row is None or not row["receipt_path"]:
        raise HTTPException(404, "no receipt for that reference")
    path = os.path.realpath(row["receipt_path"])
    # Only ever serve files from the receipts directory.
    if not path.startswith(os.path.realpath(settings.receipts_dir) + os.sep) or not os.path.exists(path):
        raise HTTPException(404, "receipt file missing")
    media = "application/pdf" if path.endswith(".pdf") else "application/octet-stream"
    return FileResponse(path, media_type=media, filename=os.path.basename(path),
                        content_disposition_type="inline")


@app.post("/api/payments/{reference_number}/send")
async def send_payment_receipt(reference_number: str):
    """Browser equivalent of the Telegram "Confirm & Send" button."""
    processor: PaymentProcessor = app.state.processor
    return await asyncio.to_thread(processor.send_one, reference_number)


# --- Frontend ------------------------------------------------------------------------
# The built React app is copied to FRONTEND_DIR in the image. Anything that is
# not an API route falls through to index.html so client-side routes work on
# refresh. Registered last so it never shadows an API path.
_frontend_dir = os.environ.get("FRONTEND_DIR", "/app/frontend")
if os.path.isdir(_frontend_dir):
    _assets = os.path.join(_frontend_dir, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith(("api/", "docs", "openapi.json", "health")):
            raise HTTPException(404, "not found")
        candidate = os.path.realpath(os.path.join(_frontend_dir, full_path))
        if full_path and candidate.startswith(os.path.realpath(_frontend_dir) + os.sep) \
                and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_frontend_dir, "index.html"))
