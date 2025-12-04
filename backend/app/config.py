"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Supabase
    supabase_url: str
    supabase_key: str
    
    # Gmail
    gmail_credentials_path: str = "/app/credentials/gmail_credentials.json"
    gmail_token_path: str = "/app/credentials/gmail_token.json"
    gmail_watch_email: str
    
    # Invoice Ninja
    invoiceninja_url: str = "http://invoiceninja:80"
    invoiceninja_api_key: str = ""
    
    # Notifications
    landlord_email: str
    
    # Polling
    poll_interval_minutes: int = 5
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

