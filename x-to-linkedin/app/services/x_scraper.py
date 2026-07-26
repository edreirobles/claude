"""
Extractor de contenido de X (Twitter).
Usa playwright para obtener texto, imágenes y enlaces del tweet.
Fallback a oEmbed para obtener al menos el texto cuando el browser no está disponible.
"""
import re
import sys
import os
import asyncio
import concurrent.futures
import html as html_lib
import httpx
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Optional
import logging

from ..config import get_settings

logger = logging.getLogger(__name__)


def ensure_playwright_browsers_path() -> None:
    """Hace que Playwright encuentre Chromium incluso si la app corre como SYSTEM."""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return

    candidates = [
        r"C:\Users\victo\AppData\Local\ms-playwright",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = candidate
            logger.info("PLAYWRIGHT_BROWSERS_PATH=%s", candidate)
            return


ensure_playwright_browsers_path()

_X_POST_PATH_RE = re.compile(
    r"^/(?:(?P<user>[^/]+)/)?(?P<kind>status|article)/(?P<id>\d+)$",
    re.IGNORECASE,
)
_X_I_STATUS_PATH_RE = re.compile(r"^/i/status/(?P<id>\d+)$", re.IGNORECASE)
_ARXIV_URL_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf|html)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)


@dataclass
class TweetData:
    text: str
    author_name: str
    author_handle: str
    images: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    tweet_url: str = ""
    paper_info: Optional[dict] = None
    has_video: bool = False
    pdf_url: Optional[str] = None
    is_article: bool = False
    article_content: str = ""  # Contenido completo si es un artículo largo de X


def _article_teaser(article_content: str) -> str:
    cleaned = re.sub(r"\s+", " ", (article_content or "")).strip()
    return cleaned[:500]


def normalize_tweet_url(url: str) -> str:
    """Convierte twitter.com a x.com y limpia el URL."""
    url = url.strip()
    url = re.sub(r"https?://(www\.)?(twitter|x)\.com", "https://x.com", url)
    url = url.split("?")[0]
    return url


def is_x_post_url(url: str) -> bool:
    normalized = normalize_tweet_url(url)
    path = httpx.URL(normalized).path
    return bool(_X_POST_PATH_RE.match(path) or _X_I_STATUS_PATH_RE.match(path))


def parse_x_post_url(url: str) -> dict[str, str]:
    """
    Extrae kind e id de una URL de X.

    Soporta:
    - /{user}/status/{id}
    - /{user}/article/{id}
    - /i/status/{id}
    """
    normalized = normalize_tweet_url(url)
    path = httpx.URL(normalized).path

    match = _X_POST_PATH_RE.match(path)
    if match:
        return {
            "url": normalized,
            "kind": match.group("kind").lower(),
            "tweet_id": match.group("id"),
            "username": (match.group("user") or "").strip(),
        }

    match = _X_I_STATUS_PATH_RE.match(path)
    if match:
        return {
            "url": normalized,
            "kind": "status",
            "tweet_id": match.group("id"),
            "username": "",
        }

    return {
        "url": normalized,
        "kind": "",
        "tweet_id": "",
        "username": "",
    }


def extract_arxiv_id(url: str) -> Optional[str]:
    """Extrae el ID moderno de arXiv desde /abs, /pdf o /html."""
    match = _ARXIV_URL_RE.search(url or "")
    return match.group("id") if match else None


def arxiv_pdf_url(url: str) -> Optional[str]:
    """Devuelve el PDF canonico de arXiv si el URL apunta a un paper."""
    arxiv_id = extract_arxiv_id(url)
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None


def is_arxiv_paper(paper_info: Optional[dict]) -> bool:
    """Indica si la metadata corresponde a arXiv."""
    return bool(paper_info and paper_info.get("source") == "arXiv")


