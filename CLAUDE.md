# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A FastAPI service with a React UI for managing rental properties. Its core automates rent receipts. It polls a Gmail inbox over IMAP for Interac
e-Transfer deposit notifications, parses each one, matches the sender to a tenant in a local
SQLite DB, validates the amount, fills a design-heavy Excel receipt template, renders it to PDF
with headless LibreOffice, and emails it to the tenant over SMTP.

There are two operating modes, chosen by `TELEGRAM_ENABLED`:

- **Telegram off:** a poll preps and emails receipts automatically.
- **Telegram on (current production setting):** a poll preps receipts and posts each to Telegram
  with Confirm/Hold buttons. Nothing is emailed until you tap "Confirm & Send".

Around the receipt pipeline is a portfolio layer driven by the web UI: properties, household
tasks (maintenance, vendor work, sale prep), leasing leads with drafted messages, listing posts per
venue, and reusable message templates. Every portfolio row hangs off a `property_id`.

`rent-receipts.json` in the repo root is the original n8n workflow export. It remains the
reference for the Interac parsing regexes and the validation tolerance. Consult it when changing
parsing behaviour.

## Commands

```bash
# Run in Docker (reads .env from repo root)
docker compose up -d --build
docker compose logs -f mypropmate-api

# Run locally
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload      # run from backend/, since imports are `app.*`

# CLI, bypassing the scheduler (run from backend/)
python -m app.pipeline.run seed      # load/refresh tenants from JSON
python -m app.pipeline.run prep      # render + record receipts, do NOT email
python -m app.pipeline.run send      # email prepped-but-unsent receipts
python -m app.pipeline.run poll      # prep + send in one shot
python -m app.pipeline.run tenants   # list tenants + their invoice counter
python -m app.pipeline.run backup    # write a timestamped DB backup now

# Trigger a poll immediately instead of waiting for the scheduler
curl -X POST http://localhost:8139/api/payments/process

# Frontend dev server (proxies /api to the container on :8139)
cd frontend && npm install && npm run dev     # http://localhost:5173
cd frontend && npm run build                  # tsc + vite build, also the only type check
```

There is no test suite or formatter configured. `npm run build` is the frontend type check.
Interactive API docs at `/docs`. The UI is served from `/` by the same container.

Local runs need the `IMAP_*`, `SMTP_*`, and `TELEGRAM_*` values in the environment. `Settings`
also reads a `.env` in the current working directory. The file and DB paths default to container
paths (`/app/...`), so override `TEMPLATE_PATH`, `RECEIPTS_DIR`, `DB_PATH`, `TENANTS_SEED_PATH`,
and `BACKUP_DIR` when running outside Docker.

## Architecture

```
APScheduler poll job (every POLL_INTERVAL_MINUTES) ─┐
POST /api/payments/process                          ─┴─> PaymentProcessor.process_new_payments()
                                                          ├─ ImapClient.fetch_new_payments()
                                                          ├─ parse_interac_email() / derive_period()
                                                          ├─ Store (match tenant, dedupe, record)
                                                          ├─ render_receipt()  xlsx fill -> LibreOffice PDF
                                                          └─ Mailer.send_receipt()   [only when send_email]

Telegram tap "Confirm & Send" ──> PaymentProcessor.send_one(ref) ──> Mailer.send_receipt()
```

- `backend/app/main.py`: the receipt routes, the APScheduler poll and backup jobs, the Telegram
  long-poll listener, and the SPA fallback that serves the built UI. Receipt routes are
  `GET /health`, `GET /api`, `GET /api/tenants`, `GET /api/payments`, `POST /api/tenants/reseed`,
  `POST /api/payments/process`, `GET /api/payments/{ref}/receipt`, `POST /api/payments/{ref}/send`
  (the browser twin of Telegram Confirm, via `send_one`).
- `backend/app/portfolio/store.py`: schema and generic CRUD for `properties`, `tasks`,
  `prospects`, `messages`, `posts`, `templates`, plus the allowed status lists (`FIELDS` is the
  per-table write whitelist).
