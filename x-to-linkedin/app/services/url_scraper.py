"""
Extrae contenido de cualquier URL: artículos, blogs, noticias, etc.
Usado cuando el usuario envía un enlace que no es un tweet de X.
"""
import logging
import re
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}


@dataclass
class UrlContent:
    url: str
    title: str = ""
    text: str = ""
    author: str = ""
    images: list[str] = field(default_factory=list)
    has_video: bool = False
    source_domain: str = ""
    published_at: Optional[str] = None
    updated_at: Optional[str] = None
    status_code: int = 200
    content_type: str = ""


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_main_content(soup: BeautifulSoup) -> str:
    """Extrae el texto principal descartando nav, footer, ads, etc."""
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "form", "noscript", "iframe"]):
        tag.decompose()

    for selector in [
        "article", "[role='main']", "main",
        ".post-content", ".entry-content", ".article-body",
        ".content", "#content", ".post", "#post",
        ".article", ".story-body", ".story", ".text",
    ]:
        el = soup.select_one(selector)
        if el:
            return _clean_text(el.get_text(separator="\n"))

    body = soup.find("body")
    if body:
        return _clean_text(body.get_text(separator="\n"))

    return _clean_text(soup.get_text(separator="\n"))


def _extract_images(soup: BeautifulSoup) -> list[str]:
    """Extrae imágenes relevantes de la página."""
    images: list[str] = []

    # Prioridad: og:image
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        images.append(og_image["content"])

    # Twitter card image
    tw_image = soup.find("meta", attrs={"name": "twitter:image"})
    if tw_image and tw_image.get("content"):
        img_url = tw_image["content"]
        if img_url not in images:
            images.append(img_url)

    # Imágenes grandes en el contenido principal
    for img in soup.find_all("img", src=True):
        src = img["src"]
        if not src or src.startswith("data:"):
            continue
        if src.startswith("//"):
            src = "https:" + src
        if not src.startswith("http"):
            continue
        # Excluir íconos y logos pequeños
        width = img.get("width", "")
        height = img.get("height", "")
        try:
            if width and int(str(width).replace("px", "")) < 100:
                continue
        except (ValueError, TypeError):
            pass
        if src not in images:
            images.append(src)
        if len(images) >= 5:
            break

    return images


def _has_video_embed(soup: BeautifulSoup) -> bool:
    """Detecta si la página tiene un video embebido relevante."""
    video_tags = soup.find_all("video")
    if video_tags:
        return True
    # Detectar embeds de YouTube, Vimeo, etc.
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"] or ""
        if any(d in src for d in ["youtube.com", "youtu.be", "vimeo.com"]):
            return True
    return False


def _normalize_datetime_string(value: str) -> Optional[str]:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None

    candidates = [
        raw,
        raw.replace("Z", "+00:00"),
    ]

    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate).isoformat()
        except ValueError:
            continue

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue

    return None


def _extract_json_ld_dates(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
    published = None
    updated = None

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue

        nodes = payload if isinstance(payload, list) else [payload]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if not published:
                published = _normalize_datetime_string(
                    str(node.get("datePublished") or "")
                )
            if not updated:
                updated = _normalize_datetime_string(
                    str(node.get("dateModified") or "")
                )
            if published and updated:
                return published, updated

    return published, updated


def _extract_dates(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
    published_selectors = [
        ('meta[property="article:published_time"]', "content"),
        ('meta[name="article:published_time"]', "content"),
        ('meta[name="parsely-pub-date"]', "content"),
        ('meta[name="pubdate"]', "content"),
        ('meta[name="publish-date"]', "content"),
        ('meta[itemprop="datePublished"]', "content"),
        ('time[itemprop="datePublished"]', "datetime"),
        ("time[datetime]", "datetime"),
    ]
    updated_selectors = [
        ('meta[property="article:modified_time"]', "content"),
        ('meta[name="article:modified_time"]', "content"),
        ('meta[name="last-modified"]', "content"),
        ('meta[itemprop="dateModified"]', "content"),
        ('time[itemprop="dateModified"]', "datetime"),
    ]

    published = None
    updated = None

    for selector, attr in published_selectors:
        el = soup.select_one(selector)
        if not el:
            continue
        value = (el.get(attr) or el.get_text() or "").strip()
        published = _normalize_datetime_string(value)
        if published:
            break

    for selector, attr in updated_selectors:
        el = soup.select_one(selector)
        if not el:
            continue
        value = (el.get(attr) or el.get_text() or "").strip()
        updated = _normalize_datetime_string(value)
        if updated:
            break

    jsonld_published, jsonld_updated = _extract_json_ld_dates(soup)
    published = published or jsonld_published
    updated = updated or jsonld_updated

    return published, updated


async def scrape_url(url: str) -> UrlContent:
    """Extrae el contenido de una URL genérica (artículo, blog, noticia)."""
    domain = urlparse(url).netloc.replace("www.", "")

    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers=HEADERS,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
            status_code = response.status_code
            content_type = response.headers.get("content-type", "")

    except httpx.HTTPStatusError as e:
        raise ValueError(f"No se pudo acceder a la URL (código {e.response.status_code})")
    except httpx.RequestError as e:
        raise ValueError(f"No se pudo conectar a la URL: {e}")

    soup = BeautifulSoup(html, "lxml")

    # Título
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Autor
    author = ""
    for sel in [
        'meta[name="author"]',
        'meta[property="article:author"]',
        '[rel="author"]',
        ".author-name", ".author", ".byline", ".writer",
    ]:
        el = soup.select_one(sel)
        if el:
            author = (el.get("content") or el.get_text()).strip()
            if author:
                break

    # Descripción (como complemento si el texto es corto)
    description = ""
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        description = og_desc["content"].strip()

    # Texto principal
    text = _extract_main_content(soup)
    if len(text) < 200 and description:
        text = description + "\n\n" + text
    # Limitar para no saturar el prompt de Claude
    if len(text) > 5000:
        text = text[:5000] + "…"

    images = _extract_images(soup)
    has_video = _has_video_embed(soup)
    published_at, updated_at = _extract_dates(soup)

    return UrlContent(
        url=url,
        title=title,
        text=text,
        author=author,
        images=images,
        has_video=has_video,
        source_domain=domain,
        published_at=published_at,
        updated_at=updated_at,
        status_code=status_code,
        content_type=content_type,
    )
