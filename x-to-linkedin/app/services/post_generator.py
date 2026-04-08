"""
Generador de publicaciones LinkedIn usando Claude AI.
Transforma contenido de X en posts atractivos para LinkedIn
sobre IA e IA en educación.
"""
import asyncio
import os
import re
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
Tu tarea es transformar contenido en publicaciones atractivas para LinkedIn.

REGLAS:
1. Lenguaje: profesional pero accesible. Usa vocabulario de español de México.
   - "computadora" (no "ordenador"), "celular" (no "móvil"), "manejar" (no "conducir"), etc.
   - Explica conceptos técnicos con palabras que cualquier profesional entienda
   - Usa analogías cuando ayuden a clarificar
   - Evita jerga innecesaria

2. Estructura (máximo 1400 caracteres sin los hashtags):
   [PRIMERA LÍNEA: empieza DIRECTO con el dato, hallazgo o idea más importante.
    Sin preámbulos como "Les comparto...", "Hoy aprendí...", "Acabo de leer...".
    El gancho ES el contenido, no una introducción al contenido.]

   [2-4 oraciones desarrollando el punto central y por qué importa en la práctica]

   [Cierre: varía la forma — reflexión directa, observación provocadora, dato de impacto,
    o (solo cuando sea genuinamente relevante) una pregunta que invite a debate real.
    NO termines siempre con pregunta. NO pidas opiniones de forma genérica.
    Si hay algo que naturalmente provoque discusión, déjalo ahí sin forzarlo.]

   [Si hay imagen o diagrama disponible, mencionarlo de forma natural]

3. Cierra con 2-3 hashtags relevantes separados por espacios. Menos es más.
   Elige los más específicos y útiles para el tema, no los más genéricos.
   Ejemplos: #IAEducacion #EdTech #AprendizajeAutomatico

4. Si el contenido menciona un paper o investigación, destaca:
   - El hallazgo más relevante en términos concretos
   - Por qué importa en la práctica
   - A quién beneficia

5. NO copies el texto fuente textualmente. Transforma y eleva el contenido.
6. NO uses mayúsculas innecesarias ni signos de exclamación repetidos.

SOBRE ARROBADOS (@menciones):
- Si el contenido proviene de una empresa, investigador o institución reconocida, menciona
  su nombre en el texto para que el autor pueda etiquetar manualmente (ej: "según OpenAI",
  "el equipo de Google DeepMind").
- NO inventes menciones de personas que no aparecen en el contenido fuente.

SOBRE CITAR AL AUTOR:
- Solo menciona a quien escribió el tweet si es una persona o institución reconocida
  cuya voz añade valor al mensaje (investigador destacado, empresa líder, organismo oficial, etc.).
- Si es un usuario sin relevancia pública para el tema, NO lo menciones.
- Cuando sí cites, hazlo de forma natural dentro del texto, no como nota al pie.

TONO: Divulgador de tecnología educativa hablando con colegas inteligentes, no especialistas.

CASO ESPECIAL — CONTENIDO NO PUBLICABLE:
Si el contenido no tiene sustancia suficiente para un post profesional de LinkedIn
(meme sin contexto, respuesta suelta sin información, contenido personal sin valor
profesional, spam, o texto vacío/ilegible), responde ÚNICAMENTE con:
[NO_PUBLICAR]: <explicación breve de por qué no es publicable>"""

SYSTEM_PROMPT_EN = """You are a digital communication expert specializing in Artificial Intelligence and AI in education.
Your task is to transform content into attractive LinkedIn posts.

STRICT RULES:
1. Language: professional but accessible. Not overly technical, not too casual.

2. Post structure (max 1400 characters without hashtags):
   [FIRST LINE: start DIRECTLY with the key insight, finding, or idea.
    No preambles like "I just read...", "Today I learned...", "Sharing this...".
    The hook IS the content, not an intro to the content.]

   [2-3 sentences developing the main point and why it matters in practice]

   [Closing: vary the form — direct reflection, provocative observation, impactful stat,
    or (only when genuinely relevant) a question that invites real debate.
    Do NOT always end with a question. Do NOT generically ask for opinions.
    If the content naturally sparks discussion, let it do so organically.]

   [If image/diagram available, mention it naturally]

3. Close with 2-3 relevant hashtags. Less is more. Choose specific, useful ones.
   Examples: #AIEducation #EdTech #MachineLearning

4. If content mentions a paper, highlight the key finding and practical relevance.
5. Do NOT copy the source text verbatim. Transform and elevate the content.

ABOUT MENTIONS:
- If the content comes from a recognizable company or researcher, name them in the text
  so the author can manually tag them (e.g., "according to OpenAI", "Google DeepMind's team").