- `backend/app/portfolio/routes.py`: `APIRouter` under `/api` with uniform CRUD per table
  (`GET/POST /x`, `POST /x/bulk`, `GET/PATCH/DELETE /x/{id}`), `/api/meta`, `/api/overview`,
  tenant-to-property assignment, and the message draft/send flow.
- `frontend/`: React + Vite + TypeScript, `react-router-dom`, no UI library. `src/api.ts` holds
  the types and fetch wrapper, `src/hooks.ts` the app context (selected property, toasts),
  `src/components.tsx` the shared form/modal pieces, `src/pages/` one file per screen.
- `backend/app/pipeline/processor.py`: the only place business rules live. Tenant matching, amount
  validation, the `ValidationError` type, failure recording, and `send_one`.
- `backend/app/pipeline/imap_client.py`: IMAP login and the server-side Interac search. Writes
  nothing back to the mailbox.
- `backend/app/pipeline/parser.py`: Interac regexes, `is_interac_deposit`, `normalize_name`, and
  `derive_period`.
- `backend/app/pipeline/store.py`: SQLite schema and all table access. Tables `tenants` and
  `payments`.
- `backend/app/pipeline/receipt.py`: in-zip xlsx cell fill plus the LibreOffice PDF call.
- `backend/app/pipeline/mailer.py`: SMTP send for receipts and landlord notices.
- `backend/app/pipeline/telegram.py`: Bot API client and the confirm keyboard.
- `backend/app/pipeline/backup.py`: timestamped SQLite backups with retention pruning.

### Things that will bite you

**Never save the receipt template through openpyxl.** The template has an embedded background
banner, logo, and PAID watermark. openpyxl mangles them. `receipt.py` edits only the target cell
values inside the `.xlsx` zip and copies every other part (drawings, media, styles,
sharedStrings) byte-for-byte. The cell map is documented at the top of that file.

**Tenant matching uses `match_name`, not the display name.** `normalize_name` lowercases and
collapses whitespace, and `get_tenant_by_name` does an exact match on the `tenants.match_name`
column. Interac sends the sender in caps (`RICK HILSENDEGER`), so every tenant in
`backend/data/tenants.json` needs a `match_name` matching the bank's spelling, which is often not
the display name. An unmatched sender is a `ValidationError`, not a crash.

**Non-tenant transfers are expected and handled.** The same inbox receives personal transfers.
An unmatched sender is recorded by `record_failed` so it warns once rather than every poll, and
the rest of the batch keeps processing. If you later add the tenant, `recover_failures()` at the
top of the next poll deletes the "No tenant matches" row so the payment reprocesses into a real
receipt. Amount-mismatch failures are deliberately left in place since they need a human.

**Recovery depends on the email still being in the INBOX.** Dedup is DB-only by
`reference_number`; nothing is flagged or labelled server-side. `fetch_new_payments` searches
`FROM payments.interac.ca` and keeps the last `lookback` (40) of those, so recovery works only
while the message is inside that window. Past it, `recover_failures` deletes the row and the
email is never re-fetched. Do not "optimise" the search back to `ALL`: the watched inbox has
~18k messages, and a last-40-of-everything scan silently misses payments.

**`emailed = 1` means SMTP accepted the message.** `send_one` calls `mark_emailed` only after
`Mailer.send_receipt` returns without raising, and returns `already-sent` for a row that is
already flagged. Trust the column; do not set it optimistically.

**The invoice counter only moves forward.** `upsert_tenant` uses
`max(last_invoice_no, excluded.last_invoice_no)`, so the value in `tenants.json` is a floor.
Lowering it in the JSON does nothing. `record_payment` bumps the counter and inserts the payment
in one transaction, and the number is consumed only on success.

**`tenants.json` is re-applied constantly.** `seed_from_json` runs at startup and again inside
every `_open_store()`, so editing tenant rows directly in SQLite gets overwritten on the next
poll. Edit the JSON instead. The invoice counter is the one field the DB wins on.

**Amount validation is exact.** Expected = `monthly_rent + parking_fee`, compared within
`AMOUNT_TOLERANCE` (0.01). Anything else raises `ValidationError`, which is the notify path.

**The period is derived from the memo, not the deposit date.** `derive_period` prefers the month
and year named in the transfer message ("Aug", "August 2026 rent"), falling back to the deposit
date and then today. It always returns `"Month YYYY"`. A payment made late still maps to the
month the tenant stated.

