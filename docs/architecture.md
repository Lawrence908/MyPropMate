# Architecture

## System Architecture

MyPropMate is a containerized property management application built for automation and scalability. The system monitors incoming payments via Gmail, processes them automatically, and sends professional receipts through an external Invoice Ninja instance.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Homelab Server (192.168.50.70)               │
│                                                                  │
│  ┌─────────────────┐         ┌─────────────────────────────┐   │
│  │  MyPropMate API │         │  Invoice Ninja (External)   │   │
│  │    (FastAPI)    │────────▶│  https://invoices.           │   │
│  │    Port 8000    │         │       chrislawrence.ca      │   │
│  └────────┬────────┘         │  Local: :8113               │   │
│           │                  └─────────────────────────────┘   │
└───────────┼─────────────────────────────────────────────────────┘
            │
    ┌───────┴───────┐
    │               │
┌───▼───┐     ┌─────▼─────┐
│ Gmail │     │ Supabase  │
│  API  │     │ (Cloud)   │
└───────┘     └───────────┘
```

### Tech Stack

- **Backend**: Python 3.11 with FastAPI
  - Async HTTP handling
  - Background job scheduling with APScheduler
  - Pydantic for validation
  
- **Database**: Supabase (PostgreSQL)
  - Hosted PostgreSQL with REST API
  - Real-time subscriptions (future)
  - Built-in auth (future)
  
- **Invoicing**: Invoice Ninja v5 (self-hosted, external)
  - URL: https://invoices.chrislawrence.ca
  - Local: 192.168.50.70:8113
  - MySQL 8.0 + Redis 7
  - Cloudflare Access protected
  
- **Email Detection**: Gmail API
  - OAuth 2.0 authentication
  - Polling-based monitoring
  - Label-based deduplication

---

## Database Schema

### Tables

#### properties
Stores rental property information.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | Owner reference (future auth) |
| name | VARCHAR | Property name |
| address | VARCHAR | Street address |
| city | VARCHAR | City |
| province | VARCHAR | Province (default: AB) |
| postal_code | VARCHAR | Postal code |
| phone | VARCHAR | Contact phone |
| created_at | TIMESTAMPTZ | Creation timestamp |
| updated_at | TIMESTAMPTZ | Last update |

#### tenants
Stores tenant information and payment tracking.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| property_id | UUID | FK to properties |
| name | VARCHAR | Tenant name (must match e-transfer sender) |
| email | VARCHAR | Email for receipts |
| phone | VARCHAR | Contact phone |
| unit | VARCHAR | Unit number |
| monthly_rent | DECIMAL | Expected monthly rent |
| parking_fee | DECIMAL | Additional parking fee |
| lease_start | DATE | Lease start date |
| lease_end | DATE | Lease end date |
| next_due_month | VARCHAR | Next expected payment (YYYY-MM) |
| last_invoice_no | INTEGER | Last generated invoice number |
| invoice_ninja_client_id | VARCHAR | Link to Invoice Ninja |
| created_at | TIMESTAMPTZ | Creation timestamp |
| updated_at | TIMESTAMPTZ | Last update |

#### payments
Records all processed payments.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| tenant_id | UUID | FK to tenants |
| amount | DECIMAL | Payment amount |
| payment_date | DATE | Date of payment |
| period | VARCHAR | Rental period (e.g., "December 2024") |
| status | VARCHAR | completed, pending, failed |
| invoice_ninja_invoice_id | VARCHAR | Link to Invoice Ninja |
| email_sent | BOOLEAN | Receipt email status |
| email_id | VARCHAR | Gmail message ID (deduplication) |
| notes | TEXT | Processing notes |
| created_at | TIMESTAMPTZ | Creation timestamp |

---

## Payment Processing Flow

```
1. Gmail Poll (every 5 min)
   │
   ▼
2. Search: subject:"Interac e-Transfer" from:interac/cibc
   │
   ▼
3. Parse Email
   ├── Extract: sender_name, amount, date
   └── Check: not already processed (label)
   │
   ▼
4. Match Tenant
   ├── Lookup by name in Supabase
   └── Fail → Notify landlord
   │
   ▼
5. Validate Amount
   ├── Compare: received vs (rent + parking)
   └── Mismatch → Notify landlord
   │
   ▼
6. Create Invoice (Invoice Ninja)
   ├── Get/create client
   ├── Create invoice with line items
   ├── Mark as paid
   └── Send email with PDF
   │
   ▼
7. Record Payment (Supabase)
   ├── Create payment record
   └── Update tenant (next_due_month, invoice_no)
   │
   ▼
8. Mark Email Processed (Gmail label)
```

---

## Component Breakdown

### Backend Services

#### GmailWatcher (`services/gmail_watcher.py`)
- Authenticates with Gmail API using OAuth 2.0
- Searches for Interac e-transfer notifications
- Parses email content to extract payment details
- Marks processed emails with a label

#### InvoiceNinjaClient (`services/invoice_ninja.py`)
- Connects to external Invoice Ninja instance
- Creates and manages clients
- Generates invoices with rent/parking line items
- Records payments against invoices
- Triggers email delivery

#### PaymentProcessor (`services/payment_processor.py`)
- Orchestrates the full payment flow
- Validates payments against tenant records
- Handles errors and notifications
- Updates database state

### Database Layer

#### SupabaseClient (`db/supabase.py`)
- CRUD operations for properties, tenants, payments
- Tenant lookup by name (case-insensitive)
- Duplicate payment detection
- Status updates after processing

---

## Deployment

### Docker Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| mypropmate-api | Custom (Python) | 8000 | Main application |

### External Services

| Service | URL | Purpose |
|---------|-----|---------|
| Invoice Ninja | https://invoices.chrislawrence.ca | Invoice/receipt generation |
| Invoice Ninja (local) | http://192.168.50.70:8113 | Local network access |
| Supabase | https://rhlxmxgabbenavbiaaky.supabase.co | Database |

### Volume Mounts

- `credentials/` → `/app/credentials` (Gmail OAuth tokens)

---

## Invoice Ninja Configuration

The Invoice Ninja instance is hosted separately on the homelab server.

| Component | Details |
|-----------|---------|
| URL | https://invoices.chrislawrence.ca |
| Port | 8113 (local/Tailscale) |
| Database | MySQL 8.0 |
| Cache | Redis 7 |
| Email | Gmail SMTP |
| Access | Cloudflare Access (Admin policy) |

### Connection Options

Configure via `INVOICENINJA_URL` environment variable:

```bash
# From same Docker network (homelab-web)
INVOICENINJA_URL=http://invoiceninja:80

# From local network
INVOICENINJA_URL=http://192.168.50.70:8113

# From external/public
INVOICENINJA_URL=https://invoices.chrislawrence.ca
```

---

## Security Considerations

1. **Credentials**: All secrets stored in `.env`, excluded from git
2. **Gmail OAuth**: Tokens stored locally, refresh automatically
3. **Invoice Ninja**: Accessed via API key, Cloudflare Access for web UI
4. **Database**: Supabase with anon key (RLS recommended for production)
5. **No direct payment processing**: We only detect and record, not handle money

---

## Future Enhancements

1. **Multi-tenancy**: Add user authentication and RLS
2. **Webhooks**: Replace polling with Gmail push notifications
3. **Tenant Portal**: Let tenants view payment history
4. **Maintenance**: Add maintenance request tracking
5. **Reporting**: Financial reports and tax summaries
