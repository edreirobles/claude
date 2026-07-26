from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "x_to_linkedin.db"
sys.path.insert(0, str(ROOT))

from app.services.post_generator import (  # noqa: E402
    _clean_generated_post_output,
    _ensure_source_line,
    _generate_text_with_provider,
)


SYSTEM_PROMPT = """Eres editor senior de LinkedIn para Edrei Robles.

Tu tarea es convertir borradores planos en posts con storytelling, criterio y lectura práctica.

Voz:
Español de México.
Ejecutivo, cercano, directo, didáctico y con criterio.
Técnico cuando hace falta, pero siempre entendible.
Nada de vendehumo, nada de frases grandilocuentes.

Estilo esperado:
Empieza con una tensión, una escena concreta, un contraste o una pregunta incómoda.
Haz que se sienta como una reflexión profesional, no como un resumen de herramienta o paper.
Usa la fuente de manera visible dentro del cuerpo. El lector debe entender qué herramienta, paper, caso o idea disparó el post.
Construye una mini historia con 5 a 7 párrafos cortos.
Cada párrafo debe tener una intención clara.
Muestra por qué importa para negocio, educación, productividad o trabajo real.
Aterriza una consecuencia práctica.
Cierra con una idea que deje pensando. No cierres siempre con pregunta.

Reglas duras:
No inventes datos, fechas, nombres, cifras, funcionalidades ni promesas que no estén en el contexto.
No inventes experiencia personal.
No digas ni insinúes que Edrei probó, usó, abrió, entró, implementó o vio directamente una herramienta si el campo EXPERIENCIA DIRECTA PERMITIDA dice NO.
Si EXPERIENCIA DIRECTA PERMITIDA dice NO, presenta la pieza como análisis, escenario profesional, lectura de la fuente, recomendación práctica o tensión de adopción.
Si EXPERIENCIA DIRECTA PERMITIDA dice NO, puedes usar escenas plausibles en tercera persona o modo general, pero nunca frases como "probé", "abrí", "entré", "me pasó", "en mi experiencia", "le pedí" o "usé".
Si EXPERIENCIA DIRECTA PERMITIDA dice NO, evita también segunda persona demasiado testimonial como "estás", "tienes", "entraste", "abres", "abriste", "sales", "saliste", "llegas", "ves", "pides", "recibes" o "usas". Prefiere "un docente", "un equipo", "una universidad", "una empresa" o "el caso de X".
Si EXPERIENCIA DIRECTA PERMITIDA dice SÍ, puedes usar primera persona con moderación, pero solo si aporta naturalidad y no inventa detalles concretos.
No uses frases de procedencia como "según su página", "leí sobre", "la fuente dice", "el artículo de donde sale" o "en arXiv".
No uses hashtags.
No uses bullets.
No uses guiones medios ni guiones largos. Evita los caracteres -, –, —.
No uses dos puntos en el cuerpo del post.
La única línea con dos puntos debe ser la última y debe decir exactamente Fuente: <URL>.
No repitas frases del borrador actual si suenan mecánicas.
No empieces con fórmulas como "Un buen uso", "El caso interesante", "Con herramientas como" o "El uso más útil".
No suenes a ficha técnica, newsletter, resumen ejecutivo ni anuncio.
No propongas comprar, vender, contratar o implementar por implementar.
No uses lenguaje rebuscado o literario.
Máximo 1,650 caracteres.
Evita muletillas repetidas como "no es magia", "la consecuencia", "la lección", "no se trata de", "la pregunta no es", "caja negra" y "paga renta".
No uses la palabra "criterio" más de una vez.
Varía la arquitectura del post. No todos deben tener la misma secuencia de problema, práctica, consecuencia y cierre.

Si es arXiv:
Puedes mencionar el nombre del paper una vez si ayuda.
No digas "arXiv" dentro del cuerpo.
No menciones autores, autoras ni detalles de procedencia.
Presenta el contenido del paper, la tensión, el hallazgo y la implicación práctica.
No suenes a abstract ni a ficha bibliográfica.

Si es herramienta de IA:
Narra un caso de uso creíble y una buena práctica sin afirmar experiencia directa si no está permitida.
La herramienta debe aparecer como parte del caso, no como protagonista publicitaria.

Si es un LLM:
Muestra la tensión entre velocidad, criterio y responsabilidad.

Entrega solo el post final. Nada de explicación previa."""


