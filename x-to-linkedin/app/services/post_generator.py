"""
Generador de publicaciones LinkedIn usando Claude AI.
Transforma contenido de X en posts atractivos para LinkedIn
sobre IA e IA en educación.
"""
import asyncio
import json
import os
import tempfile
import urllib.parse
import re
import httpx
import logging
import anthropic
from typing import Optional
from .x_scraper import TweetData
from ..config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

VISUAL_RECIPES = {
    "education": {
        "label": "aprendizaje y tutoría",
        "palette": "ivory, terracotta, deep blue, muted gold",
        "colors": [(244, 239, 226), (201, 109, 74), (36, 68, 112), (207, 171, 89)],
        "composition": (
            "top-down editorial still life of an open notebook turning into branching learning paths, "
            "lesson cards, and modular knowledge blocks"
        ),
        "motifs": "paper textures, tabs, study tools, layered cards, light beams, clear focal point",
        "lighting": "soft morning light with crisp shadows",
        "materials": "paper, matte plastic, brushed metal",
    },
    "multimodal": {
        "label": "multimodalidad y video generado desde documentos",
        "palette": "cobalt, amber, parchment, charcoal",
        "colors": [(30, 71, 154), (224, 151, 61), (242, 232, 216), (44, 46, 53)],
        "composition": (
            "cinematic composition where blank source cards, audio waves, and stacked image frames transform into an immersive visual system"
        ),
        "motifs": "blank storyboard frames, paper fragments, motion trails, luminous edges, layered depth",
        "lighting": "studio lighting with cinematic contrast",
        "materials": "paper, glass, matte acrylic",
    },
    "agents": {
        "label": "agentes, desarrollo y sistemas de software",
        "palette": "graphite, electric cyan, amber, off-white",
        "colors": [(35, 39, 46), (78, 205, 196), (244, 162, 97), (239, 236, 230)],
        "composition": (
            "isometric conceptual workspace with modular nodes, cables, translucent blocks, and clear orchestration flows around a central build system"
        ),
        "motifs": "network links, translucent blocks, chips, cables, modular containers, no documents, no dashboards",
        "lighting": "clean directional light with subtle reflections",
        "materials": "anodized metal, matte glass, soft plastic",
    },
    "promptcraft": {
        "label": "prompt engineering y diseño de instrucciones",
        "palette": "sand, ink, vermilion, ultramarine",
        "colors": [(232, 220, 198), (44, 48, 60), (201, 76, 76), (69, 104, 220)],
        "composition": (
            "editorial desk scene with layered blank instruction tiles, aligned blocks, arrows, and a single strong organizing grid"
        ),
        "motifs": "blank tiles, brackets as shapes, layered frames, modular blocks, deliberate spacing",
        "lighting": "gallery lighting with soft highlights",
        "materials": "paper, vellum, matte lacquer",
    },
    "research": {
        "label": "papers, evidencia y síntesis de literatura",
        "palette": "warm white, oxblood, midnight blue, stone",
        "colors": [(245, 242, 237), (132, 38, 54), (33, 49, 73), (157, 149, 138)],
        "composition": (
            "editorial collage of blank research sheets, evidence tiles, citation trails, and magnified geometry arranged around one decisive insight"
        ),
        "motifs": "stacked blank sheets, highlighted bands as shapes, magnifier, nodes, diagrams without labels",
        "lighting": "library light with high clarity and quiet drama",
        "materials": "paper, ink, acetate, brushed steel",
    },
    "creativity": {
        "label": "creatividad, diversidad de ideas y homogeneización",
        "palette": "ink, coral, sunflower, teal",
        "colors": [(32, 36, 48), (231, 111, 81), (233, 196, 106), (42, 157, 143)],
        "composition": (
            "split-scene editorial illustration where a field of diverse shapes gradually collapses into a uniform pattern"
        ),
        "motifs": "contrasting clusters, converging paths, compressed shapes, tension between variety and sameness",
        "lighting": "bold side lighting with strong depth",
        "materials": "paper cutouts, matte resin, textured board",
    },
    "general": {
        "label": "idea compleja de IA explicada visualmente",
        "palette": "warm gray, indigo, rust, cream",
        "colors": [(232, 228, 220), (62, 74, 137), (182, 96, 70), (245, 242, 236)],
        "composition": (
            "clean editorial still life built around one central metaphor with layered objects and negative space"
        ),
        "motifs": "geometric objects, subtle motion lines, paper layers, restrained depth",
        "lighting": "soft directional light",
        "materials": "paper, matte ceramic, brushed aluminum",
    },
}

SYSTEM_PROMPT_ES = """Eres un experto en comunicación digital especializado en Inteligencia Artificial e IA en educación.
Tu tarea es transformar contenido de X (Twitter) en publicaciones atractivas para LinkedIn.

REGLAS:
1. Lenguaje: profesional pero accesible. Usa vocabulario de español de México.
   - "computadora" (no "ordenador"), "celular" (no "móvil"), "manejar" (no "conducir"), etc.
   - Explica conceptos técnicos con palabras que cualquier profesional entienda
   - Usa analogías cuando ayuden a clarificar
   - Evita jerga innecesaria

2. Estructura (máximo 1400 caracteres sin los hashtags):
   - Decide la estructura según la fuente. No todo debe ser reflexión.
   - Puede ser presentación de herramienta, explicación de noticia, hallazgo de paper,
     buena práctica, invitación a probar o análisis breve.
   - Varía la apertura, el desarrollo y el cierre entre publicaciones.
   - Si no hay imagen real o documento adjunto, mejora la primera línea como frase ancla
     para que el texto por sí solo invite a leer.
   - No cierres siempre con pregunta.

3. Cierra con 3-5 hashtags relevantes separados por espacios.
   Ejemplos: #InteligenciaArtificial #IAEducacion #EdTech #AprendizajeAutomatico #Innovacion

4. Si el tweet menciona un paper o investigación, destaca:
   - El hallazgo más relevante
   - Por qué importa en la práctica
   - A quién beneficia

5. NO copies el tweet textualmente. Transforma y eleva el contenido.
6. NO uses mayúsculas innecesarias ni signos de exclamación repetidos.
7. NO uses markdown, asteriscos, viñetas ni guiones medios.

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

CORE_SYSTEM_PROMPT_ES = """Eres un redactor senior de LinkedIn especializado en inteligencia artificial e IA en educación.
Escribe en español de México, con tono profesional, claro y humano.
Transforma fuentes de X o web en posts originales para LinkedIn.
Devuelve solo el post final.
Máximo 1700 caracteres.
Cierra con 3 hashtags relevantes.
No copies la fuente literalmente.
No uses markdown.
No menciones que hay una imagen adjunta si la fuente la trae.
Decide el tipo de post según la fuente. No todo debe llevar a una reflexión.
Puedes explicar una noticia, presentar una herramienta, describir una buena práctica,
invitar a probar algo concreto, advertir un riesgo o abrir una pregunta, según lo que tenga más valor.
Varia la estructura entre publicaciones. Evita repetir siempre el mismo ritmo de gancho,
desarrollo y cierre reflexivo.
Solo cita al autor si su nombre realmente aporta valor al mensaje.
La fuente no puede quedar invisible.
Integra dentro del cuerpo el caso, actor, paper, producto, estudio, experimento o hallazgo concreto que dispara el post.
Quiero que el lector entienda de qué hecho específico estás hablando, no solo la reflexión derivada.
Abre anclado en el hecho concreto. En el primer bloque debe aparecer con naturalidad la empresa, producto, paper, estudio, experimento o autor relevante.
Si el post no tendrá imagen ni documento adjunto, cuida especialmente la primera línea como frase ancla:
debe dar ganas de seguir leyendo sin sonar a clickbait.
No escondas al protagonista detrás de frases vagas como "una herramienta", "un estudio", "una investigación", "una empresa" o "un modelo" cuando sí sabes de cuál hablas.
No pegues URLs dentro del cuerpo del post.
La última línea debe ser exactamente: Fuente: <URL de la fuente>.
La línea de fuente va al final, separada del cuerpo por un salto en blanco.
No inventes experiencia personal. No escribas como si el autor hubiera probado, usado, abierto, implementado o visto directamente una herramienta salvo que el contexto indique claramente experiencia propia.
Si no hay evidencia de experiencia directa, plantea el post como análisis, escenario profesional, lectura de la fuente o recomendación práctica.
La experiencia directa solo debe asumirse en LLMs o herramientas de Google cuando el contexto lo haga razonable. Para otras herramientas, evita primera persona y segunda persona testimonial.
Si la fuente es un paper o artículo académico, no expliques de dónde salió dentro del cuerpo. No escribas "en arXiv", "los autores", "las autoras" ni nombres de autores. Como máximo menciona el nombre del paper una vez y luego desarrolla el contenido.
Si la fuente no tiene sustancia para un post serio, responde solo:
[NO_PUBLICAR]: <motivo breve>"""

CORE_SYSTEM_PROMPT_EN = """You are a senior LinkedIn writer focused on artificial intelligence and AI in education.
Write in a professional, clear, human voice.
Turn X or web sources into original LinkedIn posts.
Return only the final post.
Keep it under 1700 characters.
Close with 3 relevant hashtags.
Do not copy the source verbatim.
Do not use markdown.
Only name the original author when that identity adds real value.
The source cannot stay invisible.
Integrate the concrete actor, paper, product, experiment, study, or finding into the body of the post.
Do not paste URLs inside the body of the post.
The last line must be exactly: Fuente: <source URL>.
If the source is not substantial enough, reply only with:
[NO_PUBLICAR]: <brief reason>"""

STORYTELLING_GUARDRAILS_ES = """
REGLAS NO NEGOCIABLES DE NATURALIDAD Y VOZ:
- El post debe sonar escrito por una persona con criterio, no por una herramienta que resume fuentes.
- No hagas un resumen general de toda la fuente. Elige un ángulo, una tensión o una idea central.
- No escribas como ficha técnica, changelog, abstract ni comunicado.
- Si la fuente es una herramienta o buena práctica, puedes presentarla y describirla con claridad, pero no la conviertas en lista de funciones.
- No enumeres funcionalidades ni uses secuencias mecánicas del tipo "ofrece, permite, incluye".
- Construye una progresión natural. Puede ser narrativa, descriptiva, práctica, analítica o invitacional, según la fuente.
- El primer bloque debe aterrizar el caso concreto, no abrir en abstracto.
- El segundo párrafo debe profundizar o girar la idea, no repetir el gancho con otras palabras.
- Puedes usar datos, pero al servicio de una idea.
- Explica por qué importa, qué cambia en la práctica o cómo conviene usarlo. No fuerces una reflexión si el mejor post es presentar o invitar.
- Evita tono grandilocuente, exagerado o marketinero.
- No uses markdown, no uses asteriscos, no uses títulos internos ni etiquetas como "gancho", "cierre" o similares.
- No uses listas, viñetas ni numeraciones.
- No uses guiones medios ni guiones largos para introducir ideas.
- No uses dos puntos dentro del cuerpo del post.
- Evita punto y coma salvo que de verdad haga falta. El ritmo debe sentirse conversado, no ensayístico.
- No uses frases tipo "la documentación explica", "el artículo presenta", "la guía describe" o "X lanzó Y" como eje del texto.
- No escondas la fuente detrás de expresiones vagas como "una herramienta", "un paper", "una empresa", "un laboratorio" o "un estudio" si el nombre concreto aporta contexto.
- Si la fuente es documentación oficial, convierte el contenido en una observación útil, una tensión práctica o una implicación estratégica. No resumas la página.
- Si la fuente es documentación oficial, evita nombres de endpoints, parámetros, payloads, estados, enums o campos de respuesta salvo que el post pierda sentido sin ese detalle.
- Si la fuente es documentación oficial, no conviertas el post en walkthrough, tutorial ni lista de capacidades.
- Si la fuente es documentación oficial, casi nunca necesitas mencionar API, SDK, JSON, schema, timeout, backoff, service_tier, custom_id, contenedores o memoria. Si aparece algo de eso, debe quedar subordinado a una idea humana, organizacional o pedagógica.
- Si la fuente es un paper o estudio, evita sonar a abstract. Cuenta qué hallazgo cambia algo y cómo obliga a pensar distinto.
- La fuente debe sentirse presente dentro del copy. Nombra o describe el caso concreto sin pegar la URL dentro del cuerpo.
- El post debe cerrar con una línea final separada que diga Fuente: <URL>.
- Usa frases de distinta longitud. Algunas pueden ser breves. Pero que suenen naturales.
- No cierres por inercia con pregunta. Solo hazlo si de verdad abre una reflexión interesante.
- No cierres por inercia con una moraleja. A veces el cierre debe ser una invitación concreta, una descripción útil o una consecuencia práctica.
- No te pongas demasiado técnico. Si la fuente es técnica, tradúcela a una implicación humana, práctica o estratégica.
- No cierres con checklist, memo operativo ni lista de implementación.
- No abras por costumbre con fórmulas como "OpenAI publicó", "Anthropic lanzó", "Google presentó" o "la documentación de X muestra". Si nombras a la fuente, que sea para aterrizar una tensión o un hallazgo, no para anunciar una novedad como boletín.
- No suenes como si estuvieras vendiendo una feature. Suena como alguien que ya masticó la idea y luego la contó.
- No inventes experiencia personal. Evita frases como "probé", "abrí", "entré", "me pasó", "le pedí", "usé" o "en mi experiencia" cuando la fuente no demuestra que el autor realmente lo vivió.
- Si el post habla de una herramienta que el autor no necesariamente ha probado, usa escenarios en tercera persona, lectura analítica o recomendaciones prácticas sin fingir uso propio.
- No uses segunda persona testimonial como "estás", "abres", "tienes", "pides" o "recibes" para herramientas no probadas. Prefiere "un docente", "un equipo", "una universidad" o "una empresa".
- Si la fuente es un paper o artículo académico, no menciones arXiv ni autores dentro del cuerpo. Si aporta, menciona solo el nombre del paper y luego presenta el contenido, hallazgo, tensión e implicación práctica.
- Evita frases de procedencia como "según su página", "leí sobre", "la fuente dice" o "el artículo presenta".
- Si el post parece escrito por alguien que leyó una página y la resumió, todavía no está listo.
- No repitas fórmulas de estilo entre publicaciones. Cambia la apertura, el largo de párrafos y el tipo de cierre.

