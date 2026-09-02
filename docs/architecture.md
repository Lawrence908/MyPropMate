# Architecture

## System Architecture

MyPropMate is a containerized service that automates rent receipts. It watches a Gmail inbox
over IMAP for Interac e-Transfer deposit notifications, matches each payment to a tenant in a
local SQLite database, renders a receipt from an Excel template, converts it to PDF with headless
LibreOffice, and emails it to the tenant over SMTP.

Everything runs inside the one container. There are no cloud dependencies beyond Gmail's IMAP and
SMTP endpoints and the Telegram Bot API.

### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│  daedalus                                                    │
│                                                              │
│   ┌────────────────────────────────────────────────────┐     │
│   │  mypropmate-api  (FastAPI + APScheduler, :8000)    │     │
│   │                                                    │     │
│   │   ImapClient ─> parser ─> Store (SQLite, WAL)      │     │
│   │                              │                     │     │
│   │                              ▼                     │     │
│   │                    receipt.py ─> LibreOffice ─> PDF│     │
│   │                              │                     │     │
│   │                              ▼                     │     │
│   │                          Mailer (SMTP)             │     │
│   └───┬──────────────┬─────────────────┬───────────────┘     │
│       │              │                 │                     │
│  ./backend/data  ./receipts   /mnt/hermes/backups/mypropmate │
└───────┼──────────────┼─────────────────┼─────────────────────┘
        │              │                 │
   ┌────▼────┐   ┌─────▼─────┐    ┌──────▼──────┐
   │  Gmail  │   │  Gmail    │    │  Telegram   │
   │  IMAP   │   │  SMTP     │    │  Bot API    │
   └─────────┘   └───────────┘    └─────────────┘
```

### Tech Stack

- **Backend**: Python 3.11 with FastAPI
  - APScheduler for the poll and backup jobs
  - Pydantic Settings for configuration
  - The pipeline itself is synchronous and offloaded to worker threads
- **Database**: SQLite, local file, WAL mode with `synchronous=NORMAL`
  - Single-writer and low-volume by design (a few tenants, one payment each per month)
  - `payments.reference_number` is UNIQUE and acts as the idempotency key
- **Receipt generation**: Excel template filled in-place, then LibreOffice Calc headless to PDF
- **Email detection**: Gmail over IMAP with an app password (no OAuth)
  - Server-side `SEARCH FROM "payments.interac.ca"`, bounded to the most recent 40 matches
  - Deduplication is database-side only; nothing is written back to the mailbox
- **Receipt delivery**: Gmail SMTP, with an optional BCC to the landlord
- **Approval**: Telegram Bot API, optional confirm-to-send gate

---

## Operating Modes

Selected by `TELEGRAM_ENABLED`.

| Mode | Poll behaviour | When a receipt is emailed |
|------|----------------|---------------------------|
| Telegram off | Prep and send in one pass | Immediately during the poll |
| Telegram on | Prep only, then post to Telegram with Confirm/Hold buttons | Only when "Confirm & Send" is tapped |

Telegram on is the current production setting.

---

## Database Schema

Defined as `SCHEMA` in `backend/app/pipeline/store.py` and created on first connection. There is
no `properties` table; the earlier Supabase design had one, the SQLite schema does not.

### tenants

Seeded and refreshed from `backend/data/tenants.json`.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| display_name | TEXT | Name shown on the receipt, e.g. "Rick Hilsendeger" |
| match_name | TEXT UNIQUE | Normalized sender name used for lookup |
| monthly_rent | REAL | Expected monthly rent |
| parking_fee | REAL | Additional parking fee, default 0 |
| phone | TEXT | Contact phone, printed on the receipt |
| email | TEXT | Where the receipt PDF is sent |
| last_invoice_no | INTEGER | Per-tenant invoice counter |

`match_name` is the sender name as the bank spells it, lowercased with whitespace collapsed by
`normalize_name`. Interac sends names in caps, so this is usually not the display name.

### payments

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| reference_number | TEXT UNIQUE | Idempotency key taken from the email |
| tenant_id | INTEGER | FK to tenants, NULL for a recorded failure |
| sender_name | TEXT | Raw sender name from the notification |
| amount | REAL | Payment amount |
| period | TEXT | Rental period as "Month YYYY", or a `FAILED: ...` reason |
| payment_date | TEXT | ISO date |
| invoice_no | INTEGER | Consumed only on success, NULL for a failure |
| receipt_path | TEXT | Path to the generated PDF |
| emailed | INTEGER | 1 only after SMTP accepted the message |
| created_at | TEXT | ISO timestamp |

Failures are stored as rows with `tenant_id` and `invoice_no` NULL, and the failure reason in
`period`. This is what stops a permanently unmatched email from being retried on every poll.

---

## Payment Processing Flow

```
1. Poll (every POLL_INTERVAL_MINUTES) or POST /api/payments/process
   │
   ▼
2. recover_failures()
   └── Delete "No tenant matches" rows whose sender now matches a tenant,
       so the payment reprocesses. Amount mismatches are left alone.
   │
   ▼
3. IMAP SEARCH FROM "payments.interac.ca", last 40 matches
   └── Filter to "received" deposit notifications
   │
   ▼
4. Parse: sender_name, amount, reference_number, deposit date, memo
   └── ParseError → skip, leave unrecorded
   │
   ▼
5. Dedupe on reference_number
   │
   ▼
6. Match tenant by normalized match_name
   └── No match → ValidationError → record_failed + notify
   │
   ▼
