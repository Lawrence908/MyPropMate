# MyPropMate

**MyPropMate** is a modular property management application that automates rent receipt generation and tenant communication. It monitors Gmail for Interac e-Transfer notifications, validates payments, generates professional PDF receipts via Invoice Ninja, and emails them to tenants automatically.

## Features

### MVP (Current)
- **Automated Payment Detection**: Monitors Gmail for Interac e-Transfer notifications
- **Tenant Matching**: Automatically matches payments to tenants by sender name
- **Payment Validation**: Verifies amounts against expected rent + parking fees
- **Professional Receipts**: Generates PDF receipts via Invoice Ninja
- **Auto-Email**: Sends receipts to tenants automatically
- **Payment Logging**: Records all payments in Supabase database
- **Error Notifications**: Alerts landlord when manual review is needed

### Planned Features
- Maintenance request tracking
- Financial reporting with tax calculations
- Tenant portal for viewing payment history
- Property value tracking

## Tech Stack

- **Backend**: Python 3.11 with FastAPI
- **Database**: Supabase (PostgreSQL)
- **Invoicing**: Invoice Ninja v5 (external self-hosted instance)
- **Email Detection**: Gmail API with polling
- **Deployment**: Docker Compose

## Architecture

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

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Google Cloud Console project with Gmail API enabled
- Supabase account (free tier works)
- Invoice Ninja instance (external, already running)

### 1. Clone and Configure

```bash
git clone https://github.com/yourusername/MyPropMate.git
cd MyPropMate

# Copy environment template
cp env.example .env
# Edit .env with your credentials
```

### 2. Set Up Gmail API Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable the Gmail API
4. Create OAuth 2.0 credentials (Desktop application)
5. Download the JSON file and save as `credentials/gmail_credentials.json`

### 3. Set Up Supabase

The database schema is already created in the Dev Database. If you need to create it in a new project, see `docs/architecture.md` for the schema.

Get your Supabase URL and anon key from the project settings.

### 4. Configure Invoice Ninja

Your Invoice Ninja instance should already be running. Get an API token:

1. Log into Invoice Ninja (https://invoices.chrislawrence.ca)
2. Go to Settings > API Tokens
3. Generate a new token
4. Add to `.env` as `INVOICENINJA_API_KEY`
5. Set `INVOICENINJA_URL` to your instance URL

### 5. Start Services

```bash
docker compose up -d
```

### 6. Initialize Gmail Token

On first run, you'll need to authenticate Gmail:

```bash
# Run the backend locally once to complete OAuth flow
cd backend
pip install -r requirements.txt
python -c "from app.services.gmail_watcher import GmailWatcher; from app.config import get_settings; GmailWatcher(get_settings())._get_credentials()"
```

This will open a browser for Google authentication. The token will be saved to `credentials/gmail_token.json`.

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Supabase anon/public key |
| `GMAIL_WATCH_EMAIL` | Email address to monitor |
| `LANDLORD_EMAIL` | Email for error notifications |
| `POLL_INTERVAL_MINUTES` | How often to check Gmail (default: 5) |
| `INVOICENINJA_URL` | URL to your Invoice Ninja instance |
| `INVOICENINJA_API_KEY` | Invoice Ninja API token |

### Invoice Ninja URL Options

```bash
# From same Docker network (homelab-web)
INVOICENINJA_URL=http://invoiceninja:80

# From local network
INVOICENINJA_URL=http://192.168.50.70:8113

# From external/public
INVOICENINJA_URL=https://invoices.chrislawrence.ca
```

### Adding Tenants

Use the API or Supabase dashboard to add tenants:

```bash
# Via API
curl -X POST http://localhost:8000/api/tenants \
  -H "Content-Type: application/json" \
  -d '{
    "property_id": "your-property-uuid",
    "name": "John Doe",
    "email": "john@example.com",
    "monthly_rent": 1200,
    "parking_fee": 150
  }'
```

**Important**: The tenant name must match the sender name in Interac e-transfers exactly.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/properties` | GET, POST | List/create properties |
| `/api/tenants` | GET, POST | List/create tenants |
| `/api/tenants/{id}` | GET | Get tenant details |
| `/api/payments` | GET | List payments |
| `/api/payments/process` | POST | Manually trigger payment processing |
| `/api/receipts/send` | POST | Manually send a receipt |

## Payment Flow

1. **Tenant sends Interac e-Transfer** with rent amount
2. **Gmail receives notification** from Interac/CIBC
3. **MyPropMate polls Gmail** (every 5 minutes by default)
4. **Email is parsed** to extract sender name, amount, date
5. **Tenant is matched** by name in database
6. **Amount is validated** against expected rent + parking
7. **Invoice is created** in Invoice Ninja with line items
8. **Invoice is marked paid** and emailed to tenant
9. **Payment is logged** in Supabase
10. **Tenant record is updated** with next due month

If validation fails, the landlord receives an email notification for manual review.

## Development

### Running Locally

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set environment variables
export SUPABASE_URL="..."
export SUPABASE_KEY="..."
# etc.

# Run the server
uvicorn app.main:app --reload
```

### Project Structure

```
MyPropMate/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Environment settings
│   │   ├── db/
│   │   │   └── supabase.py      # Database client
│   │   ├── models/
│   │   │   └── schemas.py       # Pydantic models
│   │   └── services/
│   │       ├── gmail_watcher.py # Email detection
│   │       ├── invoice_ninja.py # Invoice generation
│   │       └── payment_processor.py # Core logic
│   ├── Dockerfile
│   └── requirements.txt
├── credentials/                  # Gmail OAuth (gitignored)
├── docker-compose.yml
├── env.example
└── README.md
```

## License

MIT License
