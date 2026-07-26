"""
Memoria editorial aprendida desde publicaciones historicas.

El radar usa este perfil para elegir mejores fuentes y redactar con una voz mas
cercana a los posts que ya demostraron buen desempeno.
"""
from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ScheduledPost
from .post_generator import _generate_text_with_provider, get_text_generation_config_error

logger = logging.getLogger(__name__)

PROFILE_CACHE_TTL = timedelta(hours=6)
TOP_POST_LIMIT = 28
MANUAL_REFERENCE_LIMIT = 14
WEAK_POST_LIMIT = 8
PROFILE_MAX_CHARS = 3600

_profile_cache: str | None = None
_profile_cache_at: datetime | None = None


@dataclass(slots=True)
class EditorialPostSample:
    post_id: int
    source: str
    text: str
    first_line: str
    published_at: datetime | None
    likes: int
    comments: int
    impressions: int
    clicks: int
    shares: int
    score: float


THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "educacion y aprendizaje": (
        "educacion",
        "educación",
        "aprendizaje",
        "estudiante",
        "docente",
        "profesor",
        "universidad",
        "escuela",
        "classroom",
        "learning",
        "student",
        "teacher",
    ),
    "papers y evidencia": (
        "paper",
        "estudio",
        "experimento",
        "investigacion",
        "investigación",
        "hallazgo",
        "research",
        "participantes",
    ),
    "herramientas de IA": (
        "herramienta",
        "notebooklm",
        "notebook lm",
        "workflow",
        "automatizacion",
        "automatización",
        "repositorio",
        "open source",
        "tool",
    ),
    "agentes y codigo": (
        "agente",
        "agentes",
        "agent",
        "claude code",
        "codigo",
        "código",
        "programar",
        "repositorio",
    ),
    "prompts y criterio de uso": (
        "prompt",
        "instrucciones",
        "criterio",
        "metodo",
        "método",
        "guia",
        "guía",
    ),
    "riesgos y gobernanza": (
        "riesgo",
        "seguridad",
        "privacidad",
        "evaluacion",
        "evaluación",
        "governance",
        "safety",
    ),
}


def clear_editorial_learning_cache() -> None:
    global _profile_cache, _profile_cache_at
    _profile_cache = None
    _profile_cache_at = None