SPECIAL CASE — NON-PUBLISHABLE CONTENT:
If the content lacks enough substance for a professional LinkedIn post (e.g. a meme with no
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

    # Si es un artículo largo de X, usar el contenido completo del artículo
    if tweet.is_article and tweet.article_content:
        # Limitar a 4000 chars para no saturar el prompt
        article_excerpt = tweet.article_content[:4000]
        if len(tweet.article_content) > 4000:
            article_excerpt += "…"
        context_parts.append(
            f"\n⚠️ Este tweet es un ARTÍCULO LARGO de X. Contenido completo del artículo:\n{article_excerpt}"
        )

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
        timeout=90.0,
    )

    generated = message.content[0].text.strip()

    # Agregar fuente al final
    if tweet.tweet_url:
        generated = f"{generated}\n\nFuente: {tweet.tweet_url}"

    return generated


async def generate_linkedin_post_from_url_content(
    url_content,  # UrlContent dataclass from url_scraper
    language: str = "es",
    custom_prompt: Optional[str] = None,
) -> str:
    """
    Genera una publicación de LinkedIn a partir del contenido de una URL genérica
    (artículo, blog, noticia, etc.).
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    if custom_prompt:
        system_prompt = custom_prompt
    else:
        system_prompt = SYSTEM_PROMPT_ES if language == "es" else SYSTEM_PROMPT_EN

    context_parts = []

    if url_content.title:
        context_parts.append(f"Título: {url_content.title}")

    if url_content.author:
        context_parts.append(f"Autor: {url_content.author}")

    if url_content.source_domain:
        context_parts.append(f"Fuente: {url_content.source_domain}")

    if url_content.text:
        context_parts.append(f"Contenido:\n{url_content.text}")

    if url_content.images:
        n = len(url_content.images)
        context_parts.append(
            f"La página incluye {n} imagen{'es' if n > 1 else ''} "
            f"que se pueden adjuntar al post de LinkedIn."
        )

    context = "\n\n".join(context_parts)

    user_message = (
        f"Genera una publicación de LinkedIn basada en este artículo/contenido web:\n\n{context}"
        if language == "es"
        else f"Generate a LinkedIn post based on this web article/content:\n\n{context}"
    )

    message = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        timeout=90.0,
    )

    generated = message.content[0].text.strip()

    # Agregar fuente al final
    if url_content.url:
        generated = f"{generated}\n\nFuente: {url_content.url}"

    return generated


def _build_image_prompt(linkedin_text: str) -> str:
    """
    Prompt de imagen genérico como fallback (sin llamada a Claude).
    Se usa cuando no hay API key o falla la versión inteligente.
    """
    first_line = linkedin_text.strip().split("\n")[0][:180]
    return (
        f"Professional data visualization or conceptual diagram about: {first_line}. "
        "Style: clean minimalist infographic, dark navy background, accent colors purple and teal, "
        "geometric shapes, no people, no text, abstract tech visualization. "
        "High quality, 1:1 aspect ratio."
    )


async def _build_image_prompt_smart(linkedin_text: str) -> str:
    """
    Usa Claude para generar un prompt de imagen específico y relevante
    al contenido del post. Produce imágenes mucho más contextuales.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=220,
            messages=[{
                "role": "user",
                "content": (
                    "Based on this LinkedIn post, write an image generation prompt "
                    "for a professional visual (illustration or diagram). Rules:\n"
                    "- Describe a SPECIFIC scene or visualization directly related to the topic\n"
                    "- NO text, letters, words, or numbers in the image\n"
                    "- NO human faces or recognizable people\n"
                    "- Style: clean professional infographic, minimalist, suitable for LinkedIn\n"
                    "- Be concrete: describe shapes, colors, objects, metaphors — not just 'abstract tech'\n"
                    "- Max 100 words. Output ONLY the prompt, nothing else.\n\n"
                    f"POST:\n{linkedin_text[:1200]}"
                ),
            }],
            timeout=20.0,
        )
        prompt = msg.content[0].text.strip()
        if prompt:
            logger.info(f"Image prompt generado: {prompt[:120]}…")
            return prompt
    except Exception as e:
        logger.warning(f"_build_image_prompt_smart falló, usando fallback: {e}")
    return _build_image_prompt(linkedin_text)


