# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A FastAPI service that automates rent receipts: it polls Gmail for Interac e-Transfer notifications, matches each payment to a tenant in Supabase, validates the amount, creates and emails a paid invoice via an external Invoice Ninja v5 instance, then logs the payment.

The Python implementation is a port of an n8n workflow. `rent-receipts.json` in the repo root is that original workflow export; it is the reference for the Gmail search query, email-parsing regexes, and validation tolerance. Consult it when changing parsing behaviour.

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

# One-time Gmail OAuth (opens a browser; must run outside Docker)
cd backend
python -c "from app.services.gmail_watcher import GmailWatcher; from app.config import get_settings; GmailWatcher(get_settings())._get_credentials()"

# Trigger a poll immediately instead of waiting for the scheduler
curl -X POST http://localhost:8000/api/payments/process
```

There is no test suite, linter, or formatter configured. Interactive API docs at `/docs`.

Local runs need `SUPABASE_URL`/`SUPABASE_KEY` etc. in the environment; `Settings` also reads a `.env` in the current working directory, and the credential paths default to the container paths (`/app/credentials/...`), so override `GMAIL_CREDENTIALS_PATH`/`GMAIL_TOKEN_PATH` when running outside Docker.

## Architecture

Request/job flow, all converging on one method:

```
APScheduler (lifespan, every POLL_INTERVAL_MINUTES)  ─┐
POST /api/payments/process                           ─┴─> PaymentProcessor.process_new_payments()
                                                            ├─ GmailWatcher.fetch_new_payments()
                                                            ├─ SupabaseClient (match, dedupe, log)
                                                            └─ InvoiceNinjaClient.create_and_send_invoice()
```

- `backend/app/main.py` — all routes live here (no routers), plus the `lifespan` that starts/stops the APScheduler job.
- `backend/app/services/payment_processor.py` — the only place business rules live. Owns tenant matching, amount validation, period derivation, and the `ValidationError` type.
- `backend/app/services/gmail_watcher.py` — Gmail auth, the `INTERAC_QUERY` search, HTML-stripping regex parser, and label writes.
- `backend/app/services/invoice_ninja.py` — thin Invoice Ninja v5 client; `create_and_send_invoice` is the composite used by the processor.
- `backend/app/db/supabase.py` — all table access. Tables: `properties`, `tenants`, `payments` (schema documented in `docs/architecture.md`).

### Things that will bite you

**Deduplication is three-layered and each layer matters.** A Gmail label `MyPropMate_Processed` is excluded in `GmailWatcher.INTERAC_QUERY`; `check_duplicate_payment` re-checks by Gmail `email_id` in the `payments` table; and a `ValidationError` still calls `mark_as_processed` so a bad email is not retried forever. Unexpected (non-validation) exceptions deliberately skip the label so the email is picked up on the next poll. Preserve this asymmetry.

**Tenant matching depends on the parser's casing.** `_parse_interac_email` title-cases the sender name pulled from the subject line, and `get_tenant_by_name` does an `ilike` exact match against `tenants.name`. Any change to name normalisation on either side silently breaks matching for every tenant.

**Amount validation is exact.** Expected = `monthly_rent + parking_fee`, compared within `AMOUNT_TOLERANCE = 0.01`. Anything else raises `ValidationError`, which is the "notify the landlord" path.

**Landlord notification is a stub.** `_notify_landlord_error` builds a `MIMEText` message and then only `print`s. There is no SMTP send. Do not describe it as working email.

**POST endpoints take query parameters, not JSON bodies.** The handlers in `main.py` declare plain scalar arguments (`name: str`, `monthly_rent: float`, …), so FastAPI binds them from the query string. The `curl -d '{...}'` examples in `README.md` do not actually work. The Pydantic models in `models/schemas.py` are defined but not wired into any route — use them if you convert these to real request bodies.

**The DB layer is async in name only.** Every `SupabaseClient` method is `async def` but calls the synchronous `supabase-py` client, blocking the event loop. Fine at current volume; relevant if you add concurrency.

**`get_supabase()` is a module-level singleton** constructed on first use, injected via `Depends` but not per-request. `get_settings()` is `lru_cache`d the same way.

**Docs describe a different application.** `docs/milestones.md`, `docs/ProjectPlan.md`, and `prompts/prompts.md` plan a Node/Express/React/TypeScript stack with `pdfkit` and `openpyxl` Excel templates. None of that was built. Only `docs/architecture.md` (DB schema, deployment) and `docs/requirements.md` (feature intent) reflect reality. The root `.xlsx` files are legacy receipt templates from the manual workflow.

## Deployment context

Runs on the daedalus homelab host, port 8000, with `./credentials` bind-mounted read-only into the container. Invoice Ninja is a separate self-hosted service reached via `INVOICENINJA_URL` — pick the Docker-network, LAN, or public URL depending on where the code runs (see `env.example`). Compose currently defines its own `mypropmate-network` bridge, so `http://invoiceninja:80` will not resolve unless the service is attached to the shared network.