COMPRESSION_PROMPT = """Eres editor senior de LinkedIn para Edrei Robles.

Acorta el post sin perder fuerza narrativa, claridad ni criterio.

Reglas:
Máximo 1,550 caracteres.
Conserva 5 párrafos cortos.
Mantén la fuente como última línea exacta.
No uses hashtags.
No uses bullets.
No uses guiones medios ni guiones largos.
No uses dos puntos en el cuerpo del post.
No inventes datos.
No inventes experiencia personal ni mantengas frases que digan que Edrei probó, abrió, usó o vio directamente algo si el texto no lo permite.
Entrega solo el post final."""


NEUTRALIZE_EXPERIENCE_PROMPT = """Eres editor senior de LinkedIn para Edrei Robles.

Reescribe el post para eliminar cualquier experiencia personal inventada.

Reglas:
No digas que Edrei probó, usó, abrió, entró, vio, implementó o pidió algo a una herramienta.
Convierte esas partes en escenario profesional, análisis, lectura de la fuente o recomendación práctica.
Si no hay experiencia directa permitida, elimina también segunda persona testimonial como "estás", "tienes", "entraste", "abres", "abriste", "sales", "saliste", "llegas", "ves", "pides", "recibes" o "usas".
Prefiere sujetos concretos en tercera persona, por ejemplo "un docente", "un equipo", "una universidad" o "una empresa".
Si es un paper o artículo, no menciones arXiv, autores ni procedencia. Presenta el contenido.
Mantén el storytelling y la tensión del texto.
Máximo 1,550 caracteres.
Conserva 5 a 6 párrafos.
No uses hashtags.
No uses bullets.
No uses guiones medios ni guiones largos.
No uses dos puntos en el cuerpo.
Mantén la fuente como última línea exacta.
Entrega solo el post final."""


@dataclass(frozen=True)
class ScheduledDraft:
    id: int
    scheduled_at: str
    tweet_url: str
    tweet_text: str
    tweet_author: str
    linkedin_text: str
    media_type: str


DIRECT_EXPERIENCE_NAMES = (
    "chatgpt",
    "claude",
    "gemini",
    "deepseek",
    "qwen",
    "grok",
    "meta ai",
    "le chat",
    "google",
    "notebooklm",
)


FORBIDDEN_DIRECT_EXPERIENCE_RE = re.compile(
    r"\b("
    r"probé|probamos|he probado|"
    r"usé|usamos|he usado|"
    r"abr[ií]|abrimos|"
    r"entré|entramos|entro|"
    r"vi|vimos|"
    r"me pas[oó]|nos pas[oó]|"
    r"me encontr[eé]|nos encontramos|"
    r"le ped[ií]|pedimos|"
    r"implement[eé]|implementamos|"
    r"le[ií]|le[ií]mos|"
    r"salgo|sal[ií]|salimos|"
    r"recib[ií]|recibimos|"
    r"llegu[eé]|llegamos|"
    r"volv[ií]|volvemos|volvimos|"
    r"estuve|estuvimos|"
    r"en mi experiencia|en nuestra experiencia"
    r")\b",
    flags=re.IGNORECASE,
)

FORBIDDEN_NON_DIRECT_SECOND_PERSON_RE = re.compile(
    r"\b(estás|tienes|entraste|abres|abriste|sales|saliste|llegas|ves|pides|recibes|usas)\b",
    flags=re.IGNORECASE,
)

FORBIDDEN_SOURCEY_BODY_RE = re.compile(
    r"\b(según su página|segun su pagina|leí sobre|lei sobre|la fuente dice|en arxiv)\b",
    flags=re.IGNORECASE,
)

FORBIDDEN_PAPER_BODY_RE = re.compile(
    r"\b(arxiv|los autores|las autoras|autor(?:es|as)?)\b",
    flags=re.IGNORECASE,
)


