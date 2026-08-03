"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    The active pipeline is IMAP -> parse -> SQLite -> Excel/PDF -> SMTP.
    The legacy Supabase / Gmail-OAuth / Invoice Ninja fields are kept optional
    so the old modules still import, but they are not used by the pipeline.
    """

    # --- Active pipeline: IMAP inbox we watch for Interac e-Transfers ---
    imap_host: str = "imap.gmail.com"
    imap_email: str = "c.lawrence908@gmail.com"
    imap_password: str = ""  # Gmail app password; set in .env, never commit

    # --- Active pipeline: SMTP used to email the receipt PDF ---
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""  # Gmail app password for the sending account
    smtp_from_name: str = "Chris Lawrence"
    smtp_from_address: str = ""

    # --- Active pipeline: files and storage ---
    template_path: str = "/app/templates/rental_receipt_template.xlsx"
    receipts_dir: str = "/app/receipts"
    db_path: str = "/app/data/mypropmate.db"
    tenants_seed_path: str = "/app/data/tenants.json"
    soffice_bin: str = "soffice"

    # Where to send validation/error notifications
    landlord_email: str = "c.lawrence908@gmail.com"

    # Amount tolerance for rent + parking match
    amount_tolerance: float = 0.01

    # Polling
    poll_interval_minutes: int = 5

    # --- Legacy (kept optional so old modules still import) ---
    supabase_url: str = ""
    supabase_key: str = ""
    gmail_credentials_path: str = "/app/credentials/gmail_credentials.json"
    gmail_token_path: str = "/app/credentials/gmail_token.json"
    gmail_watch_email: str = ""
    invoiceninja_url: str = "http://invoiceninja:80"
    invoiceninja_api_key: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
