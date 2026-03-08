"""
Scraping de métricas de LinkedIn con Playwright.

Usa cookies de sesión (li_at + JSESSIONID) para navegar a cada post
publicado y extraer las estadísticas que LinkedIn muestra al autor:
  - Reacciones (likes)
  - Comentarios
  - Impresiones

Configuración requerida en .env:
    LINKEDIN_LI_AT     → Cookie "li_at" de linkedin.com
    LINKEDIN_JSESSIONID → Cookie "JSESSIONID" (sin las comillas externas)

Cómo obtenerlas:
    1. Abre linkedin.com en Chrome/Firefox, inicia sesión.
    2. F12 → Application → Cookies → https://www.linkedin.com
    3. Copia el Value de "li_at" y "JSESSIONID".
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _parse_li_count(text: str) -> Optional[int]:
    """
    Convierte strings de LinkedIn como '1,234', '1.2K', '4.5M' a int.
    Devuelve None si no puede parsear.
    """
    if not text:
        return None
    text = text.strip().replace(",", "").replace("\xa0", "").replace(" ", "")
    text = re.sub(r"[^\d.KkMm]", "", text)
    try:
        if text.lower().endswith("m"):
            return int(float(text[:-1]) * 1_000_000)
        if text.lower().endswith("k"):
            return int(float(text[:-1]) * 1_000)
        return int(float(text)) if text else None
    except (ValueError, OverflowError):
        return None


async def scrape_linkedin_post_metrics(
    post_id: str,
    li_at: str,
    jsessionid: str = "",
) -> dict:
    """
    Navega a la página del post en LinkedIn y extrae métricas visibles al autor.

    Retorna dict con claves: likes, comments, impressions (int o None).
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.error("[LinkedIn Scraper] playwright no instalado. Ejecuta: pip install playwright && playwright install chromium")
        return {"likes": None, "comments": None, "impressions": None}

    post_url = f"https://www.linkedin.com/feed/update/urn:li:ugcPost:{post_id}/"
    result: dict = {"likes": None, "comments": None, "impressions": None}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="es-MX",
            )

            # Agregar cookies de sesión
            cookies = [
                {
                    "name": "li_at",
                    "value": li_at,
                    "domain": ".linkedin.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                },
            ]
            if jsessionid:
                # LinkedIn almacena JSESSIONID con comillas; normalizar
                raw_jid = jsessionid.strip('"')
                cookies.append({
                    "name": "JSESSIONID",
                    "value": f'"{raw_jid}"',
                    "domain": ".linkedin.com",
                    "path": "/",
                    "secure": True,
                })
            await ctx.add_cookies(cookies)

            page = await ctx.new_page()

            # Ir a la página del post
            try:
                await page.goto(post_url, wait_until="domcontentloaded", timeout=30_000)
            except PWTimeout:
                logger.warning(f"[LinkedIn Scraper] Timeout navegando a {post_url}")
                await browser.close()
                return result

            # Verificar que no fuimos al login
            current = page.url
            if any(x in current for x in ("authwall", "/login", "checkpoint", "/uas/login")):
                logger.warning(
                    "[LinkedIn Scraper] Redirigido al login — "
                    "LINKEDIN_LI_AT expirada o incorrecta. Actualízala en .env"
                )
                await browser.close()
                return result

            # Esperar a que cargue el contenido social
            try:
                await page.wait_for_selector(
                    ".social-details-social-counts, .feed-shared-social-counts, "
                    "[data-test-id='social-counts-reactions']",
                    timeout=12_000,
                )
            except PWTimeout:
                pass  # Continuamos con lo que hay

            # Dar un poco más de tiempo para el JS
            await page.wait_for_timeout(2_000)

            html = await page.content()

            # ── Estrategia 1: JSON embebido en la página ────────────────────────
            # LinkedIn a veces incrusta los conteos en atributos data o JSON-LD
            m = re.search(r'"numLikes"\s*:\s*(\d+)', html)
            if m:
                result["likes"] = int(m.group(1))

            m = re.search(r'"numComments"\s*:\s*(\d+)', html)
            if m:
                result["comments"] = int(m.group(1))

            m = re.search(r'"numViews"\s*:\s*(\d+)', html)
            if m:
                result["impressions"] = int(m.group(1))

            # ── Estrategia 2: selectores del DOM ───────────────────────────────
            # Reacciones
            if result["likes"] is None:
                for sel in [
                    ".social-details-social-counts__reactions-count",
                    "button[aria-label*='reaction'] .artdeco-button__text",
                    "button[aria-label*='Like'] .artdeco-button__text",
                    ".social-details-social-counts__reactions button span[aria-hidden='true']",
                    "span.social-details-social-counts__reactions-count",
                ]:
                    el = await page.query_selector(sel)
                    if el:
                        txt = await el.inner_text()
                        val = _parse_li_count(txt.strip())
                        if val is not None:
                            result["likes"] = val
                            break

            # Comentarios
            if result["comments"] is None:
                for sel in [
                    ".social-details-social-counts__comments",
                    "button[aria-label*='comment']",
                    ".feed-shared-social-counts__num-comments",
                ]:
                    el = await page.query_selector(sel)
                    if el:
                        txt = await el.inner_text()
                        m2 = re.search(r"([\d,]+(?:\.\d+)?[KkMm]?)", txt.replace("\xa0", ""))
                        if m2:
                            result["comments"] = _parse_li_count(m2.group(1))
                            break

            # Impresiones — visibles solo para el autor del post
            if result["impressions"] is None:
                for sel in [
                    ".analytics-entry-point",
                    "a[data-control-name='analytics_post_impression']",
                    "button[aria-label*='impression']",
                    "span[aria-label*='impression']",
                    ".member-analytics-addon-premium-entry-point",
                ]:
                    el = await page.query_selector(sel)
                    if el:
                        txt = await el.inner_text()
                        m2 = re.search(r"([\d,]+(?:\.\d+)?[KkMm]?)", txt.replace("\xa0", ""))
                        if m2:
                            result["impressions"] = _parse_li_count(m2.group(1))
                            break

            # ── Estrategia 3: buscar en el texto de la página ──────────────────
            # LinkedIn renderiza algo como "• 1,234 impresiones" visible al autor
            if result["impressions"] is None:
                m = re.search(
                    r"([\d,]+(?:\.\d+)?[KkMm]?)\s*(?:impression|impresion)",
                    html,
                    re.IGNORECASE,
                )
                if m:
                    result["impressions"] = _parse_li_count(m.group(1))

            logger.info(
                f"[LinkedIn Scraper] Post {post_id} → "
                f"likes={result['likes']}, comments={result['comments']}, "
                f"impressions={result['impressions']}"
            )

            await browser.close()

    except Exception as e:
        logger.error(f"[LinkedIn Scraper] Error inesperado scrapeando post {post_id}: {e}")

    return result