def allows_direct_experience(draft: ScheduledDraft) -> bool:
    haystack = f"{draft.tweet_author} {draft.tweet_url} {draft.tweet_text}".lower()
    return any(name in haystack for name in DIRECT_EXPERIENCE_NAMES)


def is_paper_source(draft: ScheduledDraft) -> bool:
    haystack = f"{draft.tweet_author} {draft.tweet_url} {draft.media_type}".lower()
    return "arxiv.org" in haystack or "arxiv" in haystack or draft.media_type == "paper_image"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_scheduled_posts(
    start_id: int | None = None,
    limit: int | None = None,
    ids: list[int] | None = None,
    include_cancelled: bool = False,
) -> list[ScheduledDraft]:
    query = """
        select id, scheduled_at, tweet_url, tweet_text, tweet_author, linkedin_text, media_type
        from scheduled_posts
        where status = 'scheduled'
    """
    params: list[object] = []
    if include_cancelled:
        query = """
            select id, scheduled_at, tweet_url, tweet_text, tweet_author, linkedin_text, media_type
            from scheduled_posts
            where status in ('scheduled', 'cancelled')
        """
    if ids:
        placeholders = ",".join("?" for _ in ids)
        query += f" and id in ({placeholders})"
        params.extend(ids)
    if start_id is not None:
        query += " and id >= ?"
        params.append(start_id)
    query += " order by scheduled_at asc, id asc"
    if limit is not None:
        query += " limit ?"
        params.append(limit)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        ScheduledDraft(
            id=int(row["id"]),
            scheduled_at=str(row["scheduled_at"] or ""),
            tweet_url=str(row["tweet_url"] or ""),
            tweet_text=str(row["tweet_text"] or ""),
            tweet_author=str(row["tweet_author"] or ""),
            linkedin_text=str(row["linkedin_text"] or ""),
            media_type=str(row["media_type"] or ""),
        )
        for row in rows
    ]


