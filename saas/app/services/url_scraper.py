"""
Extrae contenido de cualquier URL: artículos, blogs, posts de X, etc.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}


@dataclass
class ScrapedContent:
    url: str
    title: str = ""
    text: str = ""
    author: str = ""
    images: list[str] = field(default_factory=list)
    source_type: str = "article"  # article, tweet, blog, news


def _is_x_url(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return any(d in domain for d in ["twitter.com", "x.com", "t.co"])


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_main_content(soup: BeautifulSoup) -> str:
    """Extrae el texto principal descartando nav, footer, ads, etc."""
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "form", "noscript", "iframe", "ads"]):
        tag.decompose()

    # Intentar encontrar el contenido principal
    for selector in [
        "article", "[role='main']", "main",
        ".post-content", ".entry-content", ".article-body",
        ".content", "#content", ".post", "#post",
    ]:
        el = soup.select_one(selector)
        if el:
            return _clean_text(el.get_text(separator="\n"))

    # Fallback: body completo
    body = soup.find("body")
    if body:
        return _clean_text(body.get_text(separator="\n"))

    return _clean_text(soup.get_text(separator="\n"))


def _extract_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    images = []
    for img in soup.find_all("img", src=True):
        src = img["src"]
        if src.startswith("http"):
            images.append(src)
        elif src.startswith("//"):
            images.append("https:" + src)
    return images[:5]  # máximo 5


async def scrape_url(url: str) -> ScrapedContent:
    """Extrae el contenido de una URL."""
    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers=HEADERS,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "lxml")

        # Título
        title = ""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"]
        elif soup.title:
            title = soup.title.string or ""
        title = title.strip()

        # Autor
        author = ""
        for sel in [
            'meta[name="author"]',
            'meta[property="article:author"]',
            '[rel="author"]',
            ".author", ".byline",
        ]:
            el = soup.select_one(sel)
            if el:
                author = el.get("content") or el.get_text()
                author = author.strip()
                break

        # Texto principal
        text = _extract_main_content(soup)
        # Limitar a ~4000 chars para no saturar el prompt
        if len(text) > 4000:
            text = text[:4000] + "..."

        # Imágenes
        images = _extract_images(soup, url)
        # Preferir og:image
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            og_img_url = og_image["content"]
            if og_img_url not in images:
                images.insert(0, og_img_url)

        # Tipo de fuente
        source_type = "tweet" if _is_x_url(url) else "article"

        return ScrapedContent(
            url=url,
            title=title,
            text=text,
            author=author,
            images=images,
            source_type=source_type,
        )

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error scraping {url}: {e.response.status_code}")
        raise ValueError(f"No se pudo acceder a la URL (código {e.response.status_code})")
    except httpx.RequestError as e:
        logger.error(f"Request error scraping {url}: {e}")
        raise ValueError("No se pudo conectar a la URL. Verifica que sea válida.")
    except Exception as e:
        logger.error(f"Error inesperado scraping {url}: {e}")
        raise ValueError(f"Error al procesar la URL: {str(e)}")