async def generate_free_image(linkedin_text: str) -> Optional[bytes]:
    """
    Genera una imagen para el post usando:
    1. Google Imagen 3 (si GOOGLE_API_KEY está configurado)
    2. Google Gemini 2.0 Flash image generation (fallback con la misma key)
    3. Pollinations.ai (fallback gratuito sin key)
    """
    img_prompt = await _build_image_prompt_smart(linkedin_text)
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
    """
    Genera imagen con Google Imagen 3.
    Intenta primero imagen-3.0-generate-001, luego imagen-3.0-fast-generate-001 como fallback.
    """
    import base64
    models = [
        "imagen-3.0-generate-001",
        "imagen-3.0-fast-generate-001",  # Nano Banana Pro — más rápido
        "imagen-3.0-generate-002",        # alias anterior
    ]
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": "1:1"},
    }
    for model in models:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta"
            f"/models/{model}:predict?key={api_key}"
        )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(url, json=payload)
                if r.status_code == 200:
                    predictions = r.json().get("predictions", [])
                    if predictions and "bytesBase64Encoded" in predictions[0]:
                        logger.info(f"Imagen generada con {model}")
                        return base64.b64decode(predictions[0]["bytesBase64Encoded"])
                logger.warning(f"{model} devolvió {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.warning(f"Error con {model}: {e}")
    return None


async def _generate_gemini_image(prompt: str, api_key: str) -> Optional[bytes]:
    """
    Genera imagen con Gemini (imagen nativa).
    Intenta varios modelos en orden de preferencia.
    """
    import base64
    # Modelos en orden de preferencia (más nuevos primero)
    models = [
        "gemini-2.0-flash-preview-image-generation",
        "gemini-2.0-flash-exp-image-generation",
        "gemini-2.0-flash-exp",
    ]
    # Payload estándar para generación de imagen
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
            "temperature": 1.0,
        },
    }
    for model in models:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta"
            f"/models/{model}:generateContent?key={api_key}"
        )
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                r = await client.post(url, json=payload)
                if r.status_code == 200:
                    data = r.json()
                    for candidate in data.get("candidates", []):
                        for part in candidate.get("content", {}).get("parts", []):
                            if "inlineData" in part:
                                mime = part["inlineData"].get("mimeType", "image/png")
                                img_bytes = base64.b64decode(part["inlineData"]["data"])
                                if len(img_bytes) > 1000:  # imagen real, no vacía
                                    logger.info(f"Gemini imagen OK con {model} ({len(img_bytes) // 1024} KB)")
                                    return img_bytes
                    logger.warning(f"Gemini {model}: respuesta 200 pero sin imagen en candidates")
                else:
                    logger.warning(f"Gemini {model} devolvió {r.status_code}: {r.text[:300]}")
        except httpx.TimeoutException:
            logger.warning(f"Gemini {model}: timeout")
        except Exception as e:
            logger.warning(f"Error con Gemini {model}: {e}")
    return None


async def _generate_pollinations(prompt: str) -> Optional[bytes]:
    """Fallback gratuito: Pollinations.ai. Intenta múltiples seeds y URLs."""
    import random
    encoded = urllib.parse.quote(prompt[:300])
    seed = random.randint(1, 99999)

    # Intentar con distintos parámetros en cada intento
    url_variants = [
        f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&nofeed=true&model=flux&seed={seed}",
        f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&nofeed=true&seed={seed}",
        f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&nofeed=true",
    ]

    for attempt, url in enumerate(url_variants):
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                r = await client.get(url)
                ct = r.headers.get("content-type", "")
                if r.status_code == 200 and ct.startswith("image/") and len(r.content) > 5000:
                    logger.info(f"Pollinations: imagen OK en intento {attempt + 1} ({len(r.content) // 1024} KB)")
                    return r.content
                logger.warning(
                    f"Pollinations intento {attempt + 1}: status={r.status_code}, "
                    f"ct='{ct}', size={len(r.content)}"
                )
        except httpx.TimeoutException:
            logger.warning(f"Pollinations intento {attempt + 1}: timeout")
        except Exception as e:
            logger.warning(f"Pollinations intento {attempt + 1} error: {e}")
        if attempt < len(url_variants) - 1:
            await asyncio.sleep(3)

    logger.error("Pollinations.ai falló en todos los intentos")
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
    img_prompt = await _build_image_prompt_smart(linkedin_text)
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