**The processor is fully synchronous.** Blocking IMAP, LibreOffice, and SMTP calls are offloaded
with `asyncio.to_thread` from `main.py`. Each `Store` opens its own connection with
`check_same_thread=False`, because FastAPI builds sync dependencies in a worker thread while
`async def` endpoints run on the event loop. Keep connections per-request or per-job; do not
introduce a shared long-lived one without adding locking.

**Landlord notification really sends.** `_notify_landlord` emails via `Mailer.send_notice` when
both `LANDLORD_EMAIL` and `SMTP_PASSWORD` are set, and only falls back to `print` when they are
not. It is best-effort and never blocks the pipeline.

**Confirm and Hold taps log nothing on success.** `_handle_callback` edits the Telegram caption
and answers the callback, but prints only on listener-level exceptions. Do not diagnose the
confirm flow from container logs alone; check the `emailed` column.

**Nothing outbound leaves without a click.** Lead messages are created as `draft`.
`POST /api/messages/{id}/send` emails only when the message channel is `email` and the lead's
`contact` holds an address, and marks it `sent` only after SMTP accepts. For Facebook, text, and
the rest it just records that you sent it yourself. The app never posts to or reads from Facebook;
it prepares text to copy. Keep it that way.

**`tenants.property_id` is DB-owned.** It is the one column the portfolio layer adds to the
receipt tables (via `ALTER TABLE` in `ensure_schema`). `upsert_tenant` never writes it, so the
assignment set in the UI survives the constant JSON re-seed, like the invoice counter. Deleting a
property nulls it rather than deleting tenants.

**The repo is public.** Property addresses, tenant details, leads, leases and other documents live
only in the DB or `backend/data/documents/` (gitignored). Do not commit real data or seed scripts
containing it.

**Dead legacy code is still in the tree.** `app/services/` (`gmail_watcher.py`,
`invoice_ninja.py`, `payment_processor.py`), `app/db/supabase.py`, and `app/models/schemas.py`
are the earlier Gmail-OAuth / Supabase / Invoice Ninja implementation. Nothing in `app/main.py`
or `app/pipeline/` imports them. `Settings` keeps the matching fields optional purely so those
modules still import. Do not treat them as live, and do not wire them back in.

**Docs describe a different application.** `docs/milestones.md`, `docs/ProjectPlan.md`, and
`prompts/prompts.md` plan a Node/Express/React/TypeScript stack. None of that was built.
`docs/architecture.md` still documents the Supabase schema, which the SQLite schema in
`store.py` has replaced. The root `.xlsx` files are legacy receipt templates from the manual
workflow; the live one is `backend/templates/rental_receipt_template.xlsx`.

## Deployment context

Runs on the daedalus homelab host, host port 8139 (container 8000), reachable over LAN and
Tailscale only: no auth, no Caddy route. The image is multi-stage: a Node stage builds `frontend/`
and the result is copied to `/app/frontend`, which `main.py` serves (override with
`FRONTEND_DIR`). Compose builds from the repo root with `backend/Dockerfile`; `.dockerignore`
keeps data and secrets out of the context. The image installs `libreoffice-calc` and
`fonts-liberation` for PDF rendering. Compose runs the container as `1000:1000` so bind-mounted
data stays chris-owned and the NFS-backed backup directory stays writable.

Volumes:

| Host | Container | Contents |
|------|-----------|----------|
| `./backend/data` | `/app/data` | SQLite DB, `tenants.json`, private `documents/` |
| `./receipts` | `/app/receipts` | Generated `.xlsx` and `.pdf` receipts |
| `./backend/templates` | `/app/templates` (ro) | Receipt template |
| `/mnt/hermes/backups/mypropmate` | `/app/backups` | Durable DB backups on ZFS |

The DB runs in WAL mode with `synchronous=NORMAL`. A backup job writes a timestamped copy every
`BACKUP_INTERVAL_HOURS` and prunes to `BACKUP_RETENTION`, using SQLite's online backup API so it
is safe while the DB is in use. Backups land on a different disk from the DB deliberately.
