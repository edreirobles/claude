from sqlalchemy import String, Text, DateTime, JSON, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from .database import Base


class AppSettings(Base):
    """Configuración global de la app (fila única con id=1)."""
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)  # None = usar default del sistema
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LinkedInToken(Base):
    __tablename__ = "linkedin_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    person_urn: Mapped[str] = mapped_column(String(100))
    person_name: Mapped[str] = mapped_column(String(200), default="")
    person_picture: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tweet_url: Mapped[str] = mapped_column(Text)
    tweet_text: Mapped[str] = mapped_column(Text)
    tweet_author: Mapped[str] = mapped_column(String(200), default="")
    linkedin_text: Mapped[str] = mapped_column(Text)
    image_urls: Mapped[list] = mapped_column(JSON, default=list)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    linkedin_post_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    use_first_image: Mapped[bool] = mapped_column(Boolean, default=True)
    media_type: Mapped[str] = mapped_column(String(20), default="auto")
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_title: Mapped[str] = mapped_column(String(500), default="Documento")
    # "manual" = publicado manualmente desde la app, "x_auto" = generado desde like en X
    source: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual")

    # Protege ediciones humanas para que verificadores automáticos no reescriban el copy.
    manual_edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    manual_edited_via: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Instrucciones acumuladas que el usuario pide desde Telegram para este borrador.
    editorial_revision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Imagen pre-generada heredada. El flujo editorial nuevo ya no genera imagenes.
    generated_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Métricas de LinkedIn (se actualizan manualmente o automáticamente)
    li_likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    li_comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    li_impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    li_clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    li_shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class XLikedTweet(Base):
    """Registro de tweets que el usuario marcó como 'me gusta' en X y fueron procesados."""
    __tablename__ = "x_liked_tweets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tweet_id: Mapped[str] = mapped_column(String(50), unique=True)
    tweet_url: Mapped[str] = mapped_column(Text)
    tweet_author: Mapped[str] = mapped_column(String(200), default="")
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "processing" | "processed" | "failed"
    status: Mapped[str] = mapped_column(String(20), default="processing")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class LinkedInComment(Base):
    """Comentarios detectados en posts publicados para responder desde Telegram."""
    __tablename__ = "linkedin_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheduled_post_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("scheduled_posts.id"),
        nullable=True,
    )
    linkedin_post_urn: Mapped[str] = mapped_column(String(255), index=True)
    linkedin_object_urn: Mapped[str] = mapped_column(String(255), default="")
    linkedin_comment_urn: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    parent_comment_urn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commenter_name: Mapped[str] = mapped_column(String(255), default="")
    commenter_profile_url: Mapped[str] = mapped_column(Text, default="")
    commenter_headline: Mapped[str] = mapped_column(Text, default="")
    comment_text: Mapped[str] = mapped_column(Text)
    comment_age_label: Mapped[str] = mapped_column(String(50), default="")
    post_public_url: Mapped[str] = mapped_column(Text, default="")
    suggested_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_status: Mapped[str] = mapped_column(String(30), default="pending")
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    owner_replied: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_reply_urn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