async def generate_linkedin_post_from_topic(
    topic: str,
    notes: str = "",
    language: str = "es",
    custom_prompt: Optional[str] = None,
) -> str:
    """
    Genera un post de LinkedIn a partir de un tema libre, usando web search
    para enriquecer el contenido con información actual.
    Retorna el texto del post generado.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    if custom_prompt:
        system_prompt = custom_prompt
    else:
        system_prompt = SYSTEM_PROMPT_ES if language == "es" else SYSTEM_PROMPT_EN

    # Construir el mensaje al usuario
    parts = [
        f"Genera un post profesional de LinkedIn sobre el siguiente tema:",
        f"\n**Tema:** {topic}",
    ]
    if notes.strip():
        parts.append(f"\n**Datos o contexto adicional:** {notes.strip()}")

    if language == "es":
        parts.append(
            "\n\nBusca en internet información actual, estadísticas recientes o ejemplos "
            "concretos sobre este tema para enriquecer el post. Si encuentras un dato "
            "relevante de 2024 o 2025, inclúyelo de forma natural."
        )
    else:
        parts.append(
            "\n\nSearch the web for current information, recent stats, or concrete examples "
            "about this topic to enrich the post. If you find relevant 2024/2025 data, "
            "include it naturally."
        )

    user_message = "".join(parts)
    messages = [{"role": "user", "content": user_message}]

    # Intentar con web search tool
    try:
        generated = await _generate_with_web_search(client, system_prompt, messages)
        if generated:
            return generated
    except Exception as e:
        logger.warning(f"Web search generation falló ({type(e).__name__}: {e}), usando knowledge base")

    # Fallback: sin web search, solo knowledge base de Claude
    response = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
        timeout=90.0,
    )
    return response.content[0].text.strip()


async def _generate_with_web_search(
    client: anthropic.AsyncAnthropic,
    system_prompt: str,
    messages: list,
    max_iterations: int = 6,
) -> Optional[str]:
    """
    Ejecuta el loop de tool_use para web_search y retorna el texto final.
    Usa claude-sonnet-4-6 para menor costo en búsquedas.
    """
    tools = [{"type": "web_search_20250305", "name": "web_search"}]

    for i in range(max_iterations):
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            tools=tools,
            messages=messages,
            timeout=120.0,
        )

        if response.stop_reason == "end_turn":
            texts = [
                block.text
                for block in response.content
                if hasattr(block, "text") and block.text
            ]
            result = "\n".join(texts).strip()
            if result:
                logger.info(f"Web search generation completada en {i + 1} iteraciones")
                return result
            return None

        if response.stop_reason == "tool_use":
            messages = list(messages)  # copia local
            messages.append({"role": "assistant", "content": response.content})

            # Construir tool_results — para server tools (web_search) la API
            # ya ejecutó la búsqueda; sólo necesitamos confirmar cada tool_use
            tool_results = []
            for block in response.content:
                if getattr(block, "type", "") == "tool_use":
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "",
                    })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            else:
                # Sin tool_use blocks, algo inesperado
                break
        else:
            logger.warning(f"Web search: stop_reason inesperado '{response.stop_reason}'")
            break

    return None


async def suggest_linkedin_topics(language: str = "es") -> list[str]:
    """
    Sugiere 6 temas tendencia en IA y EdTech para crear posts de LinkedIn.
    Retorna lista de strings con títulos de temas.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    if language == "es":
        user_msg = (
            "Sugiere exactamente 6 temas de tendencia en Inteligencia Artificial y tecnología educativa "
            "(EdTech) que serían interesantes para publicar en LinkedIn hoy. "
            "El público objetivo son profesionales de educación, tecnología y negocios en México y Latinoamérica.\n\n"
            "Formato de respuesta: una lista numerada, un tema por línea, máximo 12 palabras por tema. "
            "Solo la lista, sin explicaciones adicionales. Incluye el ángulo específico, no solo el tema genérico.\n\n"
            "Ejemplo de formato:\n"
            "1. Cómo los agentes de IA están reemplazando tareas de analistas en finanzas\n"
            "2. Por qué el 70% de los estudiantes prefieren tutores de IA sobre humanos\n"
            "..."
        )
    else:
        user_msg = (
            "Suggest exactly 6 trending topics in Artificial Intelligence and EdTech "
            "that would be interesting to post on LinkedIn today. "
            "Target audience: education, tech, and business professionals.\n\n"
            "Response format: numbered list, one topic per line, max 12 words each. "
            "Just the list, no additional explanations. Include a specific angle, not just a generic topic.\n\n"
            "Example format:\n"
            "1. How AI agents are replacing analyst tasks in finance\n"
            "2. Why 70% of students prefer AI tutors over human ones\n"
            "..."
        )

    tools = [{"type": "web_search_20250305", "name": "web_search"}]
    messages = [{"role": "user", "content": user_msg}]

    try:
        result_text = await _generate_with_web_search(
            client,
            "Eres un experto en tendencias de IA y tecnología educativa. Respondes con listas concisas.",
            messages,
        )
    except Exception:
        result_text = None

    if not result_text:
        # Fallback sin web search
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=messages,
            timeout=30.0,
        )
        result_text = response.content[0].text.strip()

    # Parsear la lista
    topics = []
    for line in result_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Quitar numeración: "1. ", "1) ", "• ", "- ", etc.
        cleaned = re.sub(r"^[\d]+[.)]\s*|^[-•*]\s*", "", line).strip()
        if cleaned and len(cleaned) > 5:
            topics.append(cleaned)
    return topics[:8]  # máximo 8


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
