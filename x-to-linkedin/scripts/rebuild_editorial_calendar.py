"""
Rebuild the future editorial calendar with one 9 AM post per day.

Rules:
- Monday and Friday: recent arXiv papers about AI in higher education or work.
- Tuesday and Saturday: AI education tool use case or best practice.
- Wednesday: AI productivity tool use case or best practice.
- Thursday and Sunday: Claude, ChatGPT, DeepSeek, Gemini, or similar LLM practice.
"""
from __future__ import annotations

import asyncio
import html
import json
import re
import sqlite3
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "x_to_linkedin.db"
SCHEDULER_DB_PATH = ROOT / "scheduler_jobs.db"
MX_TZ = ZoneInfo("America/Mexico_City")
END_DATE = date(2026, 7, 31)
POST_HOUR = 9


@dataclass
class Source:
    kind: str
    name: str
    url: str
    title: str
    angle: str
    practice: str
    consequence: str
    image_url: str = ""
    abstract: str = ""
    published: date | None = None
    pdf_url: str | None = None


EDU_TOOLS = [
    Source("education_tool", "Gradescope", "https://www.gradescope.com/", "Gradescope", "retroalimentación más consistente en evaluaciones grandes", "usar rúbricas explícitas antes de automatizar cualquier revisión", "el profesor recupera tiempo sin convertir la evaluación en una caja negra"),
    Source("education_tool", "Perusall", "https://www.perusall.com/", "Perusall", "lectura activa con señales tempranas de participación", "mirar patrones de discusión antes de la clase, no solo calificaciones al final", "la sesión presencial llega mejor enfocada porque ya se ven dudas reales"),
    Source("education_tool", "MagicSchool", "https://www.magicschool.ai/", "MagicSchool AI", "planeación docente más rápida sin perder intención pedagógica", "pedir borradores y luego ajustar con criterio propio", "la IA acelera la preparación, pero la decisión didáctica sigue siendo humana"),
    Source("education_tool", "Brisk Teaching", "https://www.briskteaching.com/", "Brisk Teaching", "adaptación rápida de materiales para distintos niveles", "convertir un recurso base en versiones con apoyos distintos", "la inclusión deja de depender de rehacer todo desde cero"),
    Source("education_tool", "Diffit", "https://web.diffit.me/", "Diffit", "diferenciación de lectura sin bajar la expectativa académica", "ajustar acceso al texto, no simplificar la pregunta intelectual", "más estudiantes pueden entrar al tema sin que la clase pierda profundidad"),
    Source("education_tool", "Curipod", "https://curipod.com/", "Curipod", "actividades interactivas que obligan a pensar en clase", "usar la IA para diseñar preguntas que revelen razonamiento, no para llenar diapositivas", "la participación se vuelve evidencia útil, no solo movimiento en pantalla"),
    Source("education_tool", "Quizizz AI", "https://quizizz.com/ai", "Quizizz AI", "evaluación formativa rápida durante una secuencia", "generar preguntas y depurarlas contra el objetivo de aprendizaje", "el quiz deja de ser trámite y se vuelve sensor de comprensión"),
    Source("education_tool", "Formative", "https://goformative.com/", "Formative", "seguimiento en tiempo real de respuestas estudiantiles", "revisar errores comunes antes de avanzar", "la clase se ajusta mientras todavía hay tiempo de intervenir"),
    Source("education_tool", "SchoolAI", "https://schoolai.com/", "SchoolAI", "espacios guiados para practicar ideas con IA", "definir límites claros de la conversación y revisar evidencias después", "el estudiante practica más, pero el docente conserva la dirección"),
    Source("education_tool", "TeachFX", "https://teachfx.com/", "TeachFX", "analítica de conversación en el aula", "usar datos de participación para mejorar preguntas y silencios", "la reflexión docente se apoya en evidencia, no en memoria borrosa"),
    Source("education_tool", "Eduaide", "https://www.eduaide.ai/", "Eduaide.AI", "diseño de recursos y apoyos para clase", "tratar cada salida como primer borrador revisable", "la productividad docente mejora si la revisión pedagógica no se salta"),
    Source("education_tool", "Elicit", "https://elicit.com/", "Elicit", "búsqueda y síntesis de literatura para cursos avanzados", "comparar evidencia antes de convertir un paper en actividad", "los estudiantes ven investigación viva sin ahogarse en el volumen"),
    Source("education_tool", "Consensus", "https://consensus.app/", "Consensus", "preguntas de investigación con evidencia rastreable", "pedir respuestas que obliguen a revisar el paper fuente", "la IA ayuda a entrar a la literatura, no a reemplazarla"),
    Source("education_tool", "Scite", "https://scite.ai/", "Scite", "lectura crítica de citas académicas", "revisar si una cita apoya, contrasta o solo menciona un hallazgo", "citar se vuelve una práctica de criterio, no de acumulación"),
    Source("education_tool", "Iris.ai", "https://iris.ai/", "Iris.ai", "mapear literatura alrededor de un problema de investigación", "usar el mapa para formular mejores preguntas antes de leer todo", "la exploración bibliográfica se vuelve más estratégica"),
    Source("education_tool", "Century Tech", "https://www.century.tech/", "Century Tech", "rutas de práctica adaptativa", "combinar datos de desempeño con intervención docente", "la personalización sirve más cuando no se delega toda la tutoría"),
]