PATRONES QUE DEBES EVITAR:
- "X presentó..."
- "La herramienta permite..."
- "Entre sus funciones destacan..."
- "La documentación de X muestra..."
- "OpenAI, en su guía..."
- "Anthropic, en su documentación..."
- "En resumen..."
- "En conclusión..."
"""

STORYTELLING_GUARDRAILS_EN = """
NON-NEGOTIABLE NATURALNESS RULES:
- The post must sound like a smart human sharing a point of view, not like an automatic summary.
- Do not summarize the whole source. Pick one angle, tension, or central idea.
- Do not sound like documentation, a changelog, an abstract, or a product recap.
- Avoid feature lists and repetitive "it offers / enables / includes" phrasing.
- Build narrative progression: hook, development with a concrete case or contrast, then reflection.
- Do not use bullets, numbering, or internal section labels.
- Avoid em dashes and colon-heavy prose in the body.
- If the source is official documentation, turn it into one practical implication instead of summarizing the page.
"""

COMMENT_REPLY_SYSTEM_PROMPT_ES = """Eres el autor de un post de LinkedIn respondiendo comentarios.
Tu voz es casual, amable, cercana y con un toque ligero de humor cuando caiga natural.

OBJETIVO
- Responder como humano, no como community manager ni como resumen automático.
- La respuesta debe sentirse hablada, simple y natural.

REGLAS NO NEGOCIABLES
- Devuelve solo JSON válido con este formato:
  {"stance":"supportive|critical|neutral","reply":"..."}
- No uses markdown.
- No uses guion medio ni guion largo.
- No uses dos puntos dentro de la respuesta.
- No uses hashtags.
- No repitas frases del comentario ni copies palabras llamativas tal cual si se pueden evitar.
- No agradezcas de forma robótica ni uses fórmulas de plantilla.
- Usa palabras comunes. Nada solemne, académico, poético ni rebuscado.
- No suenes a ensayo, hilo mental, reflexión literaria ni lección.
- Debe sonar como una respuesta escrita rápido desde el celular por alguien cercano e inteligente.
- Evita frases como "lo clave es", "el reto es", "juicio y creatividad", "en la práctica", "de verdad" o "ahí está lo interesante".
- No propongas colaborar, hacer algo juntos, mandarle algo después ni ofrecer ayuda del tipo "si quieres te ayudo", "te paso", "me escribes" o "lo vemos".
- No suenes condescendiente ni paternalista.
- Máximo 2 frases casi siempre. 3 solo si hace falta. De preferencia menos de 320 caracteres.

SI EL COMENTARIO VA A FAVOR
- Refuerza la idea central.
- Añade una arista nueva o una consecuencia práctica.
- Puedes cerrar con una observación breve o una pregunta ligera si de verdad abre conversación.

SI EL COMENTARIO VA EN CONTRA
- Empieza validando el punto sin rendirte.
- Defiende la idea del post con calma.
- Cierra pidiendo opinión o con una frase que baje la temperatura y deje postura clara.

