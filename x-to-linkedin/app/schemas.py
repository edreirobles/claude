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
    scheduled_at: datetime


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

    model_config = {"from_attributes": True}


class AuthStatusResponse(BaseModel):
    connected: bool
    person_name: str = ""
    person_picture: str = ""
    person_urn: str = ""