def _compact(text: str, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "..."


def build_user_message(draft: ScheduledDraft) -> str:
    direct_experience = "SÍ" if allows_direct_experience(draft) else "NO"
    source_type = "PAPER O ARTÍCULO ACADÉMICO" if is_paper_source(draft) else "HERRAMIENTA, PRODUCTO O FUENTE WEB"
    return f"""Reescribe esta publicación desde cero.

FECHA PROGRAMADA:
{draft.scheduled_at}

TIPO DE MEDIA:
{draft.media_type}

EXPERIENCIA DIRECTA PERMITIDA:
{direct_experience}

TIPO DE FUENTE:
{source_type}

FUENTE:
{draft.tweet_url}

ACTOR, HERRAMIENTA O PUBLICACIÓN:
{draft.tweet_author or "Sin nombre explícito"}

CONTEXTO DE FUENTE:
{_compact(draft.tweet_text, 2400)}

BORRADOR ACTUAL:
{_compact(draft.linkedin_text, 2400)}

Recuerda que la última línea debe ser:
Fuente: {draft.tweet_url}
"""


def _strip_hashtags(text: str) -> str:
    text = re.sub(r"(?<!\S)#\w+", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _remove_forbidden_dashes(text: str) -> str:
    text = text.replace("—", ", ")
    text = text.replace("–", ", ")
    text = text.replace("‑", " ")
    text = text.replace("‒", " ")
    text = text.replace("−", " ")
    text = re.sub(r"\s+-\s+", ", ", text)
    text = re.sub(r"(?<=\w)-(?=\w)", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def _remove_body_colons(text: str, source_url: str) -> str:
    body, _ = _split_source(text)
    body = body.replace(":", ",")
    return _ensure_source_line(body, source_url)


def _split_source(text: str) -> tuple[str, str]:
    match = re.search(r"(?im)^\s*Fuente:\s*\S+\s*$", text or "")
    if not match:
        return (text or "").strip(), ""
    return (text[: match.start()] or "").strip(), match.group(0).strip()


def clean_post(text: str, source_url: str) -> str:
    cleaned = _clean_generated_post_output(text or "")
    cleaned = cleaned.replace("```", "").strip()
    cleaned = re.sub(r"\b(\d{1,2}),(\d{2})\b", r"\1 con \2", cleaned)
    cleaned = re.sub(r"(?im)^\s*(fuente exacta|url de fuente|source exact)\s*[,.:].*$", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*(post final|publicación final|versión final)\s*:?\s*$", "", cleaned)
    cleaned = _strip_hashtags(cleaned)
    cleaned = _remove_forbidden_dashes(cleaned)
    cleaned = _ensure_source_line(cleaned, source_url)
    cleaned = _remove_body_colons(cleaned, source_url)
    body, _ = _split_source(cleaned)

    lines = [line.strip() for line in body.splitlines()]
    normalized_lines: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line
        if is_blank and previous_blank:
            continue
        normalized_lines.append(line)
        previous_blank = is_blank

    body = "\n".join(normalized_lines).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"[ \t]{2,}", " ", body)
    return _ensure_source_line(body, source_url)


def quality_issues(text: str, source_url: str) -> list[str]:
    issues: list[str] = []
    body, source = _split_source(text)
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    if not source.strip().lower().startswith("fuente:"):
        issues.append("missing_source")
    if source_url and source_url not in source:
        issues.append("wrong_source")
    if len(paragraphs) < 4:
        issues.append("too_few_paragraphs")
    if len(text) > 1650:
        issues.append("too_long")
    if re.search(r"\b\d{1,2},\d{2}\b", body):
        issues.append("comma_time")
    if re.search(r"(?<!\S)#\w+", text):
        issues.append("has_hashtags")
    if any(ch in body for ch in ("—", "–", "‑", "‒", "−")) or re.search(r"\s+-\s+", body):
        issues.append("has_dashes")
    if ":" in body:
        issues.append("body_colon")
    if re.search(r"(?im)^\s*(fuente exacta|url de fuente|source exact)\s*[,.:]", body):
        issues.append("meta_source_line_in_body")
    mechanical_starts = (
        "un buen uso",
        "el caso interesante",
        "con herramientas como",
        "el uso más útil",
        "un paper reciente",
    )
    first = paragraphs[0].lower() if paragraphs else ""
    if first.startswith(mechanical_starts):
        issues.append("mechanical_start")
    return issues


def quality_issues_for_draft(text: str, draft: ScheduledDraft) -> list[str]:
    issues = quality_issues(text, draft.tweet_url)
    if not allows_direct_experience(draft):
        body, _ = _split_source(text)
        if FORBIDDEN_DIRECT_EXPERIENCE_RE.search(body):
            issues.append("fake_direct_experience")
        if FORBIDDEN_NON_DIRECT_SECOND_PERSON_RE.search(body):
            issues.append("too_testimonial_second_person")
    body, _ = _split_source(text)
    if FORBIDDEN_SOURCEY_BODY_RE.search(body):
        issues.append("sourcey_body")
    if is_paper_source(draft) and FORBIDDEN_PAPER_BODY_RE.search(body):
        issues.append("paper_source_or_author_body")
    return issues


async def rewrite_one(draft: ScheduledDraft, semaphore: asyncio.Semaphore) -> tuple[int, str, list[str] | None]:
    async with semaphore:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                extra = ""
                if attempt > 1:
                    extra = (
                        "\n\nLa versión anterior falló controles de calidad. "
                        "Hazla más narrativa, más concreta y respeta todas las reglas duras."
                    )
                raw = await _generate_text_with_provider(
                    system_prompt=SYSTEM_PROMPT,
                    user_message=build_user_message(draft) + extra,
                    max_output_tokens=950,
                )
                cleaned = clean_post(raw, draft.tweet_url)
                issues = quality_issues_for_draft(cleaned, draft)
                if not issues:
                    return draft.id, cleaned, None
                if (
                    "fake_direct_experience" in issues
                    or "too_testimonial_second_person" in issues
                    or "sourcey_body" in issues
                    or "paper_source_or_author_body" in issues
                    or "comma_time" in issues
                ):
                    neutralized = await _generate_text_with_provider(
                        system_prompt=NEUTRALIZE_EXPERIENCE_PROMPT,
                        user_message=(
                            "Elimina experiencia personal inventada de este post sin perder calidad.\n\n"
                            f"POST:\n{cleaned}\n\n"
                            f"FUENTE EXACTA: {draft.tweet_url}\n\n"
                            f"CONTEXTO DE FUENTE:\n{_compact(draft.tweet_text, 1800)}"
                        ),
                        max_output_tokens=750,
                    )
                    neutralized_clean = clean_post(neutralized, draft.tweet_url)
                    neutralized_issues = quality_issues_for_draft(neutralized_clean, draft)
                    if not neutralized_issues:
                        return draft.id, neutralized_clean, None
                    issues = neutralized_issues
                    cleaned = neutralized_clean
                if issues == ["too_long"]:
                    compressed = await _generate_text_with_provider(
                        system_prompt=COMPRESSION_PROMPT,
                        user_message=(
                            "Acorta este post conservando su idea central y la fuente final.\n\n"
                            f"POST:\n{cleaned}\n\n"
                            f"FUENTE EXACTA: {draft.tweet_url}"
                        ),
                        max_output_tokens=700,
                    )
                    compressed_clean = clean_post(compressed, draft.tweet_url)
                    compressed_issues = quality_issues_for_draft(compressed_clean, draft)
                    if not compressed_issues:
                        return draft.id, compressed_clean, None
                    last_error = RuntimeError(
                        f"quality issues: {', '.join(compressed_issues)}"
                    )
                    continue
                last_error = RuntimeError(f"quality issues: {', '.join(issues)}")
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(1.5 * attempt)

        fallback = clean_post(draft.linkedin_text, draft.tweet_url)
        return draft.id, fallback, [str(last_error or "unknown error")]


def save_results(results: list[tuple[int, str, list[str] | None]]) -> None:
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    with _connect() as conn:
        for post_id, rewritten, errors in results:
            if errors:
                continue
            conn.execute(
                """
                update scheduled_posts
                set linkedin_text = ?,
                    error_message = null,
                    generated_image_path = case
                        when media_type = 'generate' then null
                        else generated_image_path
                    end,
                    created_at = created_at
                where id = ?
                """,
                (rewritten, post_id),
            )
        conn.commit()
    print(f"updated_at_utc={now}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Rewrite future scheduled posts with stronger storytelling.")
    parser.add_argument("--dry-run", action="store_true", help="Generate but do not write to DB.")
    parser.add_argument("--limit", type=int, default=None, help="Only process N posts.")
    parser.add_argument("--start-id", type=int, default=None, help="Only process posts with id >= START_ID.")
    parser.add_argument("--ids", default="", help="Comma-separated post IDs to process.")
    parser.add_argument("--include-cancelled", action="store_true", help="Include cancelled posts, useful for replacing today's cancelled slot.")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrent generation calls.")
    args = parser.parse_args()

    ids = [int(item.strip()) for item in args.ids.split(",") if item.strip()]
    drafts = load_scheduled_posts(
        start_id=args.start_id,
        limit=args.limit,
        ids=ids or None,
        include_cancelled=args.include_cancelled,
    )
    if not drafts:
        print("No scheduled posts found.")
        return 0

    print(f"posts_to_rewrite={len(drafts)} dry_run={args.dry_run} concurrency={args.concurrency}")
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    results: list[tuple[int, str, list[str] | None]] = []

    completed = 0
    for future in asyncio.as_completed([rewrite_one(draft, semaphore) for draft in drafts]):
        result = await future
        results.append(result)
        completed += 1
        post_id, text, errors = result
        status = "error" if errors else "ok"
        preview = _compact(text.split("\n\n", 1)[0], 110)
        print(f"{completed}/{len(drafts)} post_id={post_id} status={status} preview={preview}")

    failed = [item for item in results if item[2]]
    if args.dry_run:
        print("Dry run. No DB updates were written.")
    else:
        save_results(results)

    print(f"success={len(results) - len(failed)} failed={len(failed)}")
    if failed:
        for post_id, _, errors in failed[:10]:
            print(f"failed_post_id={post_id} error={errors}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
