"""
Scraper de perfil público de X.

Dado un @username, obtiene las URLs de los tweets más recientes
de su perfil usando Playwright (sin autenticación, perfil público).

No necesita API key ni cookies de sesión.
"""
import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TweetRef:
    tweet_id: str
    tweet_url: str
    author_handle: str


async def get_recent_tweet_urls(username: str, max_tweets: int = 5) -> list[TweetRef]:
    """
    Navega al perfil público de x.com/{username} y extrae las URLs
    de los últimos tweets (excluye respuestas y retweets).

    Retorna lista de TweetRef ordenada de más reciente a más antiguo.
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.error("playwright no está instalado")
        return []

    username = username.lstrip("@")
    profile_url = f"https://x.com/{username}"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )

            page = await context.new_page()

            # Bloquear fuentes y otros recursos pesados
            await page.route("**/*.{woff,woff2,ttf,otf}", lambda r: r.abort())

            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)

            try:
                await page.wait_for_selector('[data-testid="tweet"]', timeout=15000)
            except PWTimeout:
                current_url = page.url
                if "login" in current_url or "i/flow" in current_url:
                    logger.warning(
                        f"X redirigió al login al visitar @{username}. "
                        "El perfil puede ser privado o X está bloqueando scraping."
                    )
                else:
                    logger.warning(f"Timeout esperando tweets del perfil @{username}")
                await browser.close()
                return []

            # Extraer links con patrón /{username}/status/{id}
            refs: list[TweetRef] = []
            seen_ids: set[str] = set()

            link_els = await page.query_selector_all(f'a[href*="/{username}/status/"]')
            for el in link_els:
                href = await el.get_attribute("href")
                if not href:
                    continue

                # Solo tweets directos del perfil, no respuestas (evitar /with_replies)
                match = re.match(rf"^/{re.escape(username)}/status/(\d+)$", href, re.IGNORECASE)
                if not match:
                    continue

                tweet_id = match.group(1)
                if tweet_id in seen_ids:
                    continue
                seen_ids.add(tweet_id)

                refs.append(TweetRef(
                    tweet_id=tweet_id,
                    tweet_url=f"https://x.com/{username}/status/{tweet_id}",
                    author_handle=username,
                ))

                if len(refs) >= max_tweets:
                    break

            await browser.close()
            logger.info(f"@{username}: {len(refs)} tweets recientes encontrados")
            return refs

    except Exception as e:
        logger.error(f"Error scrapeando perfil de @{username}: {e}")
        return []
