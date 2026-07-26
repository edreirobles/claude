"""
Cliente LinkedIn API v2.
Usa el endpoint UGC Posts (v2) para publicar y assets para subir media.
"""
from datetime import datetime
import httpx
import logging
from typing import Optional
import urllib.parse
import json

logger = logging.getLogger(__name__)
from ..config import get_settings

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
settings = get_settings()


def _candidate_post_urns(post_id: str) -> list[str]:
    post_id = (post_id or "").strip()
    if not post_id:
        return []

    if post_id.startswith("urn:li:share:"):
        numeric_id = post_id.split(":")[-1]
        urns = [post_id, f"urn:li:ugcPost:{numeric_id}"]
    elif post_id.startswith("urn:li:ugcPost:"):
        numeric_id = post_id.split(":")[-1]
        urns = [post_id, f"urn:li:share:{numeric_id}"]
    else:
        numeric_id = post_id
        urns = [f"urn:li:ugcPost:{numeric_id}", f"urn:li:share:{numeric_id}"]

    deduped: list[str] = []
    seen = set()
    for urn in urns:
        if urn not in seen:
            seen.add(urn)
            deduped.append(urn)
    return deduped


class LinkedInClient:
    def __init__(self, access_token: str, person_urn: str):
        self.access_token = access_token
        self.person_urn = person_urn
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    async def get_profile(self) -> dict:
        """Obtiene información del perfil del usuario."""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{LINKEDIN_API_BASE}/userinfo",
                headers=self._headers,
            )
            r.raise_for_status()
            return r.json()

    # ── Image upload ───────────────────────────────────────────────────────

    async def _register_image_upload(self) -> tuple[str, str]:
        """Registra un upload de imagen. Retorna (uploadUrl, asset_urn)."""
        payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": f"urn:li:person:{self.person_urn}",
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{LINKEDIN_API_BASE}/assets?action=registerUpload",
                json=payload,
                headers=self._headers,
            )
            r.raise_for_status()
            data = r.json()
            upload_url = data["value"]["uploadMechanism"][
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
            ]["uploadUrl"]
            asset_urn = data["value"]["asset"]
            return upload_url, asset_urn

    async def _upload_image_binary(self, upload_url: str, image_data: bytes) -> None:
        """Sube los bytes de la imagen al URL de LinkedIn."""
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/octet-stream",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.put(upload_url, content=image_data, headers=headers)
            r.raise_for_status()

    async def _download_image(self, image_url: str) -> bytes | None:
        """Descarga una imagen desde una URL (incluyendo CDN de Twitter)."""
        try:
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                    "Referer": "https://twitter.com/",
                },
            ) as client:
                r = await client.get(image_url)
                if r.status_code == 200:
                    return r.content
                logger.warning(f"Descarga de imagen devolvió {r.status_code}: {image_url}")
        except Exception as e:
            logger.warning(f"No se pudo descargar imagen {image_url}: {e}")
        return None

    async def upload_image_from_url(self, image_url: str) -> Optional[str]:
        """Descarga una imagen y la sube a LinkedIn. Retorna el asset URN."""
        image_data = await self._download_image(image_url)
        if not image_data:
            logger.warning(f"Descarga fallida, no se adjuntará imagen: {image_url}")
            return None
        try:
            upload_url, asset_urn = await self._register_image_upload()
            await self._upload_image_binary(upload_url, image_data)
            return asset_urn
        except Exception as e:
            logger.error(f"Error subiendo imagen a LinkedIn: {e}")
            return None

    async def upload_image_bytes(self, image_bytes: bytes) -> Optional[str]:
        """Sube bytes de imagen directamente a LinkedIn. Retorna el asset URN."""
        try:
            upload_url, asset_urn = await self._register_image_upload()
            await self._upload_image_binary(upload_url, image_bytes)
            return asset_urn
        except Exception as e:
            logger.error(f"Error subiendo imagen generada a LinkedIn: {e}")
            return None

    # ── Video upload ───────────────────────────────────────────────────────

    async def _register_video_upload(self) -> tuple[str, str]:
        """Registra upload de video. Retorna (uploadUrl, asset_urn)."""
        payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-video"],
                "owner": f"urn:li:person:{self.person_urn}",
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{LINKEDIN_API_BASE}/assets?action=registerUpload",
                json=payload,
                headers=self._headers,
            )
            r.raise_for_status()
            data = r.json()
            upload_url = data["value"]["uploadMechanism"][
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
            ]["uploadUrl"]
            asset_urn = data["value"]["asset"]
            return upload_url, asset_urn

    async def upload_video_bytes(self, video_bytes: bytes) -> Optional[str]:
        """Sube video a LinkedIn. Retorna el asset URN o None si falla."""
        try:
            upload_url, asset_urn = await self._register_video_upload()
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/octet-stream",
            }
            async with httpx.AsyncClient(timeout=180) as client:
                r = await client.put(upload_url, content=video_bytes, headers=headers)
                r.raise_for_status()
            return asset_urn
        except Exception as e:
            logger.error(f"Error subiendo video a LinkedIn: {e}")
            return None

    # ── Document upload ────────────────────────────────────────────────────

    async def _register_document_upload(self) -> tuple[str, str]:
        """Registra upload de documento PDF. Retorna (uploadUrl, asset_urn)."""
        payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-document"],
                "owner": f"urn:li:person:{self.person_urn}",
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{LINKEDIN_API_BASE}/assets?action=registerUpload",
                json=payload,
                headers=self._headers,
            )
            r.raise_for_status()
            data = r.json()
            upload_url = data["value"]["uploadMechanism"][
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
            ]["uploadUrl"]
            asset_urn = data["value"]["asset"]
            return upload_url, asset_urn

    async def upload_document_bytes(self, pdf_bytes: bytes) -> Optional[str]:
        """Sube documento PDF a LinkedIn. Retorna el asset URN o None si falla."""
        try:
            upload_url, asset_urn = await self._register_document_upload()
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/pdf",
            }
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.put(upload_url, content=pdf_bytes, headers=headers)
                r.raise_for_status()
            return asset_urn
        except Exception as e:
            logger.error(f"Error subiendo documento a LinkedIn: {e}")
            return None

    # ── Post creation ──────────────────────────────────────────────────────

    async def _ugc_post(self, payload: dict) -> dict:
        """Envía un ugcPost a LinkedIn y retorna el resultado."""
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{LINKEDIN_API_BASE}/ugcPosts",
                json=payload,
                headers=self._headers,
            )
            r.raise_for_status()
            return {"post_id": r.headers.get("x-restli-id", ""), "status": "published"}

    async def _create_text_post(self, text: str) -> dict:
        """Crea un post de solo texto."""
        return await self._ugc_post({
            "author": f"urn:li:person:{self.person_urn}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        })

    async def _create_image_post(self, text: str, asset_urn: str) -> dict:
        """Crea un post con imagen."""
        return await self._ugc_post({
            "author": f"urn:li:person:{self.person_urn}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "IMAGE",
                    "media": [{"status": "READY", "media": asset_urn}],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        })

    async def _create_video_post(self, text: str, asset_urn: str) -> dict:
        """Crea un post con video."""
        return await self._ugc_post({
            "author": f"urn:li:person:{self.person_urn}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "VIDEO",
                    "media": [{"status": "READY", "media": asset_urn}],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        })

    async def _create_document_post(self, text: str, asset_urn: str, title: str = "Documento") -> dict:
        """Crea un post con documento PDF."""
        return await self._ugc_post({
            "author": f"urn:li:person:{self.person_urn}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "DOCUMENT",
                    "media": [
                        {
                            "status": "READY",
                            "media": asset_urn,
                            "title": {"text": title},
                        }
                    ],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        })

    # ── Main entry point ───────────────────────────────────────────────────

    async def create_post(
        self,
        text: str,
        image_urls: list[str] | None = None,
        use_first_image: bool = True,
        video_bytes: bytes | None = None,
        document_bytes: bytes | None = None,
        document_title: str = "Documento",
        generated_image_bytes: bytes | None = None,
    ) -> dict:
        """
        Crea un post en LinkedIn con el tipo de media apropiado.
        Prioridad: video > documento > imagen (URL) > imagen generada > texto solo.
        """
        # 1. Video
        if video_bytes:
            asset_urn = await self.upload_video_bytes(video_bytes)
            if asset_urn:
                return await self._create_video_post(text, asset_urn)
            logger.warning("Upload de video falló, intentando con imagen")

        # 2. Documento PDF
        if document_bytes:
            asset_urn = await self.upload_document_bytes(document_bytes)
            if asset_urn:
                return await self._create_document_post(text, asset_urn, document_title)
            logger.warning("Upload de documento falló, publicando sin PDF")

        # 3. Imagen desde URL (tweet original)
        if use_first_image and image_urls:
            asset_urn = await self.upload_image_from_url(image_urls[0])
            if asset_urn:
                return await self._create_image_post(text, asset_urn)

        # 4. Imagen generada con IA
        if generated_image_bytes:
            asset_urn = await self.upload_image_bytes(generated_image_bytes)
            if asset_urn:
                return await self._create_image_post(text, asset_urn)

        # 5. Solo texto
        return await self._create_text_post(text)

    async def create_comment(
        self,
        *,
        target_urn: str,
        object_urn: str,
        text: str,
        parent_comment_urn: str | None = None,
    ) -> dict:
        """
        Publica un comentario o respuesta usando Social Actions.

        Primero intenta el endpoint v2, que hoy sigue aceptando este flujo
        para cuentas con `w_member_social`. Si LinkedIn rechaza ese formato
        o endpoint, cae al endpoint REST nuevo como respaldo.

        `target_urn` suele ser el URN del post (`share` o `ugcPost`).
        `object_urn` debe ser el URN del thread subyacente, normalmente
        `urn:li:activity:...`, que obtenemos del comentario original.
        """
        attempts: list[tuple[str, str]] = []
        if parent_comment_urn:
            # Para respuestas anidadas, LinkedIn espera que el target del path
            # sea el commentUrn padre y que el object en el body apunte al post.
            attempts.append((parent_comment_urn, target_urn))
            if object_urn and object_urn != target_urn:
                attempts.append((parent_comment_urn, object_urn))
        else:
            attempts.append((target_urn, object_urn or target_urn))
            if target_urn and object_urn and object_urn != target_urn:
                attempts.append((target_urn, target_urn))

        last_error: Exception | None = None
        response = None
        data = None

        async with httpx.AsyncClient(timeout=20) as client:
            for request_target, request_object in attempts:
                payload = {
                    "actor": f"urn:li:person:{self.person_urn}",
                    "object": request_object,
                    "message": {"text": text},
                }
                if parent_comment_urn:
                    payload["parentComment"] = parent_comment_urn

                encoded_target = urllib.parse.quote(request_target, safe="")
                endpoint_variants = [
                    (
                        "v2",
                        f"{LINKEDIN_API_BASE}/socialActions/{encoded_target}/comments",
                        self._headers,
                    ),
                    (
                        "rest",
                        f"https://api.linkedin.com/rest/socialActions/{encoded_target}/comments",
                        {
                            **self._headers,
                            "Linkedin-Version": self._rest_api_version(),
                        },
                    ),
                ]

                for api_family, url, headers in endpoint_variants:
                    try:
                        response = await client.post(url, headers=headers, json=payload)
                        response.raise_for_status()
                        data = response.json()
                        break
                    except httpx.HTTPStatusError as exc:
                        last_error = RuntimeError(
                            self._format_linkedin_http_error(
                                exc,
                                context=(
                                    "respuesta a comentario"
                                    if parent_comment_urn
                                    else "comentario"
                                ),
                            )
                        )
                        # LinkedIn cambia entre endpoints y tipos de URN.
                        # Si rechaza la forma del target/body o el endpoint
                        # concreto, probamos el siguiente candidato.
                        if exc.response.status_code in {400, 403, 404, 405, 409, 422}:
                            logger.warning(
                                "LinkedIn rechazo create_comment family=%s target=%s object=%s status=%s",
                                api_family,
                                request_target,
                                request_object,
                                exc.response.status_code,
                            )
                            continue
                        raise last_error from exc
                    except Exception as exc:
                        last_error = exc
                        raise

                if data is not None and response is not None:
                    break

        if data is None or response is None:
            if last_error:
                raise last_error
            raise RuntimeError("LinkedIn no devolvió respuesta al crear el comentario")

        return {
            "comment_id": response.headers.get("x-restli-id", ""),
            "comment_urn": data.get("commentUrn", "") or data.get("$URN", "") or data.get("urn", ""),
            "status": "published",
            "raw": data,
        }

    @staticmethod
    def _rest_api_version() -> str:
        version = (settings.linkedin_api_version or "").strip()
        if len(version) == 6 and version.isdigit():
            return version
        return "202604"

    @staticmethod
    def _format_linkedin_http_error(exc: httpx.HTTPStatusError, *, context: str) -> str:
        status = exc.response.status_code
        detail = ""
        try:
            payload = exc.response.json()
            if isinstance(payload, dict):
                pieces = [
                    str(payload.get("message") or "").strip(),
                    str(payload.get("code") or "").strip(),
                    str(payload.get("status") or "").strip(),
                ]
                detail = " | ".join(piece for piece in pieces if piece)
                if not detail:
                    detail = json.dumps(payload, ensure_ascii=False)
            else:
                detail = str(payload)
        except Exception:
            detail = exc.response.text

        detail = " ".join((detail or "").split())
        if detail:
            detail = detail[:500]
            return f"LinkedIn devolvió {status} al publicar la {context}: {detail}"
        return f"LinkedIn devolvió {status} al publicar la {context}"

    async def get_post_metrics(self, post_id: str) -> dict:
        """
        Obtiene métricas de un post publicado.

        Estrategia:
        1. Voyager API (cookies li_at/JSESSIONID) — devuelve likes, comentarios
           e impresiones para cuentas personales sin scopes adicionales.
        2. shareStatistics API v2 — requiere r_member_social scope. Devuelve
           likes, comentarios, impresiones, clicks y shares.
        3. socialActions API v2 — fallback final, solo likes/comentarios.
        """
        import urllib.parse
        from ..config import get_settings
        settings = get_settings()

        empty = {"likes": None, "comments": None, "impressions": None,
                 "clicks": None, "shares": None}

        # Normalizar post_id (quitar prefijo URN si viene así)
        numeric_id = post_id
        if numeric_id.startswith("urn:li:ugcPost:"):
            numeric_id = numeric_id.split(":")[-1]
        elif numeric_id.startswith("urn:li:share:"):
            numeric_id = numeric_id.split(":")[-1]
        urn_candidates = _candidate_post_urns(post_id)

        # ── Intento 1: Voyager API (cookies) ───────────────────────────────
        if settings.linkedin_li_at:
            try:
                from .linkedin_scraper import scrape_linkedin_post_metrics
                metrics = await scrape_linkedin_post_metrics(
                    post_id=post_id,
                    li_at=settings.linkedin_li_at,
                    jsessionid=settings.linkedin_jsessionid,
                )
                if any(v is not None for v in metrics.values()):
                    return {**empty, **metrics}
                logger.warning(
                    f"[LinkedIn] Voyager no extrajo métricas para {numeric_id}, "
                    "intentando con shareStatistics API..."
                )
            except Exception as e:
                logger.warning(f"[LinkedIn] Voyager falló ({e}), intentando API...")

        # ── Intento 2: shareStatistics API v2 (requiere r_member_social) ───
        # Devuelve: likeCount, commentCount, impressionCount, clickCount, shareCount
        try:
            person_urn_encoded = urllib.parse.quote(
                f"urn:li:person:{self.person_urn}", safe=""
            )
            async with httpx.AsyncClient(timeout=15) as client:
                for post_urn in urn_candidates:
                    share_urn_encoded = urllib.parse.quote(post_urn, safe="")
                    stats_url = (
                        f"{LINKEDIN_API_BASE}/shareStatistics"
                        f"?q=authors"
                        f"&authors[0]={person_urn_encoded}"
                        f"&shares[0]={share_urn_encoded}"
                    )
                    r = await client.get(stats_url, headers=self._headers)
                    if r.status_code == 200:
                        data = r.json()
                        elements = data.get("elements", [])
                        if elements:
                            stats = elements[0].get("totalShareStatistics", {})
                            result = {
                                "likes": stats.get("likeCount"),
                                "comments": stats.get("commentCount"),
                                "impressions": stats.get("impressionCount"),
                                "clicks": stats.get("clickCount"),
                                "shares": stats.get("shareCount"),
                            }
                            if any(v is not None for v in result.values()):
                                logger.info(
                                    f"[LinkedIn] shareStatistics OK {post_urn}: {result}"
                                )
                                return result
                    else:
                        logger.warning(
                            f"[LinkedIn] shareStatistics devolvio {r.status_code} para {post_urn}. "
                            f"Si es 403, reconecta LinkedIn para obtener el scope r_member_social."
                        )
        except Exception as e:
            logger.warning(f"[LinkedIn] shareStatistics falló ({e}), intentando socialActions...")

        # ── Intento 3: socialActions (solo likes/comentarios, requiere r_member_social) ──
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                for post_urn in urn_candidates:
                    encoded_urn = urllib.parse.quote(post_urn, safe="")
                    url = f"{LINKEDIN_API_BASE}/socialActions/{encoded_urn}"
                    r = await client.get(url, headers=self._headers)
                    if r.status_code == 200:
                        data = r.json()
                        result = {
                            "likes": data.get("likesSummary", {}).get("totalLikes"),
                            "comments": data.get("commentsSummary", {}).get("totalFirstLevelComments"),
                            "impressions": None,
                            "clicks": None,
                            "shares": None,
                        }
                        if any(v is not None for v in result.values()):
                            return result
                    logger.warning(f"[LinkedIn] socialActions devolvio {r.status_code} para {post_urn}")
        except Exception as e:
            logger.error(f"[LinkedIn] Error en socialActions: {e}")

        return empty


def get_oauth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Genera la URL de autorización OAuth 2.0 de LinkedIn."""
    # `w_member_social` basta para publicar posts, comentarios y respuestas.
    # `r_member_social` es un permiso cerrado y hoy no debe pedirse aquí
    # porque rompe la reautorización para apps sin esa aprobación especial.
    scope = "openid profile email w_member_social"
    return (
        f"{LINKEDIN_AUTH_URL}"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&state={state}"
        f"&scope={scope.replace(' ', '%20')}"
    )


async def exchange_code_for_token(
    code: str, client_id: str, client_secret: str, redirect_uri: str
) -> dict:
    """Intercambia el código de autorización por un access token."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        return r.json()


async def exchange_refresh_token_for_token(
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str = "",
) -> dict:
    """Intercambia un refresh token por un nuevo access token."""
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if redirect_uri:
        payload["redirect_uri"] = redirect_uri

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            LINKEDIN_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        return r.json()