def _normalize_x_media_url(src: str | None) -> Optional[str]:
    """Normaliza URLs de media de X y descarta avatares/emoji."""
    if not src:
        return None

    src = html_lib.unescape(src).replace("\\u0026", "&").replace("\\/", "/").strip()
    if not src.startswith("http") or "twimg.com" not in src:
        return None
    if "abs.twimg.com/" in src:
        return None
    if any(skip in src for skip in ("/profile_images/", "/emoji/", "/hashflags/")):
        return None

    if "pbs.twimg.com/media/" in src or "video_thumb" in src:
        if re.search(r"([?&])name=", src):
            src = re.sub(r"([?&])name=[^&]+", r"\1name=large", src)
        elif "?" in src:
            src = f"{src}&name=large"

    return src


def _append_media_url(images: list[str], src: str | None) -> None:
    normalized = _normalize_x_media_url(src)
    if normalized and normalized not in images:
        images.append(normalized)


def _extract_media_urls_from_html(raw_html: str) -> list[str]:
    """Fallback para encontrar media embebida en JSON/HTML renderizado de X."""
    cleaned = (
        raw_html.replace("\\/", "/")
        .replace("\\u0026", "&")
        .replace("&amp;", "&")
    )
    candidates = re.findall(r"https?://[^\"'<>\\\s]+twimg\.com[^\"'<>\\\s]+", cleaned)
    images: list[str] = []
    for candidate in candidates:
        _append_media_url(images, candidate)
    return images


def _is_video_media_url(url: str) -> bool:
    return any(
        marker in (url or "")
        for marker in ("video_thumb", "ext_tw_video_thumb", "amplify_video_thumb")
    )


def _is_external_content_url(url: str) -> bool:
    try:
        host = httpx.URL(url).host or ""
    except Exception:
        return False
    host = host.lower()
    return bool(host) and not (
        host.endswith("x.com")
        or host.endswith("twitter.com")
        or host.endswith("t.co")
    )


async def _expand_tco_url(url: str) -> str:
    """Resuelve enlaces t.co para detectar arXiv/DOI detrás del tweet."""
    if "t.co/" not in (url or ""):
        return url
    try:
        async with httpx.AsyncClient(
            timeout=8,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            response = await client.get(url)
            return str(response.url)
    except Exception as exc:
        logger.debug("No se pudo expandir t.co %s: %s", url, exc)
        return url


async def _get_arxiv_url(url: str, timeout: int = 20) -> httpx.Response:
    """GET para arXiv con fallback SSL acotado a esta fuente."""
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            return await client.get(url)
    except Exception as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        logger.warning("arXiv falló por certificado; reintentando sin verificación SSL")
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
            verify=False,
        ) as client:
            return await client.get(url)


async def fetch_oembed(url: str) -> dict | None:
    """Obtiene datos básicos del tweet via oEmbed (sin credenciales)."""
    oembed_url = f"https://publish.twitter.com/oembed?url={url}&omit_script=true"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(oembed_url)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"oEmbed falló: {e}")
    return None


def parse_oembed(data: dict, url: str) -> TweetData:
    """Parsea la respuesta HTML de oEmbed para extraer texto y autor."""
    html = data.get("html", "")
    soup = BeautifulSoup(html, "lxml")

    # Extraer texto del blockquote (primer <p>)
    p_tag = soup.find("p")
    text = p_tag.get_text(separator=" ").strip() if p_tag else ""

    # Limpiar el texto (quitar links al final que son del autor)
    text = re.sub(r"\s*pic\.twitter\.com/\S+", "", text)
    text = re.sub(r"\s*https://t\.co/\S+", "", text)
    text = text.strip()

    # Extraer enlaces del <p>
    links = []
    if p_tag:
        for a in p_tag.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") and "twitter.com" not in href and "x.com" not in href:
                links.append(href)

    author_name = data.get("author_name", "")
    author_handle = ""
    # El handle aparece en el texto del último <a> del blockquote: "— Nombre (@handle)"
    match = re.search(r"\(@(\w+)\)", html)
    if match:
        author_handle = match.group(1)

    return TweetData(
        text=text,
        author_name=author_name,
        author_handle=author_handle,
        links=links,
        tweet_url=url,
    )


