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
from app.config import settings

logger = logging.getLogger(__name__)



DEFAULT_SYSTEM_PROMPT = """Eres un experto en comunicación digital especializado en Inteligencia Artificial e IA en educación.
Tu tarea es transformar contenido de X (Twitter) en publicaciones atractivas para LinkedIn.

REGLAS:
1. Lenguaje: profesional pero accesible. Usa vocabulario de español de México.
   - "computadora" (no "ordenador"), "celular" (no "móvil"), "manejar" (no "conducir"), etc.
   - Explica conceptos técnicos con palabras que cualquier profesional entienda
   - Usa analogías cuando ayuden a clarificar
   - Evita jerga innecesaria

2. Estructura (máximo 1400 caracteres sin los hashtags):
   [Primera línea impactante: el gancho que engancha al lector]

   [2-4 oraciones con el contenido principal y por qué importa]

   [Cierre: varía la forma — puede ser una reflexión directa, una observación provocadora,
    un dato impactante, una invitación a actuar, o (solo cuando sea natural) una pregunta.
    NO termines siempre con pregunta.]

   [Si hay imagen o diagrama disponible, mencionarlo de forma natural]

3. Cierra con 3-5 hashtags relevantes separados por espacios.
   Ejemplos: #InteligenciaArtificial #IAEducacion #EdTech #AprendizajeAutomatico #Innovacion

4. Si el tweet menciona un paper o investigación, destaca:
   - El hallazgo más relevante
   - Por qué importa en la práctica
   - A quién beneficia

5. NO copies el tweet textualmente. Transforma y eleva el contenido.
6. NO uses mayúsculas innecesarias ni signos de exclamación repetidos.

SOBRE CITAR AL AUTOR:
- Solo menciona a quien escribió el tweet si es una persona o institución reconocida
  cuya voz añade valor al mensaje (investigador destacado, empresa líder, organismo oficial, etc.).
- Si es un usuario sin relevancia pública para el tema, NO lo menciones. El contenido habla por sí solo.
- Cuando sí cites, hazlo de forma natural dentro del texto, no como nota al pie.

TONO: Divulgador de tecnología educativa hablando con colegas inteligentes, no especialistas.

CASO ESPECIAL — CONTENIDO NO PUBLICABLE:
Si el tweet no tiene sustancia suficiente para un post profesional de LinkedIn
(meme sin contexto, respuesta suelta sin información, contenido personal sin valor
profesional, spam, o texto vacío/ilegible), responde ÚNICAMENTE con:
[NO_PUBLICAR]: <explicación breve de por qué no es publicable>"""

SYSTEM_PROMPT_EN = """You are a digital communication expert specializing in Artificial Intelligence and AI in education.
Your task is to transform X (Twitter) content into attractive LinkedIn posts.

RULES:
1. Language: professional but accessible. Not overly technical, not too casual.

2. Post structure (max 1400 characters without hashtags):
   [Impactful first line — the hook]
   [2-4 sentences with main content and why it matters]
   [Varied closing — can be a direct reflection, provocative observation, call to action,
    or (only when natural) a question. Do NOT always end with a question.]
   [If image/diagram available, mention it naturally]

3. Close with 3-5 relevant hashtags.

4. If tweet mentions a paper, highlight the key finding and practical relevance.
5. Do NOT copy the tweet verbatim. Transform and elevate the content.

ABOUT CITING THE AUTHOR:
- Only credit the tweet author if they are a notable person or institution whose voice
  adds value (prominent researcher, leading company, official body, etc.).
- If they are not publicly relevant to the topic, do NOT mention them. Let the content speak.

SPECIAL CASE — NON-PUBLISHABLE CONTENT:
Respond ONLY with this if the tweet lacks substance:
[NO_PUBLICAR]: <brief reason>"""


async def generate_linkedin_post(
    tweet: TweetData,
    language: str = "es",
    custom_prompt: Optional[str] = None,
) -> str:
    """Genera una publicación de LinkedIn a partir de los datos del tweet."""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    if custom_prompt:
        system_prompt = custom_prompt
    elif language == "es":
        system_prompt = DEFAULT_SYSTEM_PROMPT
    else:
        system_prompt = SYSTEM_PROMPT_EN

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
