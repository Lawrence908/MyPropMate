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
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings, get_settings
from app.pipeline.backup import run_backup
from app.pipeline.processor import PaymentProcessor
from app.pipeline.store import Store, seed_from_json
from app.pipeline.telegram import TelegramBot


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
    version="0.3.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "mypropmate-api"}


@app.get("/")
async def root():
    return {"name": "MyPropMate API", "version": "0.3.0", "docs": "/docs"}


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
async def trigger_payment_processing():
    """Run one poll immediately (prep+notify in Telegram mode, else prep+send)."""
    processor: PaymentProcessor = app.state.processor
    bot: Optional[TelegramBot] = app.state.bot
    if bot is not None:
        await _prep_and_notify(processor, bot)
        return {"status": "prepped", "mode": "telegram-confirm"}
    result = await asyncio.to_thread(processor.process_new_payments)
    return {"status": "processed", "result": result}
