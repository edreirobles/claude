"""
Cliente LinkedIn API v2.
Maneja autenticación OAuth 2.0, subida de imágenes y publicación de posts.
"""
import httpx
import base64
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

    async def _register_image_upload(self) -> tuple[str, str]:
        """Registra un upload de imagen y devuelve (uploadUrl, asset_urn)."""
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
        """Sube los bytes de la imagen al URL proporcionado por LinkedIn."""
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/octet-stream",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.put(upload_url, content=image_data, headers=headers)
            r.raise_for_status()

    async def _download_image(self, image_url: str) -> bytes | None:
        """Descarga una imagen desde una URL."""
        try:
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                r = await client.get(image_url)
                if r.status_code == 200:
                    return r.content
        except Exception as e:
            logger.warning(f"No se pudo descargar imagen {image_url}: {e}")
        return None

    async def upload_image_from_url(self, image_url: str) -> Optional[str]:
        """Descarga una imagen y la sube a LinkedIn. Retorna el asset URN."""
        image_data = await self._download_image(image_url)
        if not image_data:
            return None
        try:
            upload_url, asset_urn = await self._register_image_upload()
            await self._upload_image_binary(upload_url, image_data)
            return asset_urn
        except Exception as e:
            logger.error(f"Error subiendo imagen a LinkedIn: {e}")
            return None

    async def create_post(
        self,
        text: str,
        image_urls: list[str] | None = None,
        use_first_image: bool = True,
    ) -> dict:
        """
        Crea un post en LinkedIn.
        Si hay imágenes disponibles y use_first_image=True, adjunta la primera.
        """
        asset_urn: str | None = None

        if use_first_image and image_urls:
            for img_url in image_urls[:1]:
                asset_urn = await self.upload_image_from_url(img_url)
                if asset_urn:
                    break

        if asset_urn:
            return await self._create_image_post(text, asset_urn)
        return await self._create_text_post(text)

    async def _create_text_post(self, text: str) -> dict:
        """Crea un post solo de texto."""
        payload = {
            "author": f"urn:li:person:{self.person_urn}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{LINKEDIN_API_BASE}/ugcPosts",
                json=payload,
                headers=self._headers,
            )
            r.raise_for_status()
            return {"post_id": r.headers.get("x-restli-id", ""), "status": "published"}

    async def _create_image_post(self, text: str, asset_urn: str) -> dict:
        """Crea un post con imagen."""
        payload = {
            "author": f"urn:li:person:{self.person_urn}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "IMAGE",
                    "media": [
                        {
                            "status": "READY",
                            "media": asset_urn,
                        }
                    ],
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{LINKEDIN_API_BASE}/ugcPosts",
                json=payload,
                headers=self._headers,
            )
            r.raise_for_status()
            return {"post_id": r.headers.get("x-restli-id", ""), "status": "published"}


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