async def _playwright_impl(url: str) -> TweetData | None:
    """Lógica interna de playwright, ejecutada en su propio event loop."""
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    settings = get_settings()
    parsed_url = parse_x_post_url(url)
    is_article_url = parsed_url.get("kind") == "article"

    async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )

            if settings.x_auth_token and settings.x_ct0:
                await context.add_cookies([
                    {
                        "name": "auth_token",
                        "value": settings.x_auth_token,
                        "domain": ".x.com",
                        "path": "/",
                        "secure": True,
                        "httpOnly": True,
                    },
                    {
                        "name": "ct0",
                        "value": settings.x_ct0,
                        "domain": ".x.com",
                        "path": "/",
                        "secure": True,
                    },
                ])

            page = await context.new_page()

            # Bloquear recursos innecesarios para ir más rápido
            await page.route(
                "**/*.{woff,woff2,ttf,otf}",
                lambda route: route.abort(),
            )

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            try:
                await page.wait_for_selector('[data-testid="tweetText"]', timeout=12000)
            except PWTimeout:
                logger.warning("Timeout esperando tweetText, intentando igualmente")

            # Texto principal
            text = ""
            text_el = page.locator('[data-testid="tweetText"]').first
            if await text_el.count() > 0:
                text = await text_el.inner_text()

            # Autor
            author_name = ""
            author_handle = ""
            user_el = page.locator('[data-testid="User-Name"]').first
            if await user_el.count() > 0:
                full = await user_el.inner_text()
                parts = full.split("\n")
                author_name = parts[0].strip() if parts else ""
                for part in parts:
                    if part.startswith("@"):
                        author_handle = part.strip("@").strip()

            if not author_handle and parsed_url.get("username"):
                author_handle = parsed_url["username"]
            if not author_name and author_handle:
                author_name = author_handle

            # Imágenes/thumbnails del tweet. X cambia seguido su DOM, así que
            # combinamos selectores específicos, metadata y fallback por HTML.
            images: list[str] = []
            media_root = (
                await page.query_selector('article[data-testid="tweet"]')
                or await page.query_selector('[data-testid="tweet"]')
                or page
            )
            media_selectors = [
                '[data-testid="tweetPhoto"] img[src*="twimg.com"]',
                '[data-testid="tweet"] [data-testid="tweetPhoto"] img[src*="twimg.com"]',
                'article [data-testid="tweetPhoto"] img[src*="twimg.com"]',
                '[data-testid="card.wrapper"] img[src*="twimg.com"]',
                '[data-testid="videoComponent"] img[src*="twimg.com"]',
                '[data-testid="videoPlayer"] img[src*="twimg.com"]',
                '[data-testid="previewInterstitial"] img[src*="twimg.com"]',
                'article img[src*="pbs.twimg.com/media"]',
                'article img[src*="video_thumb"]',
                'article img[src*="ext_tw_video_thumb"]',
                'article img[src*="amplify_video_thumb"]',
            ]
            for sel in media_selectors:
                for img in await media_root.query_selector_all(sel):
                    _append_media_url(images, await img.get_attribute("src"))

            # Detección de video y captura de poster.
            await page.wait_for_timeout(1800)

            has_video = False
            for sel in (
                "video",
                '[data-testid="videoComponent"]',
                '[data-testid="videoPlayer"]',
                '[data-testid="playButton"]',
                '[aria-label*="Play"]',
                '[aria-label*="Reproducir"]',
                '[aria-label*="video"]',
                '[aria-label*="Video"]',
            ):
                if await media_root.query_selector(sel):
                    has_video = True
                    break

            for v in await media_root.query_selector_all("video[poster]"):
                _append_media_url(images, await v.get_attribute("poster"))

            if not images:
                for meta_sel in (
                    'meta[property="og:image"]',
                    'meta[name="twitter:image"]',
                    'meta[property="twitter:image"]',
                ):
                    meta = page.locator(meta_sel).first
                    if await meta.count() > 0:
                        _append_media_url(images, await meta.get_attribute("content"))

            if not images:
                for src in _extract_media_urls_from_html(await page.content()):
                    _append_media_url(images, src)

            if any(_is_video_media_url(src) for src in images):
                has_video = True

            # ── Detección de artículos de X (long-form tweets) ─────────────────
            is_article = is_article_url
            article_content = ""
            article_title = ""

            if is_article_url:
                title_el = page.locator('[data-testid="twitter-article-title"]').first
                if await title_el.count() > 0:
                    article_title = (await title_el.inner_text()).strip()

                for article_sel in (
                    '[data-testid="twitterArticleRichTextView"]',
                    '[data-testid="longformRichTextComponent"]',
                    '[data-testid="twitterArticleReadView"]',
                    'main',
                ):
                    el = page.locator(article_sel).first
                    if await el.count() == 0:
                        continue
                    candidate = (await el.inner_text()).strip()
                    if candidate:
                        article_content = candidate
                        break

                if article_title:
                    text = article_title

            # Los artículos de X tienen un contenedor especial con el cuerpo del artículo
            article_selectors = [
                '[data-testid="articleBody"]',
                '[data-testid="article-body"]',
                '[data-testid="tweetArticle"]',
                '[data-testid="twitterArticleRichTextView"]',
                '[data-testid="longformRichTextComponent"]',
            ]
            for art_sel in article_selectors:
                art_els = await page.query_selector_all(art_sel)
                if art_els:
                    parts = []
                    for el in art_els:
                        t = await el.inner_text()
                        if t.strip():
                            parts.append(t.strip())
                    if parts:
                        article_content = "\n\n".join(parts)
                        is_article = True
                        break

            # Fallback: si hay un heading visible dentro del tweet, es artículo
            if not is_article:
                heading_els = await page.query_selector_all(
                    '[data-testid="tweet"] h1, [data-testid="tweet"] h2'
                )
                if heading_els:
                    is_article = True

            # Fallback 2: si el tweet container tiene mucho más texto que tweetText,
            # probablemente es un artículo con cuerpo expandido
            if not is_article:
                try:
                    tweet_container = page.locator('[data-testid="tweet"]').first
                    if await tweet_container.count() > 0:
                        container_text = await tweet_container.inner_text()
                        # Si el container tiene más de 3x el texto del tweet, hay contenido extra
                        if len(container_text.strip()) > max(len(text) * 3, 800):
                            is_article = True
                            article_content = container_text.strip()
                except Exception:
                    pass

            # Si es artículo pero no tenemos article_content aún, usar container completo
            if is_article and not article_content:
                try:
                    tweet_container = page.locator('[data-testid="tweet"]').first
                    if await tweet_container.count() > 0:
                        article_content = (await tweet_container.inner_text()).strip()
                except Exception:
                    pass

            # En artículos largos, a veces no existe tweetText tradicional.
            # Conservamos un teaser útil para no perder el contexto en la app.
            if is_article and not text.strip() and article_content.strip():
                text = _article_teaser(article_content)

            if is_article and article_title and article_title not in article_content:
                article_content = f"{article_title}\n\n{article_content}".strip()

            # Links externos. Muchos papers llegan como t.co, por eso intentamos
            # data-expanded-url, title y expansion HTTP antes de decidir.
            raw_links: list[str] = []
            link_els = await media_root.query_selector_all(
                '[data-testid="tweetText"] a, [data-testid="card.wrapper"] a, article a'
            )
            for a in link_els:
                for attr in ("data-expanded-url", "title", "href"):
                    value = (await a.get_attribute(attr)) or ""
                    value = value.strip()
                    if "arxiv.org/" in value and not value.startswith("http"):
                        value = f"https://{value.lstrip('/')}"
                    if value.startswith("http") and value not in raw_links:
                        raw_links.append(value)

            links: list[str] = []
            for raw in raw_links:
                expanded = await _expand_tco_url(raw)
                if _is_external_content_url(expanded) and expanded not in links:
                    links.append(expanded)

            await browser.close()

            return TweetData(
                text=text.strip(),
                author_name=author_name,
                author_handle=author_handle,
                images=images,
                links=links,
                tweet_url=url,
                has_video=has_video,
                is_article=is_article,
                article_content=article_content,
            )


