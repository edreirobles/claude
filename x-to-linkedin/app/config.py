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

    # LinkedIn — Cookies de sesión para scraping de métricas con Playwright
    # Obtener en: linkedin.com → F12 → Application → Cookies → linkedin.com
    linkedin_li_at: str = ""       # Cookie "li_at"  (auth principal)
    linkedin_jsessionid: str = ""  # Cookie "JSESSIONID" (sin las comillas que rodean el valor)

    # App
    secret_key: str = "dev-secret-key-change-in-production"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./x_to_linkedin.db"
    post_language: str = "es"

    # X (Twitter) — Scraping de likes con sesión de browser (gratis)
    # Obtener en: x.com → F12 → Application → Cookies → x.com
    x_username: str = ""              # @ handle sin el @  (ej: "johndoe")
    x_auth_token: str = ""            # Cookie "auth_token"
    x_ct0: str = ""                   # Cookie "ct0"
    x_user_id: str = ""               # ID numérico (ya no se usa para scraping, opcional)
    x_check_interval_minutes: int = 15
    # Fecha/hora de inicio del monitoreo en hora de Monterrey ("YYYY-MM-DDTHH:MM:SS")
    # El monitor NO procesará nada antes de esta fecha. Primera ejecución = semilla.
    x_monitor_start_date: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
