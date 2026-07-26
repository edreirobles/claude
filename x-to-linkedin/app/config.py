from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Text generation provider
    text_generation_provider: str = "anthropic"  # anthropic | openai

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_text_model: str = "claude-opus-4-6"

    # OpenAI
    openai_api_key: str = ""
    openai_text_model: str = "gpt-5-mini"
    openai_reasoning_effort: str = "minimal"

    # LinkedIn OAuth
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://localhost:8000/auth/linkedin/callback"
    linkedin_api_version: str = "202604"

    # LinkedIn — Cookies de sesión para scraping de métricas con Playwright
    # Obtener en: linkedin.com → F12 → Application → Cookies → linkedin.com
    linkedin_li_at: str = ""       # Cookie "li_at"  (auth principal)
    linkedin_jsessionid: str = ""  # Cookie "JSESSIONID" (sin las comillas que rodean el valor)

    # Google AI — generación de imágenes con Imagen 3 / Gemini
    google_api_key: str = ""  # AIzaSy... desde aistudio.google.com

    # App
    secret_key: str = "dev-secret-key-change-in-production"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./x_to_linkedin.db"
    scheduler_database_url: str = "sqlite:///./scheduler_jobs.db"
    allow_insecure_ssl_fallback: bool = False
    post_language: str = "es"
    pre_publish_verification_enabled: bool = True
    pre_publish_verification_hours: int = 6
    linkedin_comment_check_interval_minutes: int = 20
    linkedin_comment_monitor_days: int = 90

    # Editorial radar — daily source discovery + Telegram approval
    editorial_radar_enabled: bool = True
    editorial_radar_lead_hours: int = 48
    editorial_radar_approval_lead_minutes: int = 60
    editorial_radar_publish_delay_minutes: int = 30
    editorial_radar_days_ahead: int = 14
    editorial_radar_source_max_age_hours: int = 168

    # Telegram Bot — Control y notificaciones
    # Obtener token en: @BotFather → /newbot
    # Obtener user_id en: @userinfobot
    telegram_bot_token: str = ""
    telegram_user_id: int = 0

    # X (Twitter) — Scraping de likes con sesión de browser (gratis)
    # Obtener en: x.com → F12 → Application → Cookies → x.com
    x_username: str = ""              # @ handle sin el @  (ej: "johndoe")
    x_auth_token: str = ""            # Cookie "auth_token"
    x_ct0: str = ""                   # Cookie "ct0"
    x_user_id: str = ""               # ID numérico (ya no se usa para scraping, opcional)
    x_auto_schedule_enabled: bool = False
    x_check_interval_minutes: int = 15
    # Fecha/hora de inicio del monitoreo en hora de Monterrey ("YYYY-MM-DDTHH:MM:SS")
    # El monitor NO procesará nada antes de esta fecha. Primera ejecución = semilla.
    x_monitor_start_date: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
