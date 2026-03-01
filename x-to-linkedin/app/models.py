from sqlalchemy import String, Text, DateTime, JSON, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from .database import Base


class LinkedInToken(Base):
    __tablename__ = "linkedin_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    access_token: Mapped[str] = mapped_column(Text)
    person_urn: Mapped[str] = mapped_column(String(100))
    person_name: Mapped[str] = mapped_column(String(200), default="")
    person_picture: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
