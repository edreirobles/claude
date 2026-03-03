from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic
    anthropic_api_key: str = ""

    # LinkedIn OAuth
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://localhost:8000/auth/linkedin/callback"

    # App
    secret_key: str = "dev-secret-key-change-in-production"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./x_to_linkedin.db"
    post_language: str = "es"

    # X (Twitter) API — para monitoreo de likes
    # OAuth 1.0a (User Context) — necesario para leer likes privados
    x_api_key: str = ""               # Consumer Key / API Key
    x_api_key_secret: str = ""        # Consumer Secret / API Key Secret
    x_access_token: str = ""          # Access Token (del usuario)
    x_access_token_secret: str = ""   # Access Token Secret (del usuario)
    # App-only (Bearer Token) — ya no funciona para likes desde 2024
    x_bearer_token: str = ""
    x_user_id: str = ""               # ID numérico del usuario (no el @username)
    x_check_interval_minutes: int = 15
    # Fecha/hora de inicio del monitoreo en hora de Monterrey ("YYYY-MM-DDTHH:MM:SS")
    # El monitor NO procesará nada antes de esta fecha. Primera ejecución = semilla.
    x_monitor_start_date: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
