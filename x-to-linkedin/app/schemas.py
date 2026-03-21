from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ScrapeRequest(BaseModel):
    url: str
    language: Optional[str] = "es"


class TweetData(BaseModel):
    text: str
    author_name: str
    author_handle: str
    images: list[str] = []
    links: list[str] = []
    tweet_url: str
    paper_info: Optional[dict] = None
    has_video: bool = False
    pdf_url: Optional[str] = None


class GenerateResponse(BaseModel):
    tweet: TweetData
    linkedin_text: str
    suggested_images: list[str] = []
    media_type: str = "auto"  # image | video | document | generate


class PublishRequest(BaseModel):
    tweet_url: str
    tweet_text: str
    tweet_author: str
    linkedin_text: str
    image_urls: list[str] = []
    use_first_image: bool = True
    media_type: str = "auto"  # image | video | document | generate
    pdf_url: Optional[str] = None
    document_title: str = "Documento"


class ScheduleRequest(PublishRequest):
    scheduled_at: Optional[datetime] = None  # ignorado: el backend asigna el próximo slot


class PostResponse(BaseModel):
    id: int
    tweet_url: str
    tweet_author: str
    linkedin_text: str
    image_urls: list[str]
    status: str
    scheduled_at: Optional[datetime]
    published_at: Optional[datetime]
    created_at: datetime
    error_message: Optional[str]
    li_likes: Optional[int] = None
    li_comments: Optional[int] = None
    li_impressions: Optional[int] = None
    li_clicks: Optional[int] = None
    li_shares: Optional[int] = None
    metrics_updated_at: Optional[datetime] = None
    use_first_image: bool = True
    media_type: str = "auto"
    pdf_url: Optional[str] = None
    document_title: str = "Documento"
    generated_image_path: Optional[str] = None

    model_config = {"from_attributes": True}


class AuthStatusResponse(BaseModel):
    connected: bool
    person_name: str = ""
    person_picture: str = ""
    person_urn: str = ""


class PostUpdate(BaseModel):
    linkedin_text: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    use_first_image: Optional[bool] = None
    media_type: Optional[str] = None
    pdf_url: Optional[str] = None
    document_title: Optional[str] = None


class SettingsUpdate(BaseModel):
    custom_prompt: Optional[str] = None  # None = restaurar al default del sistema


class SettingsResponse(BaseModel):
    custom_prompt: Optional[str]
    default_prompt: str
