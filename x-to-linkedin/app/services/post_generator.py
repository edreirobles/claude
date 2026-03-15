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


async def generate_linkedin_post(
    tweet: TweetData,
    language: str = "es",
    custom_prompt: Optional[str] = None,
) -> str:
    """Genera una publicación de LinkedIn a partir de los datos del tweet."""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    if custom_prompt:
        system_prompt = custom_prompt
    else:
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


def _build_image_prompt(linkedin_text: str) -> str:
    """
    Construye un prompt visual compacto a partir del texto del post de LinkedIn.
    Extrae la primera línea (gancho) y añade estilo profesional.
    """
    first_line = linkedin_text.strip().split("\n")[0][:180]
    return (
        f"Professional data visualization or conceptual diagram about: {first_line}. "
        "Style: clean minimalist infographic, dark navy background, accent colors purple and teal, "
        "geometric shapes, no people, no text, abstract tech visualization. "
        "High quality, 1:1 aspect ratio."
    )


async def generate_free_image(linkedin_text: str) -> Optional[bytes]:
    """
    Genera una imagen para el post usando:
    1. Google Imagen 3 (si GOOGLE_API_KEY está configurado)
    2. Google Gemini 2.0 Flash image generation (fallback con la misma key)
    3. Pollinations.ai (fallback gratuito sin key)
    """
    img_prompt = _build_image_prompt(linkedin_text)
    key = settings.google_api_key

    if key:
        # ── Intento 1: Google Imagen 3 ──────────────────────────────
        result = await _generate_imagen3(img_prompt, key)
        if result:
            return result

        # ── Intento 2: Gemini 2.0 Flash image generation ────────────
        result = await _generate_gemini_image(img_prompt, key)
        if result:
            return result

        logger.warning("Google API falló para imagen, usando Pollinations como fallback")

    # ── Intento 3: Pollinations.ai (sin API key, gratis) ────────────
    result = await _generate_pollinations(img_prompt)
    if result:
        return result

    # ── Último recurso: placeholder con Pillow ───────────────────────
    logger.warning("generate_free_image: todos los servicios fallaron, usando placeholder con Pillow")
    return _generate_placeholder_image()


async def _generate_imagen3(prompt: str, api_key: str) -> Optional[bytes]:
    """Genera imagen con Google Imagen 3."""
    import base64
    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/imagen-3.0-generate-002:predict?key={api_key}"
    )
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": "1:1"},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                predictions = r.json().get("predictions", [])
                if predictions and "bytesBase64Encoded" in predictions[0]:
                    return base64.b64decode(predictions[0]["bytesBase64Encoded"])
            logger.warning(f"Imagen 3 devolvió {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"Error con Imagen 3: {e}")
    return None


async def _generate_gemini_image(prompt: str, api_key: str) -> Optional[bytes]:
    """Genera imagen con Gemini 2.0 Flash (image generation mode)."""
    import base64
    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/gemini-2.0-flash-preview-image-generation:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                for candidate in r.json().get("candidates", []):
                    for part in candidate.get("content", {}).get("parts", []):
                        if "inlineData" in part:
                            return base64.b64decode(part["inlineData"]["data"])
            logger.warning(f"Gemini image gen devolvió {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"Error con Gemini image gen: {e}")
    return None


async def _generate_pollinations(prompt: str) -> Optional[bytes]:
    """Fallback gratuito: Pollinations.ai. Reintenta hasta 3 veces."""
    encoded = urllib.parse.quote(prompt[:300])
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1024&height=1024&nologo=true&model=flux"
    )
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
                r = await client.get(url)
                ct = r.headers.get("content-type", "")
                if r.status_code == 200 and ct.startswith("image/"):
                    return r.content
                logger.warning(f"Pollinations intento {attempt + 1}: status {r.status_code}, content-type '{ct}'")
        except Exception as e:
            logger.warning(f"Pollinations intento {attempt + 1} error: {e}")
        if attempt < 2:
            await asyncio.sleep(5)
    logger.error("Pollinations.ai falló después de 3 intentos")
    return None


def _generate_placeholder_image() -> Optional[bytes]:
    """Genera imagen de placeholder profesional con Pillow. Último recurso sin internet."""
    try:
        from PIL import Image, ImageDraw
        import io

        w, h = 1024, 1024
        img = Image.new("RGB", (w, h), color=(10, 22, 40))
        draw = ImageDraw.Draw(img)

        # Líneas diagonales de fondo
        for i in range(0, w + h, 80):
            draw.line([(max(0, i - h), min(i, h)), (min(i, w), max(0, i - w))], fill=(20, 45, 75), width=1)

        # Círculos concéntricos (teal)
        draw.ellipse([100, 100, 924, 924], outline=(20, 184, 166), width=2)
        draw.ellipse([200, 200, 824, 824], outline=(20, 184, 166, 150), width=1)

        # Marco interior (purple)
        draw.ellipse([300, 300, 724, 724], outline=(147, 51, 234), width=2)

        # Punto central
        cx, cy = w // 2, h // 2
        draw.ellipse([cx - 70, cy - 70, cx + 70, cy + 70], fill=(147, 51, 234))
        draw.ellipse([cx - 35, cy - 35, cx + 35, cy + 35], fill=(20, 184, 166))
        draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=(255, 255, 255))

        # Acentos en esquinas
        for x, y in [(80, 80), (w - 80, 80), (80, h - 80), (w - 80, h - 80)]:
            draw.rectangle([x - 25, y - 25, x + 25, y + 25], outline=(20, 184, 166), width=2)
            draw.line([(x - 12, y), (x + 12, y)], fill=(20, 184, 166), width=2)
            draw.line([(x, y - 12), (x, y + 12)], fill=(20, 184, 166), width=2)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Error generando placeholder con Pillow: {e}")
        return None


