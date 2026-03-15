"""
Generador de publicaciones LinkedIn usando Claude AI.
Transforma contenido de cualquier URL en posts atractivos para LinkedIn.
Si no hay imagen disponible, genera una con Google Imagen.
"""
import logging
from typing import Optional

import anthropic
import httpx

from app.config import settings
from app.services.url_scraper import ScrapedContent

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Eres un experto en comunicación digital y personal branding en LinkedIn.
Tu tarea es transformar contenido de cualquier fuente (artículos, blogs, posts de X, noticias)
en publicaciones atractivas y profesionales para LinkedIn.

REGLAS:
1. Lenguaje: profesional pero accesible. Español de México.
   - "computadora" (no "ordenador"), "celular" (no "móvil")
   - Explica conceptos técnicos con palabras que cualquier profesional entienda

2. Estructura (máximo 1400 caracteres sin hashtags):
   [Primera línea impactante — el gancho]

   [2-4 oraciones con el contenido principal y por qué importa]

   [Cierre: reflexión directa, dato impactante, llamada a acción, o (solo cuando sea natural) una pregunta.
    NO termines siempre con pregunta.]

3. Cierra con 3-5 hashtags relevantes separados por espacios.

4. Si hay investigación o datos, destaca el hallazgo más relevante y su impacto práctico.

5. NO copies el texto original. Transforma y eleva el contenido.
6. NO uses mayúsculas innecesarias ni signos de exclamación repetidos.
7. Menciona la fuente solo si es una persona o institución reconocida que añade valor.

TONO: Profesional que comparte conocimiento valioso con su red, no vendedor."""


async def generate_linkedin_post(content: ScrapedContent) -> str:
    """Genera una publicación de LinkedIn a partir del contenido scrapeado."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    parts = []
    if content.title:
        parts.append(f"Título: {content.title}")
    if content.author:
        parts.append(f"Autor: {content.author}")
    parts.append(f"URL: {content.url}")
    if content.text:
        parts.append(f"\nContenido:\n{content.text}")
    if content.images:
        parts.append(f"\nImágenes disponibles: {len(content.images)}")

    context = "\n".join(parts)

    message = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Genera una publicación de LinkedIn basada en este contenido:\n\n{context}"
        }],
    )

    post = message.content[0].text.strip()
    post = f"{post}\n\nFuente: {content.url}"
    return post


async def generate_image_with_google(prompt: str) -> Optional[str]:
    """
    Genera una imagen usando Google Imagen 3 (via Gemini API).
    Retorna la URL de datos (data URI) o None si falla.
    """
    if not settings.google_api_key:
        logger.warning("GOOGLE_API_KEY no configurada, omitiendo generación de imagen")
        return None

    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"imagen-3.0-generate-002:predict?key={settings.google_api_key}"
        )
        payload = {
            "instances": [{"prompt": prompt[:480]}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": "1:1",
                "safetyFilterLevel": "block_some",
                "personGeneration": "allow_adult",
            },
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        predictions = data.get("predictions", [])
        if predictions and predictions[0].get("bytesBase64Encoded"):
            b64 = predictions[0]["bytesBase64Encoded"]
            mime = predictions[0].get("mimeType", "image/png")
            return f"data:{mime};base64,{b64}"

    except Exception as e:
        logger.error(f"Error generando imagen con Google Imagen: {e}")

    return None


def build_image_prompt(post_text: str, title: str = "") -> str:
    """Genera un prompt de imagen basado en el post."""
    base = title or post_text[:200]
    return (
        f"Professional LinkedIn post illustration for: {base}. "
        "Clean, modern, corporate style. No text overlay. Minimalist design."
    )