SI EL COMENTARIO ES NEUTRO O PREGUNTA
- Responde con claridad.
- Aterriza el punto en algo útil o concreto.
- Mantén el tono cercano.
"""


SCAFFOLD_LINE_PREFIXES = (
    "[primera línea impactante]",
    "[primera linea impactante]",
    "[contenido principal]",
    "[cierre:",
    "[si hay imagen",
    "[si hay video",
)

SUMMARY_TONE_PATTERNS = (
    "la documentación",
    "la documentación de",
    "el artículo presenta",
    "la guía describe",
    "openai, en su guía",
    "anthropic, en su guía",
    "google, en su guía",
    "entre sus funciones",
    "permite",
    "incluye",
    "ofrece",
    "en resumen",
    "en conclusión",
)

TECHNICAL_POLISH_PATTERNS = (
    "api ",
    " api",
    "sdk",
    "json",
    "schema",
    "payload",
    "endpoint",
    "timeout",
    "backoff",
    "service_tier",
    "custom_id",
    ".jsonl",
    "/v1/",
    "responses api",
)

DOC_LIKE_DOMAINS = {
    "docs.anthropic.com",
    "developers.openai.com",
    "platform.openai.com",
    "ai.google.dev",
}

DOC_NOISE_PATTERNS = (
    "/v1/",
    "curl ",
    "pip install",
    "npm install",
    "import ",
    "from openai",
    "from anthropic",
    "client.responses",
    "client.chat",
    "response_format",
    "max_output_tokens",
    "service_tier",
    "custom_id",
    "json schema",
    "jsonschema",
    "javascript",
    "typescript",
    "python sdk",
    "typescript sdk",
    "schema",
    "payload",
    "headers",
    "request body",
    "response body",
    "status code",
    ".jsonl",
    "sdk",
)

CUSTOM_PROMPT_SKIP_PREFIXES = (
    "eres un experto",
    "tu tarea es",
    "reglas:",
    "sobre citar al autor:",
    "tono:",
    "caso especial",
    "ejemplos:",
)


def _split_source_line(text: str) -> tuple[str, str]:
    cleaned = (text or "").strip()
    match = re.search(r"(\n+Fuente:\s*\S+\s*)$", cleaned, flags=re.IGNORECASE)
    if not match:
        return cleaned, ""
    return cleaned[:match.start()].strip(), match.group(1).strip()


def _ensure_source_line(text: str, source_url: str) -> str:
    body, _ = _split_source_line(text)
    normalized_body = (body or "").strip()
    normalized_body = re.sub(
        r"(?i)\s*Fuente:\s*https?://\S+\s*",
        " ",
        normalized_body,
    )
    normalized_body = re.sub(r"[ \t]{2,}", " ", normalized_body).strip()
    normalized_url = (source_url or "").strip()
    if not normalized_url:
        return normalized_body

    source_line = f"Fuente: {normalized_url}"
    if not normalized_body:
        return source_line
    return f"{normalized_body}\n\n{source_line}"


def _looks_doc_like_source(source_url: str = "", source_domain: str = "") -> bool:
    domain = (source_domain or "").lower().replace("www.", "")
    url = (source_url or "").lower()
    if domain in DOC_LIKE_DOMAINS:
        return True
    return any(
        marker in url
        for marker in ("/docs/", "/api/docs/", "/guides/", "/reference/", "/overview")
    )


def _sanitize_source_text_for_storytelling(
    text: str,
    *,
    source_url: str = "",
    source_domain: str = "",
) -> str:
    cleaned = (text or "").replace("\r\n", "\n")
    if not cleaned:
        return ""

    if not _looks_doc_like_source(source_url=source_url, source_domain=source_domain):
        return cleaned

    kept_lines: list[str] = []
    in_code_block = False
    for raw_line in cleaned.splitlines():
        stripped = raw_line.strip()
        lowered = stripped.lower()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        if not stripped:
            if kept_lines and kept_lines[-1] != "":
                kept_lines.append("")
            continue

        if any(pattern in lowered for pattern in DOC_NOISE_PATTERNS):
            continue
        if re.search(r"\b[a-z_]+\.[a-z_]+\(", lowered):
            continue
        if re.search(r"[{}[\]<>]{2,}", stripped):
            continue
        if stripped.startswith(("$ ", "> ", ">>>", "POST ", "GET ")):
            continue
        if re.fullmatch(r"[`~#=\-\s]{3,}", stripped):
            continue

        kept_lines.append(stripped)

    sanitized = "\n".join(kept_lines)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()
    return sanitized[:3500] if sanitized else cleaned[:3500]


def _clean_generated_post_output(text: str) -> str:
    """Quita andamiaje literal de prompt cuando el modelo lo devuelve por error."""
    def _capitalize_sentence_starts(value: str) -> str:
        if not value:
            return value

        chars = list(value)
        for index, char in enumerate(chars):
            if char.isalpha():
                chars[index] = char.upper()
                break

        cleaned_value = "".join(chars)

        def _upper_match(match: re.Match[str]) -> str:
            return f"{match.group(1)}{match.group(2).upper()}"

        cleaned_value = re.sub(r"([.!?]\s+)([a-záéíóúñü])", _upper_match, cleaned_value)
        cleaned_value = re.sub(r"(\n\n+)([a-záéíóúñü])", _upper_match, cleaned_value)
        return cleaned_value

    cleaned = (text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return cleaned

    kept_lines: list[str] = []
    for raw_line in cleaned.splitlines():
        stripped = raw_line.strip()
        lowered = stripped.lower()
        if any(lowered.startswith(prefix) for prefix in SCAFFOLD_LINE_PREFIXES):
            continue
        kept_lines.append(raw_line)

    cleaned = "\n".join(kept_lines).strip()
    body, source_line = _split_source_line(cleaned)
    body = body.replace("**", "")
    body = re.sub(r"(?m)^[\-\u2022]\s*", "", body)
    body = re.sub(r"(?m)^\d+\.\s*", "", body)
    body = body.replace("—", ", ").replace("–", ", ")
    body = re.sub(r"\s-\s", ", ", body)
    body = re.sub(r"(?<!Fuente)(?<!https)(?<!http):\s+", ", ", body)
    body = re.sub(r"\s+,", ",", body)
    body = re.sub(r",\s*,+", ", ", body)
    body = re.sub(r"\.\s*,", ".", body)
    body = re.sub(r"\s+\.", ".", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"[ \t]{2,}", " ", body).strip()
    body = _capitalize_sentence_starts(body)

    if source_line:
        source_url = re.sub(r"(?i)^fuente:\s*", "", source_line).strip()
        return _ensure_source_line(body, source_url)

    return body


def _clean_comment_reply(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return ""

    cleaned = cleaned.strip("`").strip()
    cleaned = re.sub(r"^['\"“”]+|['\"“”]+$", "", cleaned)
    cleaned = re.sub(r"(?m)^[\-\u2022]\s*", "", cleaned)
    cleaned = cleaned.replace("—", ", ").replace("–", ", ").replace(" - ", ", ")
    cleaned = cleaned.replace(":", ",")
    cleaned = re.sub(r"(?:^|\s)#\w+", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) <= 420:
        return cleaned

    sentence_cut = max(
        cleaned.rfind(". ", 0, 420),
        cleaned.rfind("? ", 0, 420),
        cleaned.rfind("! ", 0, 420),
    )
    if sentence_cut >= 240:
        return cleaned[:sentence_cut + 1].rstrip() + "…"

    word_cut = cleaned.rfind(" ", 0, 420)
    if word_cut >= 240:
        return cleaned[:word_cut].rstrip(" ,;:") + "…"

    return cleaned[:420].rstrip(" ,;:") + "…"


def _extract_json_block(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    candidates = [raw]
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _extract_jsonish_reply(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None

    match = re.search(r'"reply"\s*[: ,]\s*"', raw, flags=re.IGNORECASE)
    if not match:
        return None

    tail = raw[match.end():]
    tail = tail.replace(r"\\n", "\n").replace(r"\n", "\n").replace(r"\\t", "\t")
    tail = tail.replace(r"\\\"", "\"").replace(r"\\\\", "\\")

    for marker in ('"}', '" }', '", "', '","stance"', '","comment"', '",\n'):
        marker_index = tail.find(marker)
        if marker_index != -1:
            tail = tail[:marker_index]
            break

    return tail.strip().strip('"').strip()


def _word_set(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-záéíóúñü]{4,}", (text or "").lower())
        if token not in {"pero", "porque", "aunque", "sobre", "desde", "cuando", "muchas", "muchos"}
    }


def _has_excessive_comment_overlap(comment_text: str, reply_text: str) -> bool:
    source_words = _word_set(comment_text)
    if len(source_words) < 5:
        return False
    reply_words = _word_set(reply_text)
    overlap = len(source_words & reply_words) / max(len(source_words), 1)
    return overlap >= 0.5


def _has_banned_comment_reply_patterns(reply_text: str) -> bool:
    lowered = (reply_text or "").lower()
    if "#" in lowered:
        return True

    banned_patterns = (
        "si quieres te ayudo",
        "si quieres te paso",
        "si quieres te comparto",
        "si te sirve te",
        "con gusto te ayudo",
        "me escribes",
        "escribeme",
        "escríbeme",
        "te ayudo",
        "te puedo ayudar",
        "podemos verlo",
        "podemos armar",
        "podemos hacer",
        "hagamos",
        "lo vemos",
        "te paso",
        "te comparto",
    )
    return any(pattern in lowered for pattern in banned_patterns)


def _looks_incomplete_comment_reply(reply_text: str) -> bool:
    reply = (reply_text or "").strip()
    if not reply:
        return True

    debug_markers = (
        "traceback (most recent call last):",
        "unicodeencodeerror",
        "<stdin>",
        '{"stance"',
        '"reply"',
        "```",
    )
    lowered = reply.lower()
    if any(marker in lowered for marker in debug_markers):
        return True

    if reply[-1] not in ".!?…":
        return True

    weak_last_tokens = {
        "te",
        "de",
        "del",
        "la",
        "las",
        "los",
        "el",
        "y",
        "o",
        "que",
        "si",
        "bie",
        "pr",
        "pag",
        "obli",
    }
    last_words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñüÜ]+", reply)
    if last_words and last_words[-1].lower() in weak_last_tokens:
        return True

    return False


def _compress_custom_prompt(custom_prompt: Optional[str]) -> str:
    if not custom_prompt:
        return ""

    lowered = custom_prompt.lower()
    distilled: list[str] = []
    if "español de méxico" in lowered or "espanol de mexico" in lowered:
        distilled.append("Usa español de México.")
    if "1700" in lowered:
        distilled.append("Máximo 1700 caracteres.")
    elif "1400" in lowered:
        distilled.append("Máximo 1400 caracteres.")
    if "3 hashtags" in lowered:
        distilled.append("Cierra con 3 hashtags relevantes.")
    elif "5 hashtags" in lowered:
        distilled.append("Cierra con 3 a 5 hashtags relevantes.")
    if "frases largas y cortas" in lowered or "técnicas de redacción con ritmo" in lowered or "tecnicas de redaccion con ritmo" in lowered:
        distilled.append("Combina frases largas y cortas con ritmo natural y saltos de línea cuando ayude.")
    if "markdown" in lowered or "asteriscos" in lowered:
        distilled.append("No uses markdown ni asteriscos.")
    if "imagen adjunta" in lowered:
        distilled.append("No menciones que la fuente trae imagen adjunta.")
    if "citar al autor" in lowered or "solo menciona a quien escribió" in lowered:
        distilled.append("Solo cita al autor cuando su nombre aporte valor real.")
    if "no copies" in lowered or "transforma y eleva" in lowered:
        distilled.append("No copies la fuente. Transforma y eleva el contenido.")
    if "mayúsculas innecesarias" in lowered or "mayusculas innecesarias" in lowered or "signos de exclamación repetidos" in lowered or "signos de exclamacion repetidos" in lowered:
        distilled.append("Evita mayúsculas innecesarias y signos repetidos.")
    if distilled:
        return "\n".join(f"- {line}" for line in distilled[:8])

    condensed: list[str] = []
    seen: set[str] = set()
    for raw_line in custom_prompt.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        lowered = stripped.lower()
        if lowered.startswith(CUSTOM_PROMPT_SKIP_PREFIXES):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue

        cleaned = re.sub(r"^[\-\d\.\)\s]+", "", stripped).strip()
        if not cleaned:
            continue
        lowered_cleaned = cleaned.lower()
        if lowered_cleaned in seen:
            continue

        condensed.append(cleaned[:220])
        seen.add(lowered_cleaned)
        if len(condensed) >= 12:
            break

    return "\n".join(f"- {line}" for line in condensed)


def _build_system_prompt(
    *,
    language: str,
    custom_prompt: Optional[str],
) -> str:
    base_prompt = CORE_SYSTEM_PROMPT_ES if language == "es" else CORE_SYSTEM_PROMPT_EN
    guardrails = STORYTELLING_GUARDRAILS_ES if language == "es" else STORYTELLING_GUARDRAILS_EN
    condensed_custom_prompt = _compress_custom_prompt(custom_prompt)
    if condensed_custom_prompt:
        return (
            f"{base_prompt}\n\n{guardrails}\n\n"
            "PREFERENCIAS ACTIVAS DEL USUARIO:\n"
            f"{condensed_custom_prompt}\n\n"
            "Si hay tensión entre el prompt personalizado y las reglas de naturalidad, "
            "prioriza la naturalidad, el storytelling y el tono humano."
        )
    return f"{base_prompt}\n\n{guardrails}"


def _needs_naturalization_polish(
    text: str,
    *,
    source_url: str = "",
    source_domain: str = "",
) -> bool:
    lowered = (text or "").lower()
    colon_count = lowered.count(":")
    summary_hits = sum(1 for pattern in SUMMARY_TONE_PATTERNS if pattern in lowered)
    technical_hits = sum(1 for pattern in TECHNICAL_POLISH_PATTERNS if pattern in lowered)
    return (
        _looks_doc_like_source(source_url=source_url, source_domain=source_domain)
        or colon_count > 2
        or summary_hits >= 2
        or technical_hits >= 2
        or "\n-" in lowered
        or "\n•" in lowered
    )


def _should_polish_output(
    *,
    language: str,
    text: str,
    source_url: str = "",
    source_domain: str = "",
) -> bool:
    if language != "es":
        return False
    return _get_text_generation_provider() == "openai" or _needs_naturalization_polish(
        text,
        source_url=source_url,
        source_domain=source_domain,
    )


async def _polish_linkedin_post_naturalness(
    *,
    draft: str,
    source_context: str,
    source_url: str,
    language: str = "es",
) -> str:
    if language != "es":
        return draft

    system_prompt = (
        "Eres un editor senior de LinkedIn. Tu trabajo es convertir borradores correctos "
        "en posts que suenen humanos, naturales y memorables, sin cambiar los hechos.\n\n"
        "Reglas no negociables:\n"
        "- No uses guiones medios, guiones largos, viñetas ni numeraciones.\n"
        "- No uses dos puntos dentro del cuerpo.\n"
        "- Evita también el punto y coma salvo que sea imprescindible.\n"
        "- No suenes a resumen, abstract, changelog, documentación ni ficha de producto.\n"
        "- No enumeres funciones ni capacidades.\n"
        "- Mantén una sola idea central.\n"
        "- Estructura el texto como una progresión natural. gancho, desarrollo con caso o contraste, y cierre reflexivo.\n"
        "- El primer bloque debe aterrizar el caso concreto y nombrar con naturalidad a la empresa, paper, estudio, producto, autor o experimento relevante.\n"
        "- No escondas la fuente detrás de palabras vagas como herramienta, empresa, investigación o estudio si el nombre concreto sí importa.\n"
        "- No dejes frases sueltas después de punto. Cada oración debe ser gramaticalmente completa.\n"
        "- No inventes experiencia personal. Si el contexto no demuestra que el autor probó, usó, abrió o vio directamente una herramienta, formula el texto como análisis o escenario profesional, no como vivencia propia.\n"
        "- Para herramientas no probadas, evita segunda persona testimonial como estás, abres, tienes, pides o recibes. Usa tercera persona concreta.\n"
        "- Si la fuente es paper o artículo académico, no menciones arXiv ni autores dentro del cuerpo. Presenta el contenido, no la procedencia.\n"
        "- Usa español de México.\n"
        "- No uses markdown.\n"
        "- Devuelve solo el post final.\n"
        "- La fuente debe hacerse visible dentro del cuerpo, mencionando o describiendo el caso concreto, sin pegar la URL ahí.\n"
        "- Devuelve al final una línea separada con este formato exacto: Fuente: <URL de la fuente>.\n"
        "- No te pongas demasiado técnico. Si el borrador se fue a specs o detalles de producto, devuélvelo a una idea humana y útil.\n"
        "- Si la fuente es documentación, no la conviertas en walkthrough, tutorial ni demo de la herramienta.\n"
        "- Si la fuente es documentación, está prohibido mencionar API, SDK, JSON, endpoint, schema, payload, timeout, backoff, service_tier, custom_id, contenedores, memoria, rate limits, modelos concretos, nombres de parámetros o tipos de archivo, salvo que sin ese detalle el post pierda honestamente su sentido.\n"
        "- No abras con fórmulas tipo 'X publicó', 'Y presentó' o 'la documentación explica' si puedes abrir con la idea que de verdad importa.\n"
        "- El resultado debe sonar como alguien que ya pensó la idea y luego la contó, no como alguien que resumió una página.\n"
        "- Máximo 1400 caracteres."
    )

    user_message = (
        "Reescribe este borrador para que suene mucho más natural y humano sin cambiar los hechos.\n\n"
        f"BORRADOR:\n{draft}\n\n"
        f"CONTEXTO DE FUENTE:\n{source_context[:2800]}\n\n"
        f"URL DE FUENTE: {source_url}"
    )

    polished = await _generate_text_with_provider(
        system_prompt=system_prompt,
        user_message=user_message,
        max_output_tokens=900,
    )
    polished = _clean_generated_post_output(polished)
    return _ensure_source_line(polished, source_url)


async def _rewrite_doc_like_post_for_general_audience(
    *,
    source_context: str,
    source_url: str,
    language: str = "es",
    editorial_context: str | None = None,
) -> str:
    if language != "es":
        return ""

    system_prompt = (
        "Eres un editor senior de LinkedIn en español de México.\n\n"
        "Tarea:\n"
        "Escribe un post de LinkedIn humano y natural a partir de una fuente técnica, "
        "pero para lectores inteligentes que no quieren leer documentación.\n\n"
        "Reglas duras:\n"
        "- Debe sonar como una observación con criterio, no como resumen técnico.\n"
        "- No uses dos puntos dentro del cuerpo.\n"
        "- No uses guiones medios ni guiones largos.\n"
        "- No uses listas.\n"
        "- No uses tono de memo, tutorial, abstract o changelog.\n"
        "- Está prohibido mencionar API, SDK, JSON, endpoint, payload, schema, timeout, backoff, rate limits, nombres de parámetros, rutas, tipos de archivo, modelos concretos o detalles de implementación.\n"
        "- Tampoco menciones ejemplos de código ni artefactos de la doc.\n"
        "- Elige una sola implicación humana, estratégica, organizacional o pedagógica.\n"
        "- Si la fuente se presta más para una descripción práctica o invitación a usar, haz eso sin forzar una reflexión.\n"
        "- Debe aterrizar el caso concreto de la fuente y su actor principal, pero sin hablar como manual.\n"
        "- No inventes anécdotas, casos de clientes, experiencias personales, cifras externas ni ejemplos que la fuente no respalde.\n"
        "- Máximo 1100 caracteres.\n"
        "- Devuelve al final una línea separada exacta con Fuente: <URL>.\n"
        "- Si no puedes volverla una idea valiosa sin caer en lo técnico, responde solo [CANCELAR]: <motivo breve>."
    )

    user_message = (
        f"FUENTE ACTUAL:\n{source_context[:3200]}\n\n"
        f"CRITERIO EDITORIAL ADICIONAL:\n{editorial_context or 'Decide el mejor enfoque según la fuente.'}\n\n"
        f"URL DE FUENTE: {source_url}\n\n"
        "Escribe el post final."
    )

    rewritten = await _generate_text_with_provider(
        system_prompt=system_prompt,
        user_message=user_message,
        max_output_tokens=700,
    )
    rewritten = _clean_generated_post_output(rewritten)
    return _ensure_source_line(rewritten, source_url)


def _get_text_generation_provider() -> str:
    provider = (settings.text_generation_provider or "anthropic").strip().lower()
    if provider not in {"anthropic", "openai"}:
        logger.warning(
            "TEXT_GENERATION_PROVIDER=%s no es valido; usando anthropic",
            settings.text_generation_provider,
        )
        return "anthropic"
    return provider


def get_text_generation_config_error() -> str | None:
    provider = _get_text_generation_provider()
    if provider == "openai":
        if not settings.openai_api_key:
            return (
                "TEXT_GENERATION_PROVIDER=openai pero OPENAI_API_KEY no está configurada."
            )
        if not settings.openai_text_model:
            return "OPENAI_TEXT_MODEL no está configurado."
        return None

    if not settings.anthropic_api_key:
        return (
            "TEXT_GENERATION_PROVIDER=anthropic pero ANTHROPIC_API_KEY no está configurada."
        )
    if not settings.anthropic_text_model:
        return "ANTHROPIC_TEXT_MODEL no está configurado."
    return None


async def _generate_text_with_provider(
    *,
    system_prompt: str,
    user_message: str,
    max_output_tokens: int,
) -> str:
    error = get_text_generation_config_error()
    if error:
        raise RuntimeError(error)

    provider = _get_text_generation_provider()
    if provider == "openai":
        return await _generate_text_with_openai(
            system_prompt=system_prompt,
            user_message=user_message,
            max_output_tokens=max_output_tokens,
        )

    return await _generate_text_with_anthropic(
        system_prompt=system_prompt,
        user_message=user_message,
        max_output_tokens=max_output_tokens,
    )


async def _generate_text_with_anthropic(
    *,
    system_prompt: str,
    user_message: str,
    max_output_tokens: int,
) -> str:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=settings.anthropic_text_model,
        max_tokens=max_output_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        timeout=90.0,
    )
    return message.content[0].text.strip()


def _extract_openai_output_text(payload: dict) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks: list[str] = []
    for item in payload.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(content["text"])

    return "\n".join(chunks).strip()


async def _generate_text_with_openai(
    *,
    system_prompt: str,
    user_message: str,
    max_output_tokens: int,
) -> str:
    payload = {
        "model": settings.openai_text_model,
        "instructions": system_prompt,
        "input": [
            {
                "role": "user",
                "content": user_message,
            }
        ],
        "max_output_tokens": max_output_tokens,
        "store": False,
    }

    if settings.openai_reasoning_effort:
        payload["reasoning"] = {"effort": settings.openai_reasoning_effort}

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(
        timeout=90.0,
        verify=not settings.allow_insecure_ssl_fallback,
    ) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    text = _extract_openai_output_text(data)
    if text:
        return text

    status = data.get("status")
    incomplete = data.get("incomplete_details") or {}
    reason = incomplete.get("reason") or "sin detalle"
    raise RuntimeError(
        f"OpenAI no devolvió texto util (status={status}, reason={reason})."
    )


async def generate_linkedin_post(
    tweet: TweetData,
    language: str = "es",
    custom_prompt: Optional[str] = None,
    editorial_context: Optional[str] = None,
) -> str:
    """Genera una publicación de LinkedIn a partir de los datos del tweet."""
    system_prompt = _build_system_prompt(
        language=language,
        custom_prompt=custom_prompt,
    )

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

    source_notes: list[str] = []
    if language == "es":
        source_notes.append(
            "Escribe el post como una idea original para LinkedIn, no como un resumen del contenido."
        )
        source_notes.append(
            "La fuente debe sentirse dentro del texto. Haz visible el hecho, actor, herramienta, experimento o hallazgo concreto que originó el post."
        )
        source_notes.append(
            "En el primer bloque debe aparecer con naturalidad el protagonista concreto de la fuente."
        )
        source_notes.append(
            "Integra la referencia de forma natural en el cuerpo y termina con una línea final exacta: Fuente: <URL de la fuente>."
        )
        if tweet.is_article and tweet.article_content:
            source_notes.append(
                "Aquí hay contexto suficiente para construir una narrativa con caso, giro o contraste. Aprovecha eso."
            )
        if tweet.paper_info:
            source_notes.append(
                "Si retomas el paper, evita sonar a abstract. Cuenta qué hallazgo cambia algo en la práctica."
            )
        elif tweet.author_name:
            source_notes.append(
                "Si el autor o la organización aportan contexto real, menciónalos de forma natural dentro de la historia."
            )
        if editorial_context:
            source_notes.append(editorial_context)

    source_guidance = "\n".join(f"- {note}" for note in source_notes)

    user_message = (
        (
            "Genera una publicación de LinkedIn basada en este contenido de X.\n\n"
            f"CONTEXTO:\n{context}\n\n"
            f"INSTRUCCIONES ESPECÍFICAS:\n{source_guidance}"
        )
        if language == "es"
        else f"Generate a LinkedIn post based on this X (Twitter) content:\n\n{context}"
    )

    generated = await _generate_text_with_provider(
        system_prompt=system_prompt,
        user_message=user_message,
        max_output_tokens=900,
    )
    generated = _ensure_source_line(_clean_generated_post_output(generated), tweet.tweet_url or "")

    if _should_polish_output(
        language=language,
        text=generated,
        source_url=tweet.tweet_url or "",
        source_domain="x.com",
    ):
        generated = await _polish_linkedin_post_naturalness(
            draft=generated,
            source_context=context,
            source_url=tweet.tweet_url or "",
            language=language,
        )
        generated = _ensure_source_line(_clean_generated_post_output(generated), tweet.tweet_url or "")

    return _ensure_source_line(_clean_generated_post_output(generated), tweet.tweet_url or "")


async def generate_linkedin_post_from_url_content(
    url_content,  # UrlContent dataclass from url_scraper
    language: str = "es",
    custom_prompt: Optional[str] = None,
    editorial_context: Optional[str] = None,
) -> str:
    """
    Genera una publicación de LinkedIn a partir del contenido de una URL genérica
    (artículo, blog, noticia, etc.).
    """
    system_prompt = _build_system_prompt(
        language=language,
        custom_prompt=custom_prompt,
    )

    context_parts = []

    if url_content.title:
        context_parts.append(f"Título: {url_content.title}")

    if url_content.author:
        context_parts.append(f"Autor: {url_content.author}")

    if url_content.source_domain:
        context_parts.append(f"Fuente: {url_content.source_domain}")

    if url_content.text:
        source_text = _sanitize_source_text_for_storytelling(
            url_content.text,
            source_url=url_content.url or "",
            source_domain=url_content.source_domain or "",
        )
        context_parts.append(f"Contenido:\n{source_text}")

    if url_content.images:
        n = len(url_content.images)
        context_parts.append(
            f"La página incluye {n} imagen{'es' if n > 1 else ''} "
            f"que se pueden adjuntar al post de LinkedIn."
        )

    context = "\n\n".join(context_parts)

    source_notes: list[str] = []
    if language == "es":
        source_notes.append(
            "Escribe como un post original de LinkedIn con punto de vista, no como resumen del artículo."
        )
        source_notes.append(
            "La fuente debe sentirse dentro del texto. Haz visible el caso, empresa, paper, producto o experimento concreto del que estás hablando."
        )
        source_notes.append(
            "En el primer bloque debe aparecer con naturalidad el protagonista concreto de la fuente."
        )
        source_notes.append(
            "Integra la referencia de forma natural en el cuerpo y termina con una línea final exacta: Fuente: <URL de la fuente>."
        )
        if _looks_doc_like_source(
            source_url=url_content.url or "",
            source_domain=url_content.source_domain or "",
        ):
            source_notes.append(
                "La fuente es documentación o guía oficial. No resumas secciones ni funciones. Elige una sola implicación práctica o estratégica."
            )
        elif (url_content.source_domain or "").lower().endswith(("nature.com", "arxiv.org")):
            source_notes.append(
                "La fuente es de investigación. No suenes a abstract. Cuenta qué cambia y por qué obliga a pensar distinto."
            )
        if editorial_context:
            source_notes.append(editorial_context)

    source_guidance = "\n".join(f"- {note}" for note in source_notes)

    user_message = (
        (
            "Genera una publicación de LinkedIn basada en este artículo o contenido web.\n\n"
            f"CONTEXTO:\n{context}\n\n"
            f"INSTRUCCIONES ESPECÍFICAS:\n{source_guidance}"
        )
        if language == "es"
        else f"Generate a LinkedIn post based on this web article/content:\n\n{context}"
    )

    if _looks_doc_like_source(
        source_url=url_content.url or "",
        source_domain=url_content.source_domain or "",
    ) and language == "es":
        generated = await _rewrite_doc_like_post_for_general_audience(
            source_context=context,
            source_url=url_content.url or "",
            language=language,
            editorial_context=editorial_context,
        )
    else:
        generated = await _generate_text_with_provider(
            system_prompt=system_prompt,
            user_message=user_message,
            max_output_tokens=900,
        )
        generated = _ensure_source_line(_clean_generated_post_output(generated), url_content.url or "")

    if _should_polish_output(
        language=language,
        text=generated,
        source_url=url_content.url or "",
        source_domain=url_content.source_domain or "",
    ):
        generated = await _polish_linkedin_post_naturalness(
            draft=generated,
            source_context=context,
            source_url=url_content.url or "",
            language=language,
        )
        generated = _ensure_source_line(_clean_generated_post_output(generated), url_content.url or "")

    return _ensure_source_line(_clean_generated_post_output(generated), url_content.url or "")


async def rewrite_linkedin_post_with_storytelling(
    *,
    original_post: str,
    source_summary: str,
    source_url: str,
    language: str = "es",
    custom_prompt: Optional[str] = None,
) -> str:
    """Reescribe un post existente con una voz más natural sin perder fidelidad a la fuente."""
    if _looks_doc_like_source(source_url=source_url) and language == "es":
        rewritten = await _rewrite_doc_like_post_for_general_audience(
            source_context=source_summary,
            source_url=source_url,
            language=language,
            editorial_context="Reescribe desde cero y decide si conviene explicar, presentar, invitar o reflexionar según la fuente.",
        )
        return _ensure_source_line(_clean_generated_post_output(rewritten), source_url)

    condensed_custom_prompt = _compress_custom_prompt(custom_prompt)
    system_prompt = (
        f"{CORE_SYSTEM_PROMPT_ES if language == 'es' else CORE_SYSTEM_PROMPT_EN}\n\n"
        f"{STORYTELLING_GUARDRAILS_ES if language == 'es' else STORYTELLING_GUARDRAILS_EN}\n\n"
        "TAREA ESPECÍFICA:\n"
        "- Reescribe el copy desde cero.\n"
        "- Mantén solo hechos respaldados por la fuente actual.\n"
        "- Conserva el tema si sigue vigente, pero no reciclar la redacción actual.\n"
        "- Evita por completo el tono de resumen o ficha técnica.\n"
        "- Haz visible la fuente dentro del cuerpo. El lector debe entender qué caso, actor, estudio, producto o experimento disparó el post.\n"
        "- El primer bloque debe aterrizar ese caso concreto y, cuando aporte contexto, nombrarlo con naturalidad.\n"
        "- No inventes experiencia personal. Si la fuente no demuestra uso propio, no escribas 'probé', 'abrí', 'entré', 'le pedí', 'usé', 'me pasó' ni 'en mi experiencia'.\n"
        "- Para herramientas que no conste que el autor haya probado, escribe como análisis, escenario o recomendación, no como testimonio.\n"
        "- Para herramientas no probadas, evita segunda persona testimonial como 'estás', 'abres', 'tienes', 'pides' o 'recibes'. Usa tercera persona concreta.\n"
        "- Si la fuente es paper o artículo académico, no menciones arXiv ni autores dentro del cuerpo. Como máximo menciona el nombre del paper una vez y luego desarrolla el contenido.\n"
        "- No pegues la URL dentro del cuerpo.\n"
        "- Cierra con una línea final separada que diga exactamente Fuente: <URL de la fuente>.\n"
        "- No te pongas demasiado técnico. Si la fuente viene de docs o API, aterriza una sola implicación humana o estratégica.\n"
        "- Si la fuente viene de documentación o de una guía técnica, borra del borrador cualquier detalle de implementación que no sea esencial. Eso incluye API, SDK, JSON, endpoint, payload, schema, timeout, backoff, service_tier, custom_id, nombres de parámetros, rutas y tipos de archivo.\n"
        "- Si la fuente ya no sostiene honestamente el mensaje, responde solo [CANCELAR]: <motivo breve>.\n"
    )
    if condensed_custom_prompt:
        system_prompt += f"\nPREFERENCIAS ACTIVAS DEL USUARIO:\n{condensed_custom_prompt}\n"

    user_message = (
        "Reescribe esta publicación para que suene natural, humana y reflexiva.\n\n"
        f"BORRADOR ACTUAL:\n{original_post}\n\n"
        f"FUENTE ACTUAL:\n{source_summary}\n\n"
        f"URL DE FUENTE: {source_url}"
    )

    rewritten = await _generate_text_with_provider(
        system_prompt=system_prompt,
        user_message=user_message,
        max_output_tokens=700,
    )
    rewritten = _ensure_source_line(_clean_generated_post_output(rewritten), source_url)
    if rewritten.startswith("[CANCELAR]:"):
        return rewritten

    if _should_polish_output(
        language=language,
        text=rewritten,
        source_url=source_url,
        source_domain="",
    ):
        rewritten = await _polish_linkedin_post_naturalness(
            draft=rewritten,
            source_context=source_summary,
            source_url=source_url,
            language=language,
        )
        rewritten = _ensure_source_line(_clean_generated_post_output(rewritten), source_url)

    return _ensure_source_line(_clean_generated_post_output(rewritten), source_url)


async def revise_linkedin_post_from_instructions(
    *,
    original_post: str,
    source_summary: str,
    source_url: str,
    instructions: str,
    previous_instructions: str = "",
    editorial_profile: str = "",
    language: str = "es",
    custom_prompt: Optional[str] = None,
) -> str:
    """Aplica indicaciones editoriales del usuario a un borrador pendiente."""
    base_prompt = _build_system_prompt(language=language, custom_prompt=custom_prompt)
    system_prompt = (
        f"{base_prompt}\n\n"
        "TAREA DE REVISIÓN SOLICITADA POR EL AUTOR:\n"
        "Edita el borrador según las instrucciones explícitas del autor. "
        "Devuelve solo la publicación final.\n"
        "No cambies ni inventes hechos, cifras, nombres o conclusiones de la fuente.\n"
        "Las instrucciones nuevas tienen prioridad y las anteriores siguen vigentes "
        "cuando no se contradigan.\n"
        "Decide si conviene presentar, describir, invitar a usar, advertir, analizar o "
        "reflexionar; no fuerces una reflexión.\n"
        "No uses asteriscos, markdown, viñetas, guiones medios ni una estructura rígida repetitiva.\n"
        "No digas que estás revisando un borrador ni menciones estas instrucciones.\n"
        "Mantén el resultado por debajo de 3000 caracteres.\n"
        "Cierra con una línea separada que diga exactamente Fuente: <URL de la fuente>."
    )
    user_message = (
        f"BORRADOR ACTUAL:\n{(original_post or '').strip()[:5000]}\n\n"
        f"FUENTE Y CONTEXTO:\n{(source_summary or '').strip()[:5000]}\n\n"
        f"URL DE FUENTE: {source_url}\n\n"
        f"INSTRUCCIONES NUEVAS DEL AUTOR:\n{(instructions or '').strip()[:2000]}\n\n"
        "INSTRUCCIONES ANTERIORES QUE DEBEN CONSERVARSE:\n"
        f"{(previous_instructions or 'Ninguna.').strip()[:3000]}\n\n"
        "MEMORIA EDITORIAL APRENDIDA:\n"
        f"{(editorial_profile or 'No disponible.').strip()[:3000]}"
    )

    revised = await _generate_text_with_provider(
        system_prompt=system_prompt,
        user_message=user_message,
        max_output_tokens=900,
    )
    revised = _ensure_source_line(_clean_generated_post_output(revised), source_url)
    if not revised.strip():
        raise RuntimeError("La revisión no produjo un texto utilizable.")
    if len(revised) > 3000:
        raise RuntimeError("La revisión excedió el límite de 3000 caracteres de LinkedIn.")
    return revised


async def refresh_linkedin_post_for_currentness(
    *,
    original_post: str,
    source_summary: str,
    source_url: str,
    today_iso: str,
    language: str = "es",
    custom_prompt: Optional[str] = None,
    force_rewrite: bool = False,
) -> str:
    """Reescribe un post para mantenerlo vigente o cancela si ya no es confiable."""
    def _is_meta_line(line: str) -> bool:
        lowered = line.strip().lower()
        return lowered.startswith((
            "post listo para linkedin",
            "post final listo para linkedin",
            "reescrito listo para linkedin",
            "el post sigue vigente",
            "el post puede mantenerse",
            "se puede publicar",
            "el contenido de la fuente",
            "ajusté",
            "ajuste",
            "reescribí",
        ))

    def _clean_refresh_output(text: str) -> str:
        cleaned = (text or "").replace("\r\n", "\n").strip()
        if not cleaned or cleaned.startswith("[CANCELAR]:"):
            return cleaned

        if "\n\n" in cleaned:
            first_block, remainder = cleaned.split("\n\n", 1)
            if any(_is_meta_line(line) for line in first_block.splitlines() if line.strip()):
                cleaned = remainder.strip()

        lines = cleaned.splitlines()
        while lines and _is_meta_line(lines[0]):
            lines.pop(0)
            while lines and not lines[0].strip():
                lines.pop(0)
        return "\n".join(lines).strip()

    if _looks_doc_like_source(source_url=source_url) and language == "es":
        refreshed = await _rewrite_doc_like_post_for_general_audience(
            source_context=source_summary,
            source_url=source_url,
            language=language,
        )
        return _ensure_source_line(_clean_generated_post_output(refreshed), source_url)

    base_prompt = _build_system_prompt(language=language, custom_prompt=custom_prompt)
    system_prompt = (
        f"{base_prompt}\n\n"
        "Además, en esta tarea estás actuando como editor de verificación previa a publicación para LinkedIn.\n"
        "Tu trabajo es revisar un post programado contra su fuente actual y decidir si sigue siendo publicable.\n\n"
        "Reglas de verificación:\n"
        "- Usa solo hechos respaldados por la fuente actual.\n"
        "- Si el post ya está vigente, conserva al máximo su idea central y su gancho; cambia solo lo estrictamente necesario.\n"
        "- Si el problema es solo de lenguaje temporal, reescribe el post en un framing vigente y evergreen.\n"
        "- Evita afirmar disponibilidad, novedad o liderazgo si la fuente actual no lo respalda.\n"
        "- Haz visible la fuente dentro del cuerpo. Debe sentirse el caso concreto que originó el post.\n"
        "- El primer bloque debe aterrizar el caso concreto y, cuando el nombre propio aporte contexto, incluirlo con naturalidad.\n"
        "- No hables del proceso de verificación. No digas 'el post sigue vigente', 'ajusté', 'reescribí', 'listo para LinkedIn' ni nada meta.\n"
        "- No pegues la URL dentro del cuerpo.\n"
        "- Cierra con una línea final separada que diga exactamente Fuente: <URL de la fuente>.\n"
        "- No te pongas demasiado técnico. Si la fuente es muy técnica, tradúcela a una implicación útil o una decisión concreta.\n"
        "- Si la fuente es documentación o guía técnica, elimina cualquier detalle accesorio de implementación. No menciones API, SDK, JSON, endpoint, payload, schema, timeout, backoff, service_tier, custom_id, nombres de parámetros, rutas ni tipos de archivo salvo que el mensaje se vuelva falso sin eso.\n"
        "- Si la fuente ya no existe, contradice el mensaje principal, o el post quedaría engañoso, responde SOLO: [CANCELAR]: <motivo breve>\n"
        "- Si sí se puede salvar, devuelve solo el post final listo para LinkedIn.\n"
        "- Máximo 1300 caracteres."
    )

    if force_rewrite:
        user_message = (
            f"Fecha actual: {today_iso}\n\n"
            f"POST ORIGINAL:\n{original_post}\n\n"
            f"FUENTE ACTUAL:\n{source_summary}\n\n"
            f"URL DE FUENTE: {source_url}\n\n"
            "Rehaz este post desde cero para que suene más natural, humano y reflexivo, "
            "manteniendo solo hechos que sigan respaldados por la fuente actual. "
            "Conserva el tema si sigue vigente, pero no reciclar la redacción actual. "
            "Si ya no se puede sostener con honestidad, cancélalo."
        )
    else:
        user_message = (
            f"Fecha actual: {today_iso}\n\n"
            f"POST ORIGINAL:\n{original_post}\n\n"
            f"FUENTE ACTUAL:\n{source_summary}\n\n"
            f"URL DE FUENTE: {source_url}\n\n"
            "Revisa si el post sigue vigente. Si sí, devuélvelo actualizado. Si no, cancélalo."
        )

    refreshed = await _generate_text_with_provider(
        system_prompt=system_prompt,
        user_message=user_message,
        max_output_tokens=900,
    )
    refreshed = _clean_refresh_output(refreshed)
    refreshed = _ensure_source_line(_clean_generated_post_output(refreshed), source_url)
    if refreshed and not refreshed.startswith("[CANCELAR]:") and _should_polish_output(
        language=language,
        text=refreshed,
        source_url=source_url,
        source_domain="",
    ):
        refreshed = await _polish_linkedin_post_naturalness(
            draft=refreshed,
            source_context=source_summary,
            source_url=source_url,
            language=language,
        )
        refreshed = _clean_refresh_output(refreshed)
        refreshed = _ensure_source_line(_clean_generated_post_output(refreshed), source_url)
    return _ensure_source_line(refreshed, source_url)


async def generate_linkedin_comment_reply(
    *,
    post_text: str,
    comment_text: str,
    custom_prompt: Optional[str] = None,
) -> dict[str, str]:
    compressed_prompt = _compress_custom_prompt(custom_prompt)
    user_message = (
        "Post original:\n"
        f"{(post_text or '').strip()[:2400]}\n\n"
        "Comentario recibido:\n"
        f"{(comment_text or '').strip()[:1400]}\n\n"
        "Devuélveme solo el JSON pedido."
    )
    if compressed_prompt:
        user_message += f"\n\nPistas de voz del autor:\n{compressed_prompt}"

    raw = await _generate_text_with_provider(
        system_prompt=COMMENT_REPLY_SYSTEM_PROMPT_ES,
        user_message=user_message,
        max_output_tokens=280,
    )
    payload = _extract_json_block(raw) or {}
    stance = str(payload.get("stance") or "neutral").strip().lower()
    if stance not in {"supportive", "critical", "neutral"}:
        stance = "neutral"

    reply_source = payload.get("reply") if payload else (_extract_jsonish_reply(raw) or raw)
    reply = _clean_comment_reply(str(reply_source or ""))

    if (
        not reply
        or _has_excessive_comment_overlap(comment_text, reply)
        or _has_banned_comment_reply_patterns(reply)
        or _looks_incomplete_comment_reply(reply)
    ):
        retry_message = (
            user_message
            + "\n\nLa respuesta anterior sonó demasiado pegada al comentario, poco natural o cayó en una fórmula que no quiero."
            + "\nReescríbela con más distancia verbal, sin hashtags, sin ofrecer ayuda, sin proponer hacer algo juntos y manteniendo la misma idea."
            + "\nLa respuesta debe cerrar la idea completa y terminar con punto o signo de pregunta."
        )
        retry_raw = await _generate_text_with_provider(
            system_prompt=COMMENT_REPLY_SYSTEM_PROMPT_ES,
            user_message=retry_message,
            max_output_tokens=280,
        )
        retry_payload = _extract_json_block(retry_raw) or {}
        stance = str(retry_payload.get("stance") or stance).strip().lower()
        if stance not in {"supportive", "critical", "neutral"}:
            stance = "neutral"
        retry_source = retry_payload.get("reply") if retry_payload else (_extract_jsonish_reply(retry_raw) or retry_raw)
        reply = _clean_comment_reply(str(retry_source or ""))

    return {
        "stance": stance,
        "reply": reply,
    }


def _build_image_prompt(linkedin_text: str) -> str:
    """
    Prompt de imagen genérico como fallback (sin llamada a Claude).
    Se usa cuando no hay API key o falla la versión inteligente.
    """
    clean_post = _clean_linkedin_post_for_image(linkedin_text)
    first_line = clean_post.split("\n")[0][:180]
    recipe = _pick_visual_recipe(clean_post)
    return (
        f"Square LinkedIn visual, conceptual editorial illustration, not a poster or magazine cover, for the idea: {first_line}. "
        f"Composition: {recipe['composition']}. "
        f"Motifs: {recipe['motifs']}. "
        f"Color palette: {recipe['palette']}. "
        f"Lighting: {recipe['lighting']}. "
        f"Materials: {recipe['materials']}. "
        "Premium art-directed look, strong focal point, layered depth, clean negative space. "
        "No text, no letters, no numbers, no logos, no watermarks, no screenshots, no readable UI, "
        "no robot faces, no glowing brain cliché, no generic stock-art feel, no headline area, "
        "and any cards, papers, or tiles must be completely blank."
    )


def _clean_linkedin_post_for_image(linkedin_text: str) -> str:
    """Limpia hashtags y fuente para concentrar el brief visual en la idea central."""
    if not linkedin_text:
        return ""

    cleaned_lines: list[str] = []
    for raw_line in linkedin_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("fuente:"):
            continue
        if line.startswith("#"):
            continue
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"(?:^|\s)#\w+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:1200]


def _pick_visual_recipe(linkedin_text: str) -> dict:
    """Elige una dirección visual basada en el tema principal del post."""
    text = linkedin_text.lower()

    keyword_groups = [
        ("agents", ("claude code", "agent", "agente", "mcp", "repo", "repositorio", "developer", "desarrollador", "software", "terminal", "workflow", "coding", "code", "vibe coding")),
        ("multimodal", ("notebooklm", "cinematic", "video overview", "video overviews", "multimodal", "podcast")),
        ("promptcraft", ("prompt", "prompting", "context engineering", "instrucciones", "instruction", "especificación", "specification")),
        ("research", ("paper", "papers", "investigación", "literatura", "literature", "ensayo", "nature", "abstract", "citation", "revisión", "review de literatura", "científico")),
        ("creativity", ("creativ", "brainstorm", "homogen", "divers", "ideas", "idea diversity")),
        ("education", ("tutor", "estudiante", "student", "docente", "teacher", "profesor", "aprendiz", "learning", "clase", "curso", "school")),
    ]

    for recipe_name, keywords in keyword_groups:
        if any(keyword in text for keyword in keywords):
            return VISUAL_RECIPES[recipe_name]

    return VISUAL_RECIPES["general"]


async def _build_image_prompt_smart(linkedin_text: str) -> str:
    """
    Usa Claude para generar un prompt de imagen específico y relevante
    al contenido del post. Produce imágenes mucho más contextuales.
    """
    clean_post = _clean_linkedin_post_for_image(linkedin_text)
    recipe = _pick_visual_recipe(clean_post)
    try:
        prompt = await _generate_text_with_provider(
            system_prompt=(
                "You are a senior editorial art director writing prompts for premium AI image generation. "
                "Your job is to create bespoke visuals for LinkedIn posts about AI, education, research, and software. "
                "Prefer bold editorial visuals, cinematic conceptual photography, premium 3D still lifes, or museum-grade collages over flat generic infographics. "
                "Every prompt must feel art-directed, specific, high-impact, and scroll-stopping without becoming noisy.\n\n"
                "Hard rules:\n"
                "- Output only the final image prompt.\n"
                "- Create one central visual metaphor tied to the post.\n"
                "- Mention composition, lighting, materials, and depth.\n"
                "- Use a vertical 4:5 LinkedIn feed composition with one strong focal point.\n"
                "- Make it visually arresting: dramatic depth, intentional contrast, tactile materials, and a surprising metaphor.\n"
                "- Not a poster, not a magazine cover, not a slide, and not a UI mockup.\n"
                "- No text, letters, numbers, labels, logos, watermarks, screenshots, or readable UI.\n"
                "- No celebrity or recognizable public figure faces.\n"
                "- Avoid generic AI stock tropes: glowing brain, robot head, purple-on-navy abstract swirl, vague holograms.\n"
                "- Avoid bland dashboards, low-detail icon collages, generic classroom scenes, and corporate stock-photo energy.\n"
                "- Max 140 words."
            ),
            user_message=(
                "Create an image prompt for this LinkedIn post.\n\n"
                f"Topic direction: {recipe['label']}\n"
                f"Preferred palette: {recipe['palette']}\n"
                f"Composition cue: {recipe['composition']}\n"
                f"Motifs to consider: {recipe['motifs']}\n"
                f"Lighting cue: {recipe['lighting']}\n"
                f"Material cue: {recipe['materials']}\n\n"
                f"POST:\n{clean_post}"
            ),
            max_output_tokens=260,
        )
        prompt = " ".join(prompt.strip().split())
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
    return _generate_placeholder_image(linkedin_text)


async def _generate_imagen3(prompt: str, api_key: str) -> Optional[bytes]:
    """
    Genera imagen con Google Imagen.
    Usa primero Imagen 4 estándar, luego fast y ultra como fallback.
    """
    import base64
    models = [
        "imagen-4.0-generate-001",
        "imagen-4.0-fast-generate-001",
        "imagen-4.0-ultra-generate-001",
    ]
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "3:4",
            "personGeneration": "dont_allow",
        },
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
    Intenta Gemini 3.1 Flash Image Preview y Gemini 2.5 Flash Image.
    """
    import base64
    models = [
        "gemini-3-pro-image-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
    ]
    for model in models:
        if model in {"gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview"}:
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "imageConfig": {
                        "aspectRatio": "4:5",
                        "imageSize": "2K",
                    }
                },
            }
        else:
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "imageConfig": {
                        "aspectRatio": "4:5",
                    }
                },
            }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta"
            f"/models/{model}:generateContent?key={api_key}"
        )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(url, json=payload)
                if r.status_code == 200:
                    for candidate in r.json().get("candidates", []):
                        for part in candidate.get("content", {}).get("parts", []):
                            if "inlineData" in part:
                                logger.info(f"Imagen generada con {model}")
                                return base64.b64decode(part["inlineData"]["data"])
                logger.warning(f"Gemini {model} devolvió {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.warning(f"Error con Gemini {model}: {e}")
    return None


async def _generate_pollinations(prompt: str) -> Optional[bytes]:
    """Fallback gratuito: Pollinations.ai. Reintenta hasta 3 veces."""
    encoded = urllib.parse.quote(prompt[:300])
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1080&height=1350&nologo=true&model=flux"
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


def _hexless_lerp(start: tuple[int, int, int], end: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(start[i] + (end[i] - start[i]) * t) for i in range(3))


def _generate_placeholder_image(linkedin_text: str = "") -> Optional[bytes]:
    """Genera una imagen de fallback más cuidada y dependiente del tema."""
    try:
        from PIL import Image, ImageDraw, ImageFilter
        import io

        recipe = _pick_visual_recipe(_clean_linkedin_post_for_image(linkedin_text))
        c1, c2, c3, c4 = recipe["colors"]
        w, h = 1024, 1024
        img = Image.new("RGB", (w, h), color=c1)
        px = img.load()
        for y in range(h):
            blend = y / (h - 1)
            row_color = _hexless_lerp(c1, c2, blend * 0.7)
            for x in range(w):
                px[x, y] = row_color

        draw = ImageDraw.Draw(img)

        for i in range(-h, w, 110):
            draw.line([(i, 0), (i + h, h)], fill=_hexless_lerp(c3, c1, 0.65), width=2)

        # Tarjetas principales
        cards = [
            (132, 196, 720, 700, c4),
            (220, 120, 844, 586, _hexless_lerp(c2, c4, 0.35)),
            (286, 300, 902, 858, _hexless_lerp(c3, c1, 0.3)),
        ]
        for left, top, right, bottom, fill in cards:
            draw.rounded_rectangle([left, top, right, bottom], radius=36, fill=fill)
            draw.rounded_rectangle([left, top, right, bottom], radius=36, outline=_hexless_lerp(fill, c3, 0.45), width=3)

        # Motivo central según tema
        cx, cy = w // 2, h // 2
        if recipe["label"] == VISUAL_RECIPES["agents"]["label"]:
            nodes = [(300, 280), (500, 230), (730, 320), (370, 520), (640, 560), (510, 760)]
            for x1, y1 in nodes:
                for x2, y2 in nodes:
                    if (x1, y1) < (x2, y2) and abs(x1 - x2) + abs(y1 - y2) < 420:
                        draw.line([(x1, y1), (x2, y2)], fill=_hexless_lerp(c2, c4, 0.45), width=5)
            for x, y in nodes:
                draw.ellipse([x - 28, y - 28, x + 28, y + 28], fill=c2, outline=c3, width=3)
        elif recipe["label"] == VISUAL_RECIPES["research"]["label"]:
            for offset in (0, 22, 44):
                draw.rounded_rectangle([280 + offset, 240 + offset, 720 + offset, 650 + offset], radius=24, fill=c4, outline=c3, width=2)
            draw.ellipse([620, 520, 820, 720], outline=c2, width=14)
            draw.line([(760, 660), (875, 775)], fill=c2, width=18)
            for idx, y in enumerate(range(300, 590, 56)):
                width = 180 + (idx % 3) * 70
                draw.rounded_rectangle([340, y, 340 + width, y + 18], radius=9, fill=_hexless_lerp(c3, c1, 0.2))
        elif recipe["label"] == VISUAL_RECIPES["multimodal"]["label"]:
            frame_boxes = [(180, 250, 480, 620), (380, 190, 730, 640), (610, 320, 900, 700)]
            for idx, box in enumerate(frame_boxes):
                fill = [c4, _hexless_lerp(c2, c4, 0.35), _hexless_lerp(c3, c1, 0.25)][idx]
                draw.rounded_rectangle(box, radius=32, fill=fill, outline=c3, width=4)
            for i in range(6):
                x = 150 + i * 110
                draw.arc([x, 690, x + 160, 850], start=200, end=340, fill=c2, width=8)
        elif recipe["label"] == VISUAL_RECIPES["creativity"]["label"]:
            diverse = [(240, 340), (330, 270), (420, 380), (500, 300), (580, 420)]
            for idx, (x, y) in enumerate(diverse):
                size = 40 + idx * 10
                draw.ellipse([x - size, y - size, x + size, y + size], fill=[c2, c3, c4, c2, c3][idx], outline=c1, width=3)
            for col in range(4):
                for row in range(3):
                    left = 620 + col * 72
                    top = 320 + row * 72
                    draw.rounded_rectangle([left, top, left + 46, top + 46], radius=12, fill=c4, outline=c3, width=3)
            draw.polygon([(515, 500), (610, 460), (610, 540)], fill=c2)
        else:
            draw.ellipse([290, 260, 734, 704], fill=_hexless_lerp(c4, c1, 0.15), outline=c3, width=4)
            draw.rounded_rectangle([382, 352, 642, 612], radius=34, fill=c2, outline=c3, width=4)
            for radius in (220, 280, 340):
                draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=215, end=330, fill=_hexless_lerp(c3, c4, 0.35), width=6)

        # Glow suave
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.ellipse([260, 220, 780, 780], fill=(*c2, 70))
        glow = glow.filter(ImageFilter.GaussianBlur(48))
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

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
    1. Google Imagen 3
    2. Gemini 2.0 Flash image generation (Nano Banana)
    3. Pollinations.ai (fallback gratuito)
    """
    img_prompt = await _build_image_prompt_smart(linkedin_text)
    key = settings.google_api_key

    if key:
        # Intento 1: Google Imagen 3
        result = await _generate_imagen3(img_prompt, key)
        if result:
            logger.info("Nano Banana: imagen generada con Imagen 3")
            return result

        # Intento 2: Gemini 2.0 Flash image generation (Nano Banana)
        result = await _generate_gemini_image(img_prompt, key)
        if result:
            logger.info("Nano Banana: imagen generada con Gemini Flash")
            return result

        logger.warning("Nano Banana: Google API falló, usando Pollinations como fallback")

    # Intento 3: Pollinations.ai
    result = await _generate_pollinations(img_prompt)
    if result:
        logger.info("Nano Banana: imagen generada con Pollinations")
        return result

    # Último recurso: placeholder con Pillow (sin internet, siempre funciona)
    logger.warning("Nano Banana: todos los servicios fallaron, usando placeholder con Pillow")
    return _generate_placeholder_image(linkedin_text)


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
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, headers=headers
        ) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.content
            logger.warning(f"PDF download devolvió status {r.status_code} para {url}")
    except Exception as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e) and "arxiv.org" in (url or ""):
            logger.warning("PDF arXiv falló por certificado; reintentando sin verificación SSL")
            try:
                async with httpx.AsyncClient(
                    timeout=30,
                    follow_redirects=True,
                    headers=headers,
                    verify=False,
                ) as client:
                    r = await client.get(url)
                    if r.status_code == 200:
                        return r.content
                    logger.warning(f"PDF download fallback devolvió status {r.status_code} para {url}")
            except Exception as fallback_e:
                logger.error(f"Error descargando PDF con fallback SSL: {fallback_e}")
        else:
            logger.error(f"Error descargando PDF: {e}")
    return None


def _render_pdf_first_page_image_sync(pdf_bytes: bytes) -> Optional[bytes]:
    """Renderiza la primera pagina completa en un canvas 4:5 para LinkedIn."""
    try:
        import io
        import fitz
        from PIL import Image

        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if doc.page_count < 1:
                return None
            page = doc.load_page(0)
            target_width = 1800
            zoom = max(1.0, min(3.5, target_width / max(float(page.rect.width), 1.0)))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)

        page_img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

        canvas_w, canvas_h = 1800, 2250
        padding = 70
        max_w = canvas_w - (padding * 2)
        max_h = canvas_h - (padding * 2)
        scale = min(max_w / page_img.width, max_h / page_img.height)
        fitted_size = (
            max(1, int(page_img.width * scale)),
            max(1, int(page_img.height * scale)),
        )
        page_img = page_img.resize(fitted_size, Image.Resampling.LANCZOS)

        img = Image.new("RGB", (canvas_w, canvas_h), "white")
        x = (canvas_w - fitted_size[0]) // 2
        y = (canvas_h - fitted_size[1]) // 2
        img.paste(page_img, (x, y))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92, optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Error renderizando primera pagina del PDF: {e}")
        return None


async def render_pdf_first_page_image(pdf_url: str) -> Optional[bytes]:
    """
    Descarga un PDF y convierte su primera pagina en imagen.

    Para papers de arXiv esto permite publicar una vista con titulo y resumen,
    en lugar de subir el PDF como documento.
    """
    pdf_bytes = await download_pdf(pdf_url)
    if not pdf_bytes:
        return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _render_pdf_first_page_image_sync, pdf_bytes)