async def generate_nano_banana_image(linkedin_text: str) -> Optional[bytes]:
    """
    Genera una imagen con Nano Banana (Gemini image generation).
    Intenta en orden:
    1. Gemini 2.0 Flash image generation (Nano Banana)
    2. Google Imagen 3
    3. Pollinations.ai (fallback gratuito)
    """
    img_prompt = _build_image_prompt(linkedin_text)
    key = settings.google_api_key

    if key:
        # Intento 1: Gemini 2.0 Flash image generation (Nano Banana)
        result = await _generate_gemini_image(img_prompt, key)
        if result:
            logger.info("Nano Banana: imagen generada con Gemini Flash")
            return result

        # Intento 2: Google Imagen 3
        result = await _generate_imagen3(img_prompt, key)
        if result:
            logger.info("Nano Banana: imagen generada con Imagen 3")
            return result

        logger.warning("Nano Banana: Google API falló, usando Pollinations como fallback")

    # Intento 3: Pollinations.ai
    result = await _generate_pollinations(img_prompt)
    if result:
        logger.info("Nano Banana: imagen generada con Pollinations")
        return result

    # Último recurso: placeholder con Pillow (sin internet, siempre funciona)
    logger.warning("Nano Banana: todos los servicios fallaron, usando placeholder con Pillow")
    return _generate_placeholder_image()


async def download_tweet_video(tweet_url: str) -> Optional[bytes]:
    """
    Descarga el video de un tweet usando yt-dlp con cookies de X para autenticación.
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
            "format": "best[ext=mp4][height<=720]/best[ext=mp4]/best[height<=720]/best",
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "max_filesize": 150 * 1024 * 1024,  # 150 MB
        }

        # Escribir cookies de X en formato Netscape si están disponibles
        cookie_file = None
        try:
            x_auth = settings.x_auth_token
            x_ct0 = settings.x_ct0
            if x_auth:
                cookie_file = os.path.join(tmpdir, "cookies.txt")
                with open(cookie_file, "w") as f:
                    f.write("# Netscape HTTP Cookie File\n")
                    f.write(f".x.com\tTRUE\t/\tTRUE\t2147483647\tauth_token\t{x_auth}\n")
                    f.write(f".twitter.com\tTRUE\t/\tTRUE\t2147483647\tauth_token\t{x_auth}\n")
                    if x_ct0:
                        f.write(f".x.com\tTRUE\t/\tTRUE\t2147483647\tct0\t{x_ct0}\n")
                        f.write(f".twitter.com\tTRUE\t/\tTRUE\t2147483647\tct0\t{x_ct0}\n")
                ydl_opts["cookiefile"] = cookie_file
                logger.info("yt-dlp: usando cookies de X para autenticación")
            else:
                logger.warning("yt-dlp: X_AUTH_TOKEN no configurado, descarga puede fallar en videos privados")
        except Exception as e:
            logger.debug(f"yt-dlp: error preparando cookies: {e}")

        try:
            loop = asyncio.get_event_loop()

            def _download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([tweet_url])

            await loop.run_in_executor(None, _download)

            # Buscar el archivo descargado (ignorar el cookies.txt)
            files = [f for f in os.listdir(tmpdir) if not f.endswith(".txt")]
            if files:
                filepath = os.path.join(tmpdir, files[0])
                with open(filepath, "rb") as f:
                    video_bytes = f.read()
                logger.info(f"yt-dlp: video descargado ({len(video_bytes) // 1024} KB)")
                return video_bytes
            else:
                logger.warning("yt-dlp: no se encontró archivo descargado")
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
