"""
Extractor de contenido de X (Twitter).
Usa playwright para obtener texto, imágenes y enlaces del tweet.
Fallback a oEmbed para obtener al menos el texto cuando el browser no está disponible.
"""
import re
import sys
import asyncio
import concurrent.futures
import httpx
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


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


def normalize_tweet_url(url: str) -> str:
    """Convierte twitter.com a x.com y limpia el URL."""
    url = url.strip()
    url = re.sub(r"https?://(www\.)?(twitter|x)\.com", "https://x.com", url)
    url = url.split("?")[0]
    return url


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

            # Imágenes del tweet (no avatares)
            images: list[str] = []
            img_els = await page.query_selector_all('[data-testid="tweetPhoto"] img')
            for img in img_els:
                src = await img.get_attribute("src")
                if src and "twimg.com" in src:
                    # Obtener versión de alta resolución
                    src = re.sub(r"&name=\w+", "&name=large", src)
                    images.append(src)

            # Detección de video y captura de thumbnail
            # Dar tiempo al player de X para renderizar antes de buscar el poster
            await page.wait_for_timeout(1500)

            video_poster_els = await page.query_selector_all("video[poster]")
            has_video = len(video_poster_els) > 0
            for v in video_poster_els:
                poster = await v.get_attribute("poster")
                # Ignorar blob: URLs y URLs vacías
                if poster and poster.startswith("http") and "twimg.com" in poster:
                    # Obtener versión de mayor resolución del thumbnail
                    poster = re.sub(r"&name=\w+", "&name=large", poster)
                    images.append(poster)

            # Si no hay poster, buscar thumbnail en otros elementos del player de X
            if not images or not any("twimg.com" in img for img in images):
                thumb_selectors = [
                    '[data-testid="videoComponent"] img[src*="twimg.com"]',
                    '[data-testid="previewInterstitial"] img[src*="twimg.com"]',
                    'div[data-testid="tweetPhoto"] img[src*="twimg.com"]',
                    'div[aria-label*="video"] img[src*="twimg.com"]',
                ]
                for sel in thumb_selectors:
                    thumb_els = await page.query_selector_all(sel)
                    for el in thumb_els:
                        src = await el.get_attribute("src")
                        if src and "twimg.com" in src and src not in images:
                            src = re.sub(r"&name=\w+", "&name=large", src)
                            images.append(src)
                    if images:
                        break

            # Detectar videos sin poster como fallback
            if not has_video:
                all_video_els = await page.query_selector_all("video")
                has_video = len(all_video_els) > 0

            # Links en el texto
            links: list[str] = []
            link_els = await page.query_selector_all('[data-testid="tweetText"] a')
            for a in link_els:
                href = await a.get_attribute("href")
                if href and href.startswith("http") and "t.co" not in href:
                    links.append(href)

            # t.co links expandidos (el atributo data-expanded-url o title)
            tco_els = await page.query_selector_all("a[data-testid='card.layoutLarge.media']")
            card_els = await page.query_selector_all("[data-testid='card.wrapper'] a")
            for a in card_els:
                href = await a.get_attribute("href")
                if href and href.startswith("http") and "x.com" not in href:
                    links.append(href)

            await browser.close()

            return TweetData(
                text=text.strip(),
                author_name=author_name,
                author_handle=author_handle,
                images=images,
                links=list(set(links)),
                tweet_url=url,
                has_video=has_video,
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
    arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", url)
    if arxiv_match:
        arxiv_id = arxiv_match.group(1)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
                )
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
            logger.warning(f"Error fetching arXiv: {e}")

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
    if result is None or not result.text:
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