PRODUCTIVITY_TOOLS = [
    Source("productivity_tool", "Granola", "https://www.granola.ai/", "Granola", "notas de reunión sin perder atención", "anotar solo decisiones y matices mientras la IA captura estructura", "la reunión produce memoria útil sin convertir a todos en secretarios"),
    Source("productivity_tool", "Fathom", "https://fathom.video/", "Fathom", "seguimiento de acuerdos después de llamadas", "separar resumen, decisiones y próximos pasos", "menos trabajo se pierde entre la conversación y la ejecución"),
    Source("productivity_tool", "Fireflies", "https://fireflies.ai/", "Fireflies.ai", "búsqueda sobre conversaciones pasadas", "nombrar temas y responsables desde el cierre de la llamada", "las reuniones se vuelven base de conocimiento, no ruido archivado"),
    Source("productivity_tool", "Read AI", "https://www.read.ai/", "Read AI", "diagnóstico de reuniones largas", "revisar señales de participación y claridad antes de agendar otra junta", "la productividad mejora cuando también se mide el costo de reunirse"),
    Source("productivity_tool", "Reclaim", "https://reclaim.ai/", "Reclaim AI", "protección automática de bloques de trabajo", "bloquear foco antes de llenar la semana con pendientes ajenos", "el calendario empieza a defender prioridades reales"),
    Source("productivity_tool", "Motion", "https://www.usemotion.com/", "Motion", "priorización dinámica de tareas", "dar fechas, esfuerzo y prioridad antes de pedir magia", "la automatización ordena mejor cuando recibe criterios claros"),
    Source("productivity_tool", "Zapier AI", "https://zapier.com/ai", "Zapier AI", "automatización ligera entre herramientas", "empezar por flujos repetidos y medibles", "la IA deja de ser demo cuando reduce pasos concretos"),
    Source("productivity_tool", "Notion AI", "https://www.notion.com/product/ai", "Notion AI", "síntesis dentro de documentación de equipo", "pedir resúmenes que terminen en decisiones o pendientes", "la documentación se vuelve operativa, no solo bonita"),
    Source("productivity_tool", "Grammarly", "https://www.grammarly.com/ai", "Grammarly AI", "mejorar claridad de comunicación escrita", "revisar tono, intención y precisión antes de mandar", "menos fricción aparece cuando el mensaje llega limpio"),
    Source("productivity_tool", "Canva Magic Studio", "https://www.canva.com/magic/", "Canva Magic Studio", "prototipar piezas visuales más rápido", "usar la IA para explorar dirección visual y luego editar", "el equipo llega antes a una versión discutible"),
    Source("productivity_tool", "Descript", "https://www.descript.com/", "Descript", "edición de video y audio desde texto", "convertir una grabación larga en clips con una tesis clara", "el contenido sale del backlog y se vuelve reutilizable"),
    Source("productivity_tool", "Gamma", "https://gamma.app/", "Gamma", "primer borrador de presentaciones", "arrancar con estructura narrativa antes de decorar", "la IA acelera el deck si primero hay una idea que defender"),
    Source("productivity_tool", "Loom AI", "https://www.loom.com/features/loom-ai", "Loom AI", "comunicación asíncrona más clara", "grabar contexto breve y dejar que la IA genere resumen y capítulos", "se reducen juntas cuando el mensaje viaja bien"),
    Source("productivity_tool", "Airtable AI", "https://www.airtable.com/platform/ai", "Airtable AI", "operaciones con datos semiestructurados", "automatizar clasificación y seguimiento en una base compartida", "la IA rinde más cuando vive cerca del proceso"),
]