async def scrape_with_playwright(url: str) -> TweetData | None:
    """Scraping completo con playwright (texto + imágenes).
    En Windows corre en un thread con ProactorEventLoop para soportar subprocesos."""
    try:
        import importlib
        if importlib.util.find_spec("playwright") is None:
            logger.warning("playwright no está instalado")
            return None

        def run_in_thread() -> TweetData | None:
            if sys.platform == "win32":
                loop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(_playwright_impl(url))
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_thread)
            return await asyncio.get_event_loop().run_in_executor(None, future.result)

    except Exception as e:
        logger.error(f"playwright scraping falló: {e}")
        return None


async def fetch_paper_info(url: str) -> dict | None:
    """Intenta obtener información de un paper académico desde la URL."""
    paper: dict = {}

    # arXiv
    arxiv_id = extract_arxiv_id(url)
    if arxiv_id:
        try:
            api_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
            r = await _get_arxiv_url(api_url, timeout=25)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "lxml-xml")
                entry = soup.find("entry")
                if entry:
                    title_tag = entry.find("title")
                    summary_tag = entry.find("summary")
                    authors = [a.find("name").get_text() for a in entry.find_all("author") if a.find("name")]
                    paper = {
                        "title": title_tag.get_text(strip=True) if title_tag else "",
                        "abstract": summary_tag.get_text(strip=True) if summary_tag else "",
                        "authors": authors[:5],
                        "source": "arXiv",
                        "url": url,
                        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                    }
        except Exception as e:
            logger.warning(f"Error fetching arXiv API: {e}")

        if not paper:
            try:
                abs_url = f"https://arxiv.org/abs/{arxiv_id}"
                r = await _get_arxiv_url(abs_url, timeout=25)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "lxml")
                    title_el = soup.select_one("h1.title")
                    abstract_el = soup.select_one("blockquote.abstract")
                    authors_el = soup.select_one(".authors")

                    title = title_el.get_text(" ", strip=True) if title_el else ""
                    abstract = abstract_el.get_text(" ", strip=True) if abstract_el else ""
                    title = re.sub(r"^Title:\s*", "", title).strip()
                    abstract = re.sub(r"^Abstract:\s*", "", abstract).strip()
                    authors: list[str] = []
                    if authors_el:
                        authors = [
                            a.get_text(" ", strip=True)
                            for a in authors_el.find_all("a")
                            if a.get_text(" ", strip=True)
                        ]
                        if not authors:
                            authors_text = re.sub(
                                r"^Authors?:\s*",
                                "",
                                authors_el.get_text(" ", strip=True),
                            )
                            authors = [a.strip() for a in authors_text.split(",") if a.strip()]

                    if title or abstract:
                        paper = {
                            "title": title,
                            "abstract": abstract,
                            "authors": authors[:5],
                            "source": "arXiv",
                            "url": url,
                            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                        }
            except Exception as e:
                logger.warning(f"Error fetching arXiv abs page: {e}")

    return paper if paper else None


async def scrape_tweet(url: str) -> TweetData:
    """
    Punto de entrada principal.
    1. Intenta playwright (texto + imágenes completas)
    2. Fallback a oEmbed (solo texto)
    """
    url = normalize_tweet_url(url)

    # Intento 1: playwright
    result = await scrape_with_playwright(url)

    # Intento 2: oEmbed como fallback
    if result is None or (not result.text and not result.article_content):
        oembed = await fetch_oembed(url)
        if oembed:
            result = parse_oembed(oembed, url)
        else:
            result = TweetData(
                text="No se pudo extraer el contenido del tweet.",
                author_name="",
                author_handle="",
                tweet_url=url,
            )

    # Buscar info de paper si hay links académicos
    for link in result.links:
        if "arxiv.org" in link or "doi.org" in link:
            paper_info = await fetch_paper_info(link)
            if paper_info:
                result.paper_info = paper_info
                if paper_info.get("pdf_url"):
                    result.pdf_url = paper_info["pdf_url"]
                break

    # También detectar PDFs directos en los links
    if not result.pdf_url:
        for link in result.links:
            if link.lower().endswith(".pdf"):
                result.pdf_url = link
                break

    return result
