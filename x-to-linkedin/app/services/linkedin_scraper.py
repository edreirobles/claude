"""
Métricas de LinkedIn via API Voyager (API interna de linkedin.com).

LinkedIn Voyager es la API REST que usa la propia web de LinkedIn.
Se autentica con cookies de sesión (li_at + JSESSIONID), igual que
el browser. No requiere Playwright — son llamadas HTTP directas,
más rápidas y confiables.

Configuración en .env:
    LINKEDIN_LI_AT      → Cookie "li_at" de linkedin.com
    LINKEDIN_JSESSIONID → Cookie "JSESSIONID" (sin las comillas del valor)
"""
import re
import httpx
import logging
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)


def _find_int(pattern: str, text: str) -> Optional[int]:
    """Busca el primer int que coincida con el patrón en el texto."""
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def _normalize_post_id(raw_id: str) -> str:
    """
    Normaliza el linkedin_post_id guardado en la BD.
    Puede venir como:
      - "7234567890123456789"              → numérico puro
      - "urn:li:ugcPost:7234567890123456789" → URN completo
    Devuelve siempre el ID numérico.
    """
    raw_id = (raw_id or "").strip()
    if raw_id.startswith("urn:li:ugcPost:"):
        return raw_id.split(":")[-1]
    if raw_id.startswith("urn:li:share:"):
        return raw_id.split(":")[-1]
    return raw_id


def _build_headers(li_at: str, jsessionid: str) -> dict:
    raw_jid = jsessionid.strip('"') if jsessionid else ""
    cookie = f"li_at={li_at}"
    if raw_jid:
        cookie += f'; JSESSIONID="{raw_jid}"'

    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/vnd.linkedin.normalized+json+2.1",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": cookie,
        "Csrf-Token": raw_jid if raw_jid else "ajax:0",
        "x-restli-protocol-version": "2.0.0",
        "x-li-lang": "en_US",
        "Referer": "https://www.linkedin.com/feed/",
    }


async def scrape_linkedin_post_metrics(
    post_id: str,
    li_at: str,
    jsessionid: str = "",
) -> dict:
    """
    Obtiene likes, comentarios e impresiones de un post de LinkedIn
    usando la API Voyager (interna). No necesita Playwright.
    """
    numeric_id = _normalize_post_id(post_id)
    if not numeric_id:
        logger.error(f"[Voyager] post_id inválido: '{post_id}'")
        return {"likes": None, "comments": None, "impressions": None}

    urn = f"urn:li:ugcPost:{numeric_id}"
    encoded_urn = urllib.parse.quote(urn, safe="")
    headers = _build_headers(li_at, jsessionid)

    result: dict = {"likes": None, "comments": None, "impressions": None}

    # Patrones regex para extraer métricas del JSON de respuesta.
    # LinkedIn usa distintos nombres según el endpoint.
    LIKE_PATTERNS = [
        r'"numLikes"\s*:\s*(\d+)',
        r'"totalLikes"\s*:\s*(\d+)',
        r'"likeCount"\s*:\s*(\d+)',
        r'"reactionCount"\s*:\s*(\d+)',
    ]
    COMMENT_PATTERNS = [
        r'"numComments"\s*:\s*(\d+)',
        r'"totalFirstLevelComments"\s*:\s*(\d+)',
        r'"commentCount"\s*:\s*(\d+)',
    ]
    IMPRESSION_PATTERNS = [
        r'"numViews"\s*:\s*(\d+)',
        r'"viewCount"\s*:\s*(\d+)',
        r'"impressionCount"\s*:\s*(\d+)',
        r'"numImpressions"\s*:\s*(\d+)',
    ]

    endpoints = [
        # feed/updates — devuelve el update completo con socialDetail
        f"https://www.linkedin.com/voyager/api/feed/updates/{encoded_urn}",
        # socialActions — like/comment counts directos
        f"https://www.linkedin.com/voyager/api/socialActions/{encoded_urn}",
        # updateSocialDetail — detalle social específico
        f"https://www.linkedin.com/voyager/api/feed/updates/{encoded_urn}/updateSocialDetail",
    ]

    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        for url in endpoints:
            try:
                r = await client.get(url, headers=headers)
                logger.info(f"[Voyager] {url.rsplit('/', 2)[-2]} → HTTP {r.status_code}")

                if r.status_code in (401, 403):
                    logger.warning(
                        "[Voyager] Cookie li_at inválida o expirada — "
                        "actualiza LINKEDIN_LI_AT en .env"
                    )
                    break

                if r.status_code != 200:
                    continue

                text = r.text

                # Buscar cada métrica con todos sus patrones alternativos
                for key, patterns in [
                    ("likes",       LIKE_PATTERNS),
                    ("comments",    COMMENT_PATTERNS),
                    ("impressions", IMPRESSION_PATTERNS),
                ]:
                    if result[key] is None:
                        for pat in patterns:
                            val = _find_int(pat, text)
                            if val is not None:
                                result[key] = val
                                break

                if result["likes"] is not None or result["comments"] is not None:
                    logger.info(
                        f"[Voyager] ✓ Post {numeric_id}: "
                        f"likes={result['likes']}, "
                        f"comments={result['comments']}, "
                        f"impressions={result['impressions']}"
                    )
                    break

            except Exception as e:
                logger.warning(f"[Voyager] Error en {url}: {e}")

    return result


async def debug_post_metrics(
    post_id: str,
    li_at: str,
    jsessionid: str = "",
) -> dict:
    """
    Endpoint de diagnóstico: devuelve el status HTTP y un fragmento
    de la respuesta cruda de cada endpoint Voyager.
    """
    numeric_id = _normalize_post_id(post_id)
    urn = f"urn:li:ugcPost:{numeric_id}"
    encoded_urn = urllib.parse.quote(urn, safe="")
    headers = _build_headers(li_at, jsessionid)

    responses = []
    endpoints = [
        f"https://www.linkedin.com/voyager/api/feed/updates/{encoded_urn}",
        f"https://www.linkedin.com/voyager/api/socialActions/{encoded_urn}",
    ]

    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        for url in endpoints:
            try:
                r = await client.get(url, headers=headers)
                snippet = r.text[:600] if r.text else "(vacío)"
                responses.append({
                    "url": url,
                    "status": r.status_code,
                    "snippet": snippet,
                })
            except Exception as e:
                responses.append({"url": url, "status": "error", "snippet": str(e)})

    return {
        "numeric_id": numeric_id,
        "urn": urn,
        "responses": responses,
    }
