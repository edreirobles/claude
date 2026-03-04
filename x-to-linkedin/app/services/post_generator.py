"""
Generador de publicaciones LinkedIn usando Claude AI.
Transforma contenido de X en posts atractivos para LinkedIn
sobre IA e IA en educación.
"""
import asyncio
import os
import tempfile
import urllib.parse
import httpx
import logging
import anthropic
from typing import Optional
from .x_scraper import TweetData
from ..config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

SYSTEM_PROMPT_ES = """Eres un experto en comunicación digital especializado en Inteligencia Artificial e IA en educación.
Tu tarea es transformar contenido de X (Twitter) en publicaciones atractivas para LinkedIn.

REGLAS ESTRICTAS:
1. Lenguaje: profesional pero accesible. No técnico en exceso, no super casual.
   - Explica conceptos técnicos en términos que cualquier profesional entienda
   - Usa analogías cuando ayuden
   - Evita jerga innecesaria

2. Estructura del post (máximo 1400 caracteres sin los hashtags):
   [Primera línea impactante - la clave que engancha al lector]

   [2-3 oraciones con el contenido principal y su importancia]

   [Una conclusión o reflexión breve]

   [Si hay imagen/diagrama disponible, mencionarlo naturalmente: "El diagrama adjunto muestra..." o "En la imagen puedes ver..."]

3. Cierra con 3-5 hashtags relevantes separados por espacios:
   #InteligenciaArtificial #IAEducacion #EdTech #AprendizajeAutomatico #Innovacion

4. Si el tweet menciona un paper o investigación, destaca:
   - El hallazgo más importante
   - Por qué importa en la práctica
   - Quiénes se benefician de esto

5. NO copies el tweet textualmente. Transforma y eleva el contenido.
6. NO uses mayúsculas innecesarias ni signos de exclamación múltiples.
7. El post debe generar conversación: puede terminar con una pregunta o reflexión provocadora.

TONO: Como un divulgador de tecnología educativa que habla con colegas inteligentes pero no especialistas.

CASO ESPECIAL — CONTENIDO NO PUBLICABLE:
Si el tweet no tiene suficiente sustancia para crear un post profesional de LinkedIn
(p. ej. es un meme sin contexto, una respuesta suelta sin información, contenido personal
sin valor profesional, spam, o texto vacío/ilegible), responde ÚNICAMENTE con esta línea
y nada más:
[NO_PUBLICAR]: <explicación breve de por qué no es publicable>"""

SYSTEM_PROMPT_EN = """You are a digital communication expert specializing in Artificial Intelligence and AI in education.
Your task is to transform X (Twitter) content into attractive LinkedIn posts.

STRICT RULES:
1. Language: professional but accessible. Not overly technical, not too casual.

2. Post structure (max 1400 characters without hashtags):
   [Impactful first line - the hook that draws the reader in]

   [2-3 sentences with main content and why it matters]

   [Brief conclusion or reflection]

   [If image/diagram available, mention it naturally]

3. Close with 3-5 relevant hashtags:
   #ArtificialIntelligence #AIEducation #EdTech #MachineLearning #Innovation

4. If tweet mentions a paper, highlight the key finding and practical relevance.
5. Do NOT copy the tweet verbatim. Transform and elevate the content.
6. Generate conversation: end with a thought-provoking question or reflection.

SPECIAL CASE — NON-PUBLISHABLE CONTENT:
If the tweet lacks enough substance for a professional LinkedIn post (e.g. a meme with no
context, a loose reply with no information, personal content with no professional value,
spam, or empty/unreadable text), respond ONLY with this line and nothing else:
[NO_PUBLICAR]: <brief reason why it cannot be published>"""


async def generate_linkedin_post(tweet: TweetData, language: str = "es") -> str:
    """Genera una publicación de LinkedIn a partir de los datos del tweet."""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    system_prompt = SYSTEM_PROMPT_ES if language == "es" else SYSTEM_PROMPT_EN

    # Construir el contexto del tweet
    context_parts = [f"Texto del tweet:\n{tweet.text}"]

    if tweet.author_name:
        context_parts.append(f"Autor: {tweet.author_name} (@{tweet.author_handle})")

    if tweet.links:
        context_parts.append(f"Links en el tweet: {', '.join(tweet.links[:3])}")

    if tweet.images:
        n = len(tweet.images)
        context_parts.append(
            f"El tweet incluye {n} imagen{'es' if n > 1 else ''} "
            f"(diagramas/fotos que se pueden adjuntar al post de LinkedIn)."
        )

    if tweet.paper_info:
        pi = tweet.paper_info
        context_parts.append(
            f"\nInformación del paper académico:\n"
            f"Título: {pi.get('title', '')}\n"
            f"Autores: {', '.join(pi.get('authors', []))}\n"
            f"Abstract: {pi.get('abstract', '')[:600]}..."
        )

    context = "\n\n".join(context_parts)

    user_message = (
        f"Genera una publicación de LinkedIn basada en este contenido de X:\n\n{context}"
        if language == "es"
        else f"Generate a LinkedIn post based on this X (Twitter) content:\n\n{context}"
    )

    message = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    generated = message.content[0].text.strip()

    # Agregar fuente al final
    if tweet.tweet_url:
        generated = f"{generated}\n\nFuente: {tweet.tweet_url}"

    return generated


async def generate_free_image(prompt: str) -> Optional[bytes]:
    """
    Genera una imagen gratis usando Pollinations.ai (sin API key).
    Retorna los bytes de la imagen o None si falla.
    """
    # Limpiar y acortar el prompt
    clean_prompt = prompt[:300].replace("\n", " ").strip()
    encoded = urllib.parse.quote(clean_prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1024&height=1024&nologo=true&model=flux"
    )
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                return r.content
            logger.warning(f"Pollinations devolvió status {r.status_code}")
    except Exception as e:
        logger.error(f"Error generando imagen con Pollinations.ai: {e}")
    return None


async def download_tweet_video(tweet_url: str) -> Optional[bytes]:
    """
    Descarga el video de un tweet usando yt-dlp.
    Retorna los bytes del video (MP4) o None si falla.
    """
    try:
        import yt_dlp
    except ImportError:
        logger.warning("yt-dlp no está instalado, no se puede descargar el video")
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        output_template = os.path.join(tmpdir, "video.%(ext)s")
        ydl_opts = {
            "format": "best[ext=mp4]/best[height<=720]/best",
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "max_filesize": 150 * 1024 * 1024,  # 150 MB límite
        }
        try:
            loop = asyncio.get_event_loop()

            def _download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([tweet_url])

            await loop.run_in_executor(None, _download)

            files = os.listdir(tmpdir)
            if files:
                filepath = os.path.join(tmpdir, files[0])
                with open(filepath, "rb") as f:
                    return f.read()
        except Exception as e:
            logger.error(f"Error descargando video con yt-dlp: {e}")
    return None


async def download_pdf(url: str) -> Optional[bytes]:
    """
    Descarga un PDF desde una URL.
    Retorna los bytes del PDF o None si falla.
    """
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
        ) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.content
            logger.warning(f"PDF download devolvió status {r.status_code} para {url}")
    except Exception as e:
        logger.error(f"Error descargando PDF: {e}")
    return None
