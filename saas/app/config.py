from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Base de datos
    database_url: str = "sqlite+aiosqlite:///./saas.db"

    # JWT
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 días

    # Anthropic (generación de posts)
    anthropic_api_key: str = ""

    # Google (generación de imágenes con Imagen)
    google_api_key: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id_influencer: str = ""  # $6/mes — plan Influencer
    stripe_price_id_top_voice: str = ""   # $9/mes — plan Top Voice

    # Email (Resend)
    resend_api_key: str = ""
    from_email: str = "PostLinked <noreply@postlinked.com>"

    # App
    app_url: str = "http://localhost:8001"
    environment: str = "development"

    class Config:
        env_file = ".env"


settings = Settings()