def _safe_int(value: int | None) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _clean_post_text(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = re.sub(r"\n\s*Fuente:\s*\S+\s*$", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:220]
    return ""


def _engagement_score(post: ScheduledPost) -> float:
    likes = _safe_int(post.li_likes)
    comments = _safe_int(post.li_comments)
    impressions = _safe_int(post.li_impressions)
    clicks = _safe_int(post.li_clicks)
    shares = _safe_int(post.li_shares)

    actions = likes + (comments * 2) + clicks + (shares * 3)
    engagement_rate = (actions / impressions * 100) if impressions else 0.0
    impression_score = min(impressions, 150_000) / 1000
    return (
        likes * 2
        + comments * 8
        + shares * 10
        + clicks * 2
        + impression_score
        + engagement_rate * 20
    )


def _to_sample(post: ScheduledPost) -> EditorialPostSample | None:
    text = _clean_post_text(post.linkedin_text or "")
    if len(text) < 80:
        return None
    return EditorialPostSample(
        post_id=int(post.id),
        source=post.source or "manual",
        text=text,
        first_line=_first_line(text),
        published_at=post.published_at,
        likes=_safe_int(post.li_likes),
        comments=_safe_int(post.li_comments),
        impressions=_safe_int(post.li_impressions),
        clicks=_safe_int(post.li_clicks),
        shares=_safe_int(post.li_shares),
        score=_engagement_score(post),
    )


async def _load_samples(db: AsyncSession) -> list[EditorialPostSample]:
    result = await db.execute(
        select(ScheduledPost).where(
            ScheduledPost.status == "published",
            ScheduledPost.linkedin_text.isnot(None),
            ScheduledPost.linkedin_text != "",
        )
    )
    samples: list[EditorialPostSample] = []
    for post in result.scalars().all():
        sample = _to_sample(post)
        if sample:
            samples.append(sample)
    return samples


def _median_int(values: Sequence[int]) -> int:
    if not values:
        return 0
    return int(statistics.median(values))


def _paragraph_count(text: str) -> int:
    return len([chunk for chunk in re.split(r"\n\s*\n", text) if chunk.strip()])


def _hashtag_count(text: str) -> int:
    return len(re.findall(r"#[\wÁÉÍÓÚÜÑáéíóúüñ]+", text))


def _theme_counts(samples: Sequence[EditorialPostSample]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {name: 0 for name in THEME_KEYWORDS}
    for sample in samples:
        haystack = sample.text.lower()
        for theme, keywords in THEME_KEYWORDS.items():
            if any(keyword in haystack for keyword in keywords):
                counts[theme] += 1
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)


def _select_manual_reference_samples(
    samples: Sequence[EditorialPostSample],
) -> list[EditorialPostSample]:
    manual = [sample for sample in samples if sample.source == "manual"]
    if not manual:
        return []

    first_tool_date = min(
        (
            sample.published_at
            for sample in samples
            if sample.source in {"x_auto", "editorial", "radar"} and sample.published_at
        ),
        default=None,
    )
    pre_tool = [
        sample
        for sample in manual
        if first_tool_date and sample.published_at and sample.published_at < first_tool_date
    ]
    pre_tool.sort(key=lambda sample: sample.published_at or datetime.min)

    selected: list[EditorialPostSample] = pre_tool[:MANUAL_REFERENCE_LIMIT]
    selected_ids = {sample.post_id for sample in selected}

    for sample in sorted(manual, key=lambda item: item.score, reverse=True):
        if len(selected) >= MANUAL_REFERENCE_LIMIT:
            break
        if sample.post_id not in selected_ids:
            selected.append(sample)
            selected_ids.add(sample.post_id)
    return selected


def _format_sample(sample: EditorialPostSample, *, max_chars: int = 700) -> str:
    text = re.sub(r"\s+", " ", sample.text).strip()
    if len(text) > max_chars:
        text = f"{text[:max_chars].rstrip()}..."
    date = sample.published_at.date().isoformat() if sample.published_at else "sin fecha"
    return (
        f"Post #{sample.post_id} | {sample.source} | {date} | "
        f"score {sample.score:.1f} | {sample.likes} likes | "
        f"{sample.comments} comentarios | {sample.impressions} impresiones\n"
        f"{text}"
    )


def _build_deterministic_profile(
    *,
    top_samples: Sequence[EditorialPostSample],
    manual_samples: Sequence[EditorialPostSample],
    weak_samples: Sequence[EditorialPostSample],
    total_samples: int,
) -> str:
    if not top_samples:
        return (
            "Memoria editorial: todavia no hay suficientes publicaciones historicas "
            "con texto para aprender patrones. Usa criterio fresco, concreto y variado."
        )

    top_lengths = [len(sample.text) for sample in top_samples]
    top_paragraphs = [_paragraph_count(sample.text) for sample in top_samples]
    top_hashtags = [_hashtag_count(sample.text) for sample in top_samples]
    themes = [
        f"{theme} ({count})"
        for theme, count in _theme_counts(top_samples)
        if count > 0
    ][:5]
    top_openings = [sample.first_line for sample in top_samples[:7] if sample.first_line]
    weak_openings = [sample.first_line for sample in weak_samples[:4] if sample.first_line]

    lines = [
        "MEMORIA EDITORIAL APRENDIDA",
        f"Base historica: {total_samples} publicaciones publicadas con texto.",
        (
            "Longitud que mejor ha funcionado: "
            f"mediana { _median_int(top_lengths) } caracteres; "
            f"rango top {min(top_lengths)}-{max(top_lengths)}."
        ),
        (
            "Estructura top: "
            f"mediana { _median_int(top_paragraphs) } bloques; "
            f"mediana { _median_int(top_hashtags) } hashtags."
        ),
    ]
    if themes:
        lines.append(f"Temas que aparecen mas en posts fuertes: {', '.join(themes)}.")
    if manual_samples:
        lines.append(
            "Voz manual/pre-herramienta: usala como referencia de lenguaje y criterio, "
            "pero no copies frases ni plantillas."
        )
    lines.append(
        "Patron editorial: funcionan aperturas con protagonista concreto, cifra, herramienta, "
        "paper o caso claro desde la primera linea. Evita abrir en abstracto."
    )
    lines.append(
        "No fuerces moraleja ni pregunta final. Decide si conviene presentar, describir, "
        "invitar a usar, analizar, advertir o reflexionar segun la fuente."
    )
    lines.append("Aperturas top de referencia:")
    lines.extend(f"- {opening}" for opening in top_openings)
    if weak_openings:
        lines.append("Aperturas de bajo rendimiento a evitar como patron:")
        lines.extend(f"- {opening}" for opening in weak_openings)

    return "\n".join(lines)


async def _synthesize_profile_with_model(
    *,
    deterministic_profile: str,
    top_samples: Sequence[EditorialPostSample],
    manual_samples: Sequence[EditorialPostSample],
    weak_samples: Sequence[EditorialPostSample],
) -> str | None:
    if get_text_generation_config_error():
        return None

    top_text = "\n\n".join(_format_sample(sample) for sample in top_samples[:12])
    manual_text = "\n\n".join(_format_sample(sample, max_chars=520) for sample in manual_samples[:8])
    weak_text = "\n\n".join(_format_sample(sample, max_chars=360) for sample in weak_samples[:5])

    system_prompt = (
        "Eres director editorial y analista de desempeno para una cuenta de LinkedIn "
        "sobre inteligencia artificial e IA en educacion. Tu tarea no es escribir un post, "
        "sino aprender el patron editorial a partir de publicaciones historicas."
    )
    user_message = (
        "Sintetiza una memoria editorial accionable para que un radar diario elija fuentes "
        "y redacte mejor.\n\n"
        "Reglas:\n"
        "- No copies frases literales de posts antiguos.\n"
        "- Distingue voz, longitud, estructura, temas y tipos de fuentes que suelen funcionar.\n"
        "- Incluye como aprender de posts manuales/pre-herramienta.\n"
        "- Incluye tambien que patrones evitar por sonar artificiales o repetitivos.\n"
        "- Maximo 1300 caracteres.\n"
        "- Escribe en espanol claro, sin markdown pesado.\n\n"
        f"PERFIL ESTADISTICO:\n{deterministic_profile}\n\n"
        f"MEJORES POSTS HISTORICOS:\n{top_text}\n\n"
        f"REFERENCIAS MANUALES/PRE-HERRAMIENTA:\n{manual_text or 'No disponibles.'}\n\n"
        f"POSTS FLOJOS COMO CONTRASTE:\n{weak_text or 'No disponibles.'}"
    )
    try:
        synthesized = await _generate_text_with_provider(
            system_prompt=system_prompt,
            user_message=user_message,
            max_output_tokens=700,
        )
    except Exception as exc:
        logger.warning("Memoria editorial: sintesis con IA fallo: %s", exc)
        return None

    synthesized = synthesized.strip()
    if not synthesized:
        return None
    if len(synthesized) > 1600:
        synthesized = f"{synthesized[:1600].rstrip()}..."
    return (
        "MEMORIA EDITORIAL APRENDIDA\n"
        f"{synthesized}\n\n"
        "Resumen estadistico de respaldo:\n"
        f"{deterministic_profile[:900]}"
    )


async def get_editorial_learning_profile(
    db: AsyncSession,
    *,
    force: bool = False,
    use_model: bool = True,
) -> str:
    global _profile_cache, _profile_cache_at

    now = datetime.now(timezone.utc)
    if (
        not force
        and use_model
        and _profile_cache
        and _profile_cache_at
        and now - _profile_cache_at < PROFILE_CACHE_TTL
    ):
        return _profile_cache

    samples = await _load_samples(db)
    if not samples:
        profile = (
            "Memoria editorial: no hay publicaciones publicadas con texto para aprender. "
            "Usa criterio concreto, actual y variado."
        )
        _profile_cache = profile
        _profile_cache_at = now
        return profile

    ranked = sorted(samples, key=lambda sample: sample.score, reverse=True)
    top_samples = ranked[:TOP_POST_LIMIT]
    manual_samples = _select_manual_reference_samples(samples)
    weak_samples = [
        sample
        for sample in sorted(samples, key=lambda item: item.score)
        if sample.impressions or sample.likes or sample.comments
    ][:WEAK_POST_LIMIT]

    deterministic_profile = _build_deterministic_profile(
        top_samples=top_samples,
        manual_samples=manual_samples,
        weak_samples=weak_samples,
        total_samples=len(samples),
    )
    profile = deterministic_profile

    if use_model:
        synthesized = await _synthesize_profile_with_model(
            deterministic_profile=deterministic_profile,
            top_samples=top_samples,
            manual_samples=manual_samples,
            weak_samples=weak_samples,
        )
        if synthesized:
            profile = synthesized

    if len(profile) > PROFILE_MAX_CHARS:
        profile = f"{profile[:PROFILE_MAX_CHARS].rstrip()}..."

    if use_model:
        _profile_cache = profile
        _profile_cache_at = now
    return profile
