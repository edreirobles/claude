"""
Metricas de LinkedIn via API Voyager (API interna de linkedin.com).

LinkedIn Voyager es la API REST que usa la propia web de LinkedIn.
Se autentica con cookies de sesion (li_at + JSESSIONID), igual que
el browser. No requiere Playwright: son llamadas HTTP directas,
mas rapidas y confiables.

Configuracion en .env:
    LINKEDIN_LI_AT      -> Cookie "li_at" de linkedin.com
    LINKEDIN_JSESSIONID -> Cookie "JSESSIONID" (sin las comillas del valor)
"""
import httpx
import json
import logging
import urllib.parse
from typing import Any, Optional

logger = logging.getLogger(__name__)


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
    if raw_id.startswith("urn:li:activity:"):
        return raw_id.split(":")[-1]
    return raw_id


def _candidate_post_urns(raw_id: str) -> list[str]:
    """
    Devuelve URNs candidatas para el post.

    LinkedIn puede devolver posts publicados como `ugcPost` o como `share`.
    Para ampliar cobertura, intentamos primero el tipo original y luego el alterno.
    """
    raw_id = (raw_id or "").strip()
    if not raw_id:
        return []

    numeric_id = _normalize_post_id(raw_id)
    if raw_id.startswith("urn:li:share:"):
        urns = [raw_id, f"urn:li:ugcPost:{numeric_id}"]
    elif raw_id.startswith("urn:li:ugcPost:"):
        urns = [raw_id, f"urn:li:share:{numeric_id}"]
    elif raw_id.startswith("urn:li:activity:"):
        urns = [raw_id]
    else:
        urns = [f"urn:li:ugcPost:{numeric_id}", f"urn:li:share:{numeric_id}"]

    seen = set()
    ordered: list[str] = []
    for urn in urns:
        if urn and urn not in seen:
            seen.add(urn)
            ordered.append(urn)
    return ordered


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
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": cookie,
        "Csrf-Token": raw_jid if raw_jid else "ajax:0",
        "x-restli-protocol-version": "2.0.0",
        "x-li-lang": "en_US",
        "Referer": "https://www.linkedin.com/feed/",
    }


def _iter_metric_candidates(obj: Any, path: str = "root"):
    if isinstance(obj, dict):
        if any(
            key in obj
            for key in (
                "numLikes",
                "numComments",
                "numViews",
                "numShares",
                "totalLikes",
                "totalFirstLevelComments",
                "likeCount",
                "commentCount",
                "impressionCount",
                "clickCount",
                "shareCount",
            )
        ):
            yield path, obj
        for key, value in obj.items():
            yield from _iter_metric_candidates(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from _iter_metric_candidates(value, f"{path}[{index}]")


def _score_metric_candidate(
    path: str,
    candidate: dict[str, Any],
    numeric_id: str,
    requested_urn: str,
) -> int:
    refs = " ".join(
        str(candidate.get(key) or "")
        for key in ("urn", "entityUrn", "dashEntityUrn")
    )

    score = 0
    if "socialDetail.totalSocialActivityCounts" in path:
        score += 10
    if requested_urn and requested_urn in refs:
        score += 6
    if numeric_id and numeric_id in refs:
        score += 4
    if "comment:" in refs:
        score -= 6

    for key in ("numLikes", "numComments", "numViews", "numShares", "clickCount"):
        if candidate.get(key) is not None:
            score += 1

    return score


def _extract_metric_value(candidate: dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = candidate.get(key)
        if value is not None:
            return int(value)
    return None


def _extract_metrics_from_payload(
    payload: dict[str, Any],
    numeric_id: str,
    requested_urn: str,
) -> dict[str, Optional[int]]:
    best_candidate = None
    best_score = None

    for path, candidate in _iter_metric_candidates(payload):
        score = _score_metric_candidate(path, candidate, numeric_id, requested_urn)
        if best_score is None or score > best_score:
            best_score = score
            best_candidate = candidate

    if not best_candidate:
        return {
            "likes": None,
            "comments": None,
            "impressions": None,
            "clicks": None,
            "shares": None,
        }

    likes = _extract_metric_value(best_candidate, "numLikes", "totalLikes", "likeCount")
    comments = _extract_metric_value(
        best_candidate,
        "numComments",
        "totalFirstLevelComments",
        "commentCount",
    )
    impressions = _extract_metric_value(
        best_candidate,
        "numViews",
        "viewCount",
        "impressionCount",
        "numImpressions",
    )
    clicks = _extract_metric_value(best_candidate, "clickCount")
    shares = _extract_metric_value(best_candidate, "numShares", "shareCount")

    return {
        "likes": likes,
        "comments": comments,
        "impressions": impressions,
        "clicks": clicks,
        "shares": shares,
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
    urn_candidates = _candidate_post_urns(post_id)
    if not numeric_id or not urn_candidates:
        logger.error(f"[Voyager] post_id inválido: '{post_id}'")
        return {
            "likes": None,
            "comments": None,
            "impressions": None,
            "clicks": None,
            "shares": None,
        }

    headers = _build_headers(li_at, jsessionid)

    empty = {
        "likes": None,
        "comments": None,
        "impressions": None,
        "clicks": None,
        "shares": None,
    }

    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        for urn in urn_candidates:
            encoded_urn = urllib.parse.quote(urn, safe="")
            url = f"https://www.linkedin.com/voyager/api/feed/updates/{encoded_urn}"
            try:
                r = await client.get(url, headers=headers)
                logger.info(f"[Voyager] feed/updates {urn} -> HTTP {r.status_code}")

                if r.status_code in (401, 403):
                    logger.warning(
                        "[Voyager] Cookie li_at invalida o expirada; "
                        "actualiza LINKEDIN_LI_AT en .env"
                    )
                    break

                if r.status_code != 200:
                    continue

                payload = r.json()
                result = _extract_metrics_from_payload(payload, numeric_id, urn)

                if any(value is not None for value in result.values()):
                    logger.info(
                        f"[Voyager] OK post {numeric_id} via {urn}: "
                        f"likes={result['likes']}, "
                        f"comments={result['comments']}, "
                        f"impressions={result['impressions']}, "
                        f"shares={result['shares']}"
                    )
                    return result
            except Exception as e:
                logger.warning(f"[Voyager] Error en {url}: {e}")

    return empty


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
    urn_candidates = _candidate_post_urns(post_id)
    headers = _build_headers(li_at, jsessionid)

    responses = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        for urn in urn_candidates:
            encoded_urn = urllib.parse.quote(urn, safe="")
            url = f"https://www.linkedin.com/voyager/api/feed/updates/{encoded_urn}"
            try:
                r = await client.get(url, headers=headers)
                snippet = r.text[:600] if r.text else "(vacio)"
                metrics = None
                if r.status_code == 200:
                    try:
                        metrics = _extract_metrics_from_payload(r.json(), numeric_id, urn)
                    except json.JSONDecodeError:
                        metrics = None
                responses.append({
                    "urn": urn,
                    "url": url,
                    "status": r.status_code,
                    "snippet": snippet,
                    "metrics": metrics,
                })
            except Exception as e:
                responses.append(
                    {"urn": urn, "url": url, "status": "error", "snippet": str(e)}
                )

    return {
        "numeric_id": numeric_id,
        "urn_candidates": urn_candidates,
        "responses": responses,
    }