LLM_TOOLS = [
    Source("llm_tool", "Claude", "https://www.anthropic.com/claude", "Claude", "trabajo profundo con documentos largos", "dar contexto, criterio de salida y ejemplos de buen razonamiento", "el modelo sirve mejor como contraparte de pensamiento que como redactora automática"),
    Source("llm_tool", "ChatGPT", "https://openai.com/chatgpt/", "ChatGPT", "exploración rápida de escenarios", "pedir alternativas con supuestos visibles", "la velocidad ayuda si no se confunde una respuesta fluida con una decisión"),
    Source("llm_tool", "DeepSeek", "https://www.deepseek.com/", "DeepSeek", "comparar razonamientos antes de decidir", "usar el modelo como segundo punto de vista técnico", "la diversidad de modelos reduce dependencia de una sola voz"),
    Source("llm_tool", "Gemini", "https://gemini.google/", "Gemini", "trabajo multimodal con archivos y contexto", "llevar evidencia visual o documental al análisis", "la conversación mejora cuando el modelo ve más que texto suelto"),
    Source("llm_tool", "Le Chat", "https://mistral.ai/products/le-chat", "Mistral Le Chat", "asistente para equipos que necesitan rapidez", "pedir respuestas cortas con trazabilidad de supuestos", "la utilidad aparece cuando el equipo puede revisar el camino"),
    Source("llm_tool", "Perplexity", "https://www.perplexity.ai/", "Perplexity", "investigación con enlaces visibles", "usar la respuesta como mapa inicial y abrir las fuentes", "buscar con IA no sustituye verificar, pero sí acorta el arranque"),
    Source("llm_tool", "Microsoft Copilot", "https://copilot.microsoft.com/", "Microsoft Copilot", "apoyo dentro del flujo de trabajo diario", "pedir síntesis conectadas con tareas concretas", "el asistente funciona mejor cuando vive donde ocurre el trabajo"),
    Source("llm_tool", "Grok", "https://x.ai/grok", "Grok", "lectura rápida de conversaciones públicas", "separar señal, postura y evidencia antes de reaccionar", "la velocidad social necesita más criterio, no menos"),
    Source("llm_tool", "Meta AI", "https://www.meta.ai/", "Meta AI", "asistencia ligera en contextos cotidianos", "convertir ideas dispersas en próximos pasos simples", "la IA de uso diario vale si baja fricción sin inflar el problema"),
    Source("llm_tool", "Qwen", "https://chat.qwen.ai/", "Qwen", "experimentación con modelos alternativos", "probar la misma tarea con criterios de evaluación claros", "comparar modelos revela fortalezas que no salen en benchmarks genéricos"),
]


ARXIV_QUERIES = [
    'all:"artificial intelligence" AND all:"higher education"',
    'all:"generative AI" AND all:"higher education"',
    'all:"AI" AND all:"education" AND all:"university"',
    'all:"AI" AND all:"future of work"',
    'all:"artificial intelligence" AND all:"workforce"',
]


def clean(value: str) -> str:
    return " ".join(html.unescape(value or "").split())


def arxiv_pdf_url(abs_url: str) -> str:
    match = re.search(r"/abs/(\d{4}\.\d{4,5})(?:v\d+)?", abs_url)
    if not match:
        return abs_url.replace("/abs/", "/pdf/")
    return f"https://arxiv.org/pdf/{match.group(1)}.pdf"


