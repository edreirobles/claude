"""
Cliente LinkedIn API v2.
Usa el endpoint UGC Posts (v2) para publicar y assets para subir media.
"""
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"


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


    async def get_post_metrics(self, post_id: str) -> dict:
        """
        Obtiene likes y comentarios de un post publicado.

        Para cuentas personales la API de LinkedIn expone socialActions,
        que incluye likes y comentarios. Las impresiones solo están disponibles
        para páginas de empresa (scope r_organization_social), así que se
        retorna None para ese campo en cuentas personales.

        Returns dict: {"likes": int, "comments": int, "impressions": None}
        """
        import urllib.parse

        urn = f"urn:li:ugcPost:{post_id}"
        encoded_urn = urllib.parse.quote(urn, safe="")
        url = f"{LINKEDIN_API_BASE}/socialActions/{encoded_urn}"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(url, headers=self._headers)
                if r.status_code == 200:
                    data = r.json()
                    likes = data.get("likesSummary", {}).get("totalLikes", 0)
                    comments = data.get("commentsSummary", {}).get("totalFirstLevelComments", 0)
                    return {"likes": likes, "comments": comments, "impressions": None}
                logger.warning(f"socialActions devolvió {r.status_code} para {post_id}")
        except Exception as e:
            logger.error(f"Error obteniendo métricas de LinkedIn: {e}")

        return {"likes": None, "comments": None, "impressions": None}


def get_oauth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Genera la URL de autorización OAuth 2.0 de LinkedIn."""
    scope = "openid profile email w_member_social"
    return (
        f"{LINKEDIN_AUTH_URL}"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
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