7. Validate amount within AMOUNT_TOLERANCE of (rent + parking)
   └── Mismatch → ValidationError → record_failed + notify
   │
   ▼
8. Derive period from the memo, falling back to deposit date, then today
   │
   ▼
9. Render receipt: fill xlsx cells in-zip, LibreOffice to PDF
   │
   ▼
10. Email the PDF                      [auto mode, or on Telegram confirm]
   │
   ▼
11. record_payment(): insert the row and bump last_invoice_no in one
    transaction, so an invoice number is consumed only on success
```

Unexpected (non-validation) exceptions propagate and leave the payment unrecorded, so the email is
retried on the next poll. This asymmetry is deliberate.

---

## Component Breakdown

### Pipeline (`backend/app/pipeline/`)

| Module | Responsibility |
|--------|----------------|
| `processor.py` | The only place business rules live: matching, validation, `ValidationError`, failure recording, `send_one` |
| `imap_client.py` | IMAP login and the server-side Interac search. Writes nothing back to the mailbox |
| `parser.py` | Interac regexes, `is_interac_deposit`, `normalize_name`, `derive_period` |
| `store.py` | Schema and all table access, plus the online backup helper |
| `receipt.py` | In-zip xlsx cell fill and the LibreOffice PDF call |
| `mailer.py` | SMTP send for receipts and landlord notices |
| `telegram.py` | Bot API client and the confirm keyboard |
| `backup.py` | Timestamped backups with retention pruning |
| `run.py` | CLI entry point: `seed`, `prep`, `send`, `poll`, `tenants`, `backup` |

### API (`backend/app/main.py`)

All routes live here. None of them take a request body.

| Route | Purpose |
|-------|---------|
| `GET /health` | Liveness check |
| `GET /` | Service banner |
| `GET /api/tenants` | List tenants and their invoice counters |
| `GET /api/payments` | List recorded payments, newest first |
| `POST /api/tenants/reseed` | Re-apply `tenants.json` |
| `POST /api/payments/process` | Run one poll immediately |

`main.py` also owns the APScheduler poll and backup jobs and the Telegram long-poll listener,
which subscribes to `callback_query` updates only.

### Receipt Template

`backend/templates/rental_receipt_template.xlsx` is design-heavy: a full-page background banner,
the logo, and a PAID watermark are embedded images. Saving it through openpyxl mangles them, so
`receipt.py` edits only the target cell values inside the `.xlsx` zip and copies every other part
(drawings, media, styles, sharedStrings) byte-for-byte. The cell map is documented at the top of
that module.

The `.xlsx` files in the repo root are legacy templates from the manual workflow and are not used.

---

## Deployment

Runs on the daedalus homelab host, port 8000. The container runs as `1000:1000` so bind-mounted
data stays chris-owned and the NFS-backed backup directory stays writable. The image installs
`libreoffice-calc` and `fonts-liberation` for PDF rendering.

### Docker Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| mypropmate-api | Custom (Python 3.11) | 8000 | Everything |

### Volume Mounts

| Host | Container | Contents |
|------|-----------|----------|
| `./backend/data` | `/app/data` | SQLite DB and `tenants.json` |
| `./receipts` | `/app/receipts` | Generated `.xlsx` and `.pdf` receipts |
| `./backend/templates` | `/app/templates` (ro) | Receipt template |
| `/mnt/hermes/backups/mypropmate` | `/app/backups` | Durable DB backups on ZFS |

### External Services

| Service | Purpose |
|---------|---------|
| Gmail IMAP (`imap.gmail.com`) | Reading Interac notifications |
| Gmail SMTP (`smtp.gmail.com:587`) | Sending receipt PDFs |
| Telegram Bot API | Confirm-to-send approvals |

### Durability

The DB runs in WAL mode with `synchronous=NORMAL`. A backup job writes a timestamped copy every
`BACKUP_INTERVAL_HOURS` using SQLite's online backup API (`Connection.backup`), so it is safe
while the DB is in use, and prunes to `BACKUP_RETENTION` copies. Backups land on the hermes ZFS
share, deliberately a different disk from the DB.

---

## Security Considerations

1. **Credentials**: IMAP, SMTP, and Telegram secrets live in `.env`, excluded from git
2. **Gmail app passwords**: used instead of OAuth, so there are no refresh tokens to manage.
   They grant full mailbox access, so scope them to this use and rotate if leaked
3. **Confirm-to-send**: with Telegram enabled, no receipt reaches a tenant without an explicit tap
4. **No direct payment processing**: the service only detects and records, it never handles money
5. **Personal mail in scope**: the watched inbox receives unrelated transfers. Non-tenant senders
   are recorded as failures and warned about, never receipted

---

## Legacy Code

`backend/app/services/` (`gmail_watcher.py`, `invoice_ninja.py`, `payment_processor.py`),
`backend/app/db/supabase.py`, and `backend/app/models/schemas.py` are the earlier Gmail-OAuth,
Supabase, and Invoice Ninja implementation. Nothing in `app/main.py` or `app/pipeline/` imports
them. `Settings` keeps the matching fields optional purely so those modules still import. They
are not live and should not be wired back in.

---

## Future Enhancements

1. **Push instead of polling**: Gmail IMAP IDLE, to react immediately rather than every 5 minutes
2. **Tenant management over the API**: currently `tenants.json` plus a reseed call
3. **Reporting**: financial summaries and tax-year exports
4. **Maintenance tracking**: requests and their history