async def fetch_arxiv_sources() -> list[Source]:
    sources: list[Source] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=30, verify=False, follow_redirects=True) as client:
        for query in ARXIV_QUERIES:
            params = {
                "search_query": query,
                "start": "0",
                "max_results": "35",
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
            url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
            response = await client.get(url)
            if response.status_code != 200:
                continue
            soup = BeautifulSoup(response.text, "lxml-xml")
            for entry in soup.find_all("entry"):
                abs_url = clean(entry.find("id").get_text("", strip=True) if entry.find("id") else "")
                canonical = re.sub(r"v\d+$", "", abs_url)
                if canonical in seen:
                    continue
                seen.add(canonical)
                title = clean(entry.find("title").get_text(" ", strip=True) if entry.find("title") else "")
                abstract = clean(entry.find("summary").get_text(" ", strip=True) if entry.find("summary") else "")
                published_raw = clean(entry.find("published").get_text("", strip=True) if entry.find("published") else "")
                try:
                    published = datetime.fromisoformat(published_raw.replace("Z", "+00:00")).date()
                except Exception:
                    published = None
                topic = "IA y educación superior"
                haystack = f"{title} {abstract}".lower()
                if any(word in haystack for word in ("work", "worker", "workforce", "labor", "employment", "skills")):
                    topic = "IA y futuro del trabajo"
                sources.append(
                    Source(
                        kind="arxiv",
                        name="arXiv",
                        url=canonical.replace("http://", "https://"),
                        title=title,
                        angle=topic,
                        practice="leer el hallazgo como señal para diseñar mejores sistemas, no como predicción automática",
                        consequence="las decisiones de adopción de IA necesitan evidencia reciente y preguntas concretas",
                        abstract=abstract,
                        published=published,
                        pdf_url=arxiv_pdf_url(canonical),
                    )
                )
    return sources


async def fetch_image_url(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15, verify=False, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                return ""
            soup = BeautifulSoup(response.text, "lxml")
            candidates = []
            for selector, attr in (
                ('meta[property="og:image"]', "content"),
                ('meta[name="twitter:image"]', "content"),
                ('meta[property="twitter:image"]', "content"),
            ):
                el = soup.select_one(selector)
                if el and el.get(attr):
                    candidates.append(urljoin(str(response.url), el.get(attr, "")))
            for candidate in candidates:
                lowered = candidate.lower()
                if candidate.startswith("http") and not lowered.endswith(".svg"):
                    return candidate
    except Exception:
        return ""
    return ""


async def enrich_images(sources: Iterable[Source]) -> None:
    for source in sources:
        source.image_url = await fetch_image_url(source.url)


def post_for_arxiv(source: Source, post_date: date, index: int) -> str:
    title = source.title.rstrip(".")
    abstract_sentence = source.abstract.split(". ")[0].strip()
    if len(abstract_sentence) > 220:
        abstract_sentence = abstract_sentence[:220].rsplit(" ", 1)[0] + "..."
    opening = [
        f"Un paper reciente de arXiv sobre {source.angle} deja una pregunta incómoda: qué parte del cambio estamos diseñando y qué parte solo estamos dejando que pase.",
        f"Hay papers que no sirven para decir “la IA va a cambiar todo”, sino para aterrizar dónde se empieza a notar el cambio. Este va justo por ahí.",
        f"El punto interesante de este paper no es que hable de IA. Es que obliga a mirar la adopción con más criterio y menos entusiasmo automático.",
    ][index % 3]
    body = [
        f"El trabajo se titula “{title}”. La idea central que vale rescatar es esta: {abstract_sentence}",
        f"La fuente no la usaría como receta. La usaría como lente para revisar qué prácticas, incentivos y capacidades estamos construyendo alrededor de la IA.",
        f"Mi lectura práctica: antes de comprar o prohibir herramientas, conviene definir qué comportamiento queremos cambiar y cómo sabremos si realmente mejoró.",
    ]
    closing = "Ahí está la diferencia entre adoptar IA por moda y usarla para rediseñar mejor una forma de aprender o trabajar."
    return "\n\n".join([opening, *body, closing, f"Fuente: {source.url}"])


def post_for_tool(source: Source, post_date: date, index: int) -> str:
    if source.kind == "education_tool":
        opening = [
            f"Un buen uso de {source.name} en educación no es pedirle a la herramienta que “haga la clase”.",
            f"El caso interesante con {source.name} no está en automatizar por automatizar.",
            f"Si una herramienta como {source.name} funciona en educación, normalmente no es por la promesa de IA sino por el diseño pedagógico alrededor.",
        ][index % 3]
        middle = [
            f"La práctica que me parece más valiosa es {source.practice}.",
            f"Eso importa porque permite trabajar {source.angle} sin perder de vista el objetivo de aprendizaje.",
            f"La consecuencia práctica es simple: {source.consequence}.",
            "La tecnología ayuda, pero la mejora aparece cuando el docente decide qué evidencia quiere ver y qué hará con ella.",
        ]
    elif source.kind == "productivity_tool":
        opening = [
            f"Un caso de uso útil de {source.name}: no usarlo para hacer más cosas, sino para reducir fricción en una parte específica del trabajo.",
            f"Con herramientas como {source.name}, la pregunta no debería ser “qué puede automatizar”, sino qué decisión o seguimiento se está perdiendo hoy.",
            f"{source.name} es un buen recordatorio de que productividad con IA no significa llenar la agenda de automatizaciones.",
        ][index % 3]
        middle = [
            f"La buena práctica es {source.practice}.",
            f"Aplicado a productividad, eso aterriza en {source.angle}.",
            f"La consecuencia práctica es esta: {source.consequence}.",
            "Menos magia, más proceso. Ahí es donde la IA empieza a pagar renta.",
        ]
    else:
        opening = [
            f"Una buena forma de usar {source.name} no es pedirle respuestas finales, sino hacerlo trabajar contra un criterio claro.",
            f"Con {source.name}, el salto de calidad suele venir antes del prompt, no después.",
            f"El uso más útil de {source.name} aparece cuando dejamos de tratarlo como buscador elegante y lo usamos como contraparte.",
        ][index % 3]
        middle = [
            f"El caso concreto: {source.angle}.",
            f"La buena práctica es {source.practice}.",
            f"La consecuencia práctica es esta: {source.consequence}.",
            "Si el modelo no sabe qué significa una buena respuesta para ti, va a sonar convincente aunque no te sirva.",
        ]
    return "\n\n".join([opening, *middle, f"Fuente: {source.url}"])


def next_source(pool: list[Source], cursor: dict[str, int], key: str) -> Source:
    i = cursor.get(key, 0)
    cursor[key] = i + 1
    return pool[i % len(pool)]


def article_source_for_date(pool: list[Source], post_date: date, cursor: dict[str, int]) -> Source:
    min_date = post_date - timedelta(days=31 * 9)
    valid = [
        source for source in pool
        if source.published and min_date <= source.published <= post_date
    ]
    if not valid:
        valid = pool
    source = valid[cursor.get("arxiv", 0) % len(valid)]
    cursor["arxiv"] = cursor.get("arxiv", 0) + 1
    return source


def schedule_dates() -> list[date]:
    now_mx = datetime.now(MX_TZ)
    start = now_mx.date()
    today_slot = datetime.combine(start, time(POST_HOUR, 0), tzinfo=MX_TZ)
    if now_mx >= today_slot:
        start += timedelta(days=1)
    days = []
    current = start
    while current <= END_DATE:
        days.append(current)
        current += timedelta(days=1)
    return days


async def main() -> None:
    arxiv_sources = await fetch_arxiv_sources()
    if len(arxiv_sources) < 10:
        raise RuntimeError(f"No hay suficientes fuentes arXiv recientes: {len(arxiv_sources)}")

    await enrich_images([*EDU_TOOLS, *PRODUCTIVITY_TOOLS, *LLM_TOOLS])

    dates = schedule_dates()
    cursor: dict[str, int] = {}
    rows = []
    for idx, post_date in enumerate(dates):
        weekday = post_date.weekday()
        if weekday in (0, 4):
            source = article_source_for_date(arxiv_sources, post_date, cursor)
            linkedin_text = post_for_arxiv(source, post_date, idx)
            media_type = "paper_image"
            image_urls: list[str] = []
            pdf_url = source.pdf_url
            document_title = source.title[:500] or "Paper arXiv"
            use_first_image = False
        elif weekday in (1, 5):
            source = next_source(EDU_TOOLS, cursor, "education_tool")
            linkedin_text = post_for_tool(source, post_date, idx)
            image_urls = [source.image_url] if source.image_url else []
            media_type = "image" if image_urls else "generate"
            pdf_url = None
            document_title = "Documento"
            use_first_image = bool(image_urls)
        elif weekday == 2:
            source = next_source(PRODUCTIVITY_TOOLS, cursor, "productivity_tool")
            linkedin_text = post_for_tool(source, post_date, idx)
            image_urls = [source.image_url] if source.image_url else []
            media_type = "image" if image_urls else "generate"
            pdf_url = None
            document_title = "Documento"
            use_first_image = bool(image_urls)
        else:
            source = next_source(LLM_TOOLS, cursor, "llm_tool")
            linkedin_text = post_for_tool(source, post_date, idx)
            image_urls = [source.image_url] if source.image_url else []
            media_type = "image" if image_urls else "generate"
            pdf_url = None
            document_title = "Documento"
            use_first_image = bool(image_urls)

        scheduled_local = datetime.combine(post_date, time(POST_HOUR, 0), tzinfo=MX_TZ)
        scheduled_utc = scheduled_local.astimezone(timezone.utc).replace(tzinfo=None)
        rows.append(
            {
                "tweet_url": source.url,
                "tweet_text": f"{source.title}\n\n{source.abstract or source.angle}",
                "tweet_author": source.name,
                "linkedin_text": linkedin_text,
                "image_urls": image_urls,
                "scheduled_at": scheduled_utc,
                "status": "scheduled",
                "use_first_image": use_first_image,
                "media_type": media_type,
                "pdf_url": pdf_url,
                "document_title": document_title,
                "source": "editorial",
            }
        )

    now_utc = datetime.utcnow()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cancelled = conn.execute(
            """
            update scheduled_posts
            set status = 'cancelled',
                error_message = 'Reemplazado por calendario editorial 9 AM hasta 2026-07-31'
            where status in ('scheduled', 'pending')
              and (scheduled_at is null or scheduled_at >= ?)
            """,
            (now_utc,),
        ).rowcount

        created_ids = []
        for row in rows:
            cur = conn.execute(
                """
                insert into scheduled_posts (
                    tweet_url, tweet_text, tweet_author, linkedin_text, image_urls,
                    scheduled_at, status, created_at, use_first_image, media_type,
                    pdf_url, document_title, source
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["tweet_url"],
                    row["tweet_text"],
                    row["tweet_author"],
                    row["linkedin_text"],
                    json.dumps(row["image_urls"], ensure_ascii=False),
                    row["scheduled_at"],
                    row["status"],
                    now_utc,
                    1 if row["use_first_image"] else 0,
                    row["media_type"],
                    row["pdf_url"],
                    row["document_title"],
                    row["source"],
                ),
            )
            created_ids.append(cur.lastrowid)
        conn.commit()

    if SCHEDULER_DB_PATH.exists():
        with sqlite3.connect(SCHEDULER_DB_PATH) as conn:
            conn.execute(
                """
                delete from apscheduler_jobs
                where id like 'post_%'
                   or id like 'pre_notify_%'
                   or id like 'pre_verify_%'
                """
            )
            conn.commit()

    media_counts: dict[str, int] = {}
    for row in rows:
        media_counts[row["media_type"]] = media_counts.get(row["media_type"], 0) + 1
    print(json.dumps({
        "cancelled": cancelled,
        "created": len(created_ids),
        "first_id": created_ids[0] if created_ids else None,
        "last_id": created_ids[-1] if created_ids else None,
        "first_date": dates[0].isoformat() if dates else None,
        "last_date": dates[-1].isoformat() if dates else None,
        "media_counts": media_counts,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
