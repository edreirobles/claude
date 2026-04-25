import anthropic
import json
import os
import re
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs")

# ── PROMPT ─────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior professional CV editor and career strategist with 20+ years of experience helping candidates land interviews at top companies.

Your task is to take a candidate's existing CV and adapt it to a specific job posting — ruthlessly optimizing for relevance, impact, and ATS compatibility.

═══════════════════════════════════════
ANTI-HALLUCINATION RULES (NON-NEGOTIABLE)
═══════════════════════════════════════
1. EVERY fact, skill, tool, company, role, achievement, certification, and date in your output MUST exist verbatim or be directly inferable from the ORIGINAL CV text.
2. The job posting is VOCABULARY/TONE reference only. NOTHING from the job posting becomes a CV fact.
3. If a skill or experience is NOT in the original CV, it CANNOT appear in the output — even if the job requires it.
4. You MAY rephrase existing content using job posting keywords ONLY when the meaning stays 100% accurate.
5. SELF-CHECK: Before finalizing, review every single item and ask "Does this appear in the original CV?" If no → delete it immediately.

═══════════════════════════════════════
CONTENT CURATION RULES (CV BEST PRACTICES 2025)
═══════════════════════════════════════
REMOVE the following if present in the original CV:
- "References available upon request" — assumed, wastes space
- Objective statements — replace with a tailored professional summary
- Generic soft-skill bullets with no evidence ("team player", "hard worker", "good communicator" as standalone claims)
- Basic computer skills that everyone has: MS Word, Excel (basic), email, internet browsing — UNLESS the job explicitly requires them
- Personal data that doesn't belong on a CV: age, date of birth, marital status, nationality, photo references
- GPA/grades UNLESS the candidate graduated recently (<3 years) or the GPA is exceptional
- Very old jobs (>12 years ago) that are entry-level AND irrelevant to this specific role — either omit or consolidate to 1 line
- Hobbies and personal interests UNLESS directly relevant to the job
- Redundant bullets that say the same thing in two different ways
- Certifications >10 years old that are no longer industry-relevant

TRIM the following:
- Reduce each role to 3–5 bullets (max 6 for the most recent/relevant role)
- For roles >8 years ago: max 2–3 bullets, only the most relevant ones
- Skills list: curate to the 8–12 most relevant skills for THIS specific job — remove the rest
- Professional summary: 2–3 sentences maximum, NO generic filler phrases

PRIORITIZE:
- Bullets that show quantified impact (numbers, percentages, scale) — keep all of these
- Skills explicitly mentioned in the job posting (if they exist in the CV) — list these first
- Most recent experience gets the most bullets
- Most relevant experience to THIS job gets more detail, regardless of recency

═══════════════════════════════════════
WRITING QUALITY STANDARDS
═══════════════════════════════════════
PROFESSIONAL REGISTER — apply to every bullet and every sentence:
- Eliminate weak openers: "responsible for", "helped with", "assisted in", "worked on", "participated in" → replace with strong ownership verbs: "led", "built", "reduced", "generated", "negotiated", "architected", "delivered", "launched", "drove", "managed", "secured", "optimized"
- Every bullet must follow: [Strong action verb] + [what specifically] + [measurable result or scope]
- If the original bullet lacks metrics, use contextual scale where directly inferable (team size, company size, time saved) — never invent numbers
- Professional summary must immediately answer "why is THIS person the right fit for THIS role" — not a generic career description
- Elevate the register to match the seniority level of the target role: if the original sounds junior or casual, raise the language accordingly
- Use consistent verb tense: past for past roles, present for current role
- Avoid redundant qualifiers: "very", "highly", "extremely", "truly" — let facts speak

═══════════════════════════════════════
OUTPUT LANGUAGE
═══════════════════════════════════════
Write the ENTIRE CV output in: {output_language}
This includes section titles, bullet points, professional summary, skill names, section_labels — everything without exception.
If output_language is "auto", detect the dominant language of the job posting and use that language throughout."""

CV_PROMPT = """Adapt this CV to the job posting below. Apply strict content curation — remove what's irrelevant, trim what's excessive, reframe what's valuable.

=== ORIGINAL CV (the ONLY source of truth for facts) ===
{cv_text}

=== JOB POSTING (vocabulary/tone reference only — facts come from CV above) ===
{job_description}

Return ONLY a valid JSON object, no other text:
{{
  "name": "Full Name from CV",
  "email": "email from CV or empty string",
  "phone": "phone from CV or empty string",
  "location": "city/country from CV (NOT full address) or empty string",
  "linkedin": "linkedin URL/handle from CV or empty string",
  "portfolio": "portfolio or website from CV or empty string",
  "job_title_applied": "job title from the posting",
  "company_applied": "company name from the posting",
  "detected_language": "ISO 639-1 code of the language used for the entire CV output (e.g. 'en', 'es', 'fr', 'pt', 'de', 'it')",
  "section_labels": {{
    "summary": "section header translated to the output language (e.g. 'Perfil Profesional' for Spanish)",
    "skills": "section header translated to the output language (e.g. 'Habilidades' for Spanish)",
    "experience": "section header translated to the output language (e.g. 'Experiencia' for Spanish)",
    "education": "section header translated to the output language (e.g. 'Educación' for Spanish)",
    "projects": "section header translated to the output language (e.g. 'Proyectos' for Spanish)",
    "additional": "section header translated to the output language (e.g. 'Información Adicional' for Spanish)",
    "degree_connector": "word connecting degree and field in the output language (e.g. 'en' for Spanish, 'in' for English, 'em' for Portuguese)"
  }},
  "professional_summary": "2-3 sentences maximum. Synthesize the candidate's most relevant value for THIS role using their actual background. No generic phrases like 'results-driven professional' or 'passionate about'. Be specific.",
  "experience": [
    {{
      "title": "exact job title from CV",
      "company": "exact company from CV",
      "location": "city/country from CV or empty string",
      "start_date": "date from CV",
      "end_date": "date from CV",
      "bullets": [
        "Strong action verb + what you did + impact/result, using job posting keywords where accurate. Max 5 bullets, most relevant first."
      ]
    }}
  ],
  "education": [
    {{
      "degree": "degree from CV",
      "field": "field of study from CV or empty string",
      "institution": "institution from CV",
      "location": "city/country from CV or empty string",
      "graduation_year": "year from CV",
      "honors": "only if exceptional or recent grad — otherwise empty string"
    }}
  ],
  "skills": {{
    "all_items": ["curated list of 8-12 most relevant skills from CV for this specific job, most relevant first"]
  }},
  "languages": [
    {{"language": "language name", "level": "proficiency level from CV"}}
  ],
  "certifications": [
    {{"name": "certification name from CV", "issuer": "issuing body from CV or empty string", "year": "year from CV or empty string"}}
  ],
  "projects": [
    {{
      "name": "project name from CV",
      "description": "1-2 sentence description from CV, reworded for relevance",
      "technologies": ["only technologies explicitly mentioned in CV for this project"]
    }}
  ]
}}

Omit certifications array entirely if none in original CV.
Omit projects array entirely if none in original CV.
Omit languages array entirely if none in original CV.
Experience: chronological (most recent first).
Do NOT include any information not present in the original CV."""


# ── GENERATE ───────────────────────────────────────────────────────────────────

async def generate_interview_tips(cv_data: dict, job_text: str) -> dict:
    """Generate interview prep tips from an already-adapted CV. Uses Haiku for speed."""
    lang = cv_data.get("detected_language", "en")
    lang_names = {
        "en": "English", "es": "Spanish", "fr": "French",
        "pt": "Portuguese", "de": "German", "it": "Italian",
    }
    lang_name = lang_names.get(lang, "the same language used in the CV")

    job_title = cv_data.get("job_title_applied", "this role")
    company = cv_data.get("company_applied", "this company")

    cv_summary = json.dumps({
        "name": cv_data.get("name"),
        "professional_summary": cv_data.get("professional_summary"),
        "skills": (cv_data.get("skills") or {}).get("all_items", []),
        "experience": [
            {
                "title": e.get("title"),
                "company": e.get("company"),
                "dates": f"{e.get('start_date','')} – {e.get('end_date','')}",
                "bullets": e.get("bullets", []),
            }
            for e in (cv_data.get("experience") or [])
        ],
    }, ensure_ascii=False, indent=2)

    prompt = f"""You are a career coach preparing a candidate for an interview at {company} for {job_title}.

Based on the candidate's adapted CV and the job posting, generate practical interview preparation guidance entirely in {lang_name}.

CANDIDATE'S ADAPTED CV:
{cv_summary}

JOB POSTING (first 1500 chars):
{job_text[:1500]}

Return ONLY a valid JSON object:
{{
  "talking_points": [
    "3-5 specific, compelling points the candidate should proactively mention — tied to real achievements in the CV, NOT generic"
  ],
  "skill_demonstrations": [
    {{
      "skill": "skill name",
      "example": "How to present a specific story from this CV that proves this skill in an interview (1-2 sentences)"
    }}
  ],
  "likely_questions": [
    {{
      "question": "A specific interview question for this exact role",
      "tip": "1-2 sentence answer framework using the candidate's actual background"
    }}
  ]
}}

Rules:
- 3-5 talking_points, 3-4 skill_demonstrations, 5-6 likely_questions
- Role-specific questions only — no generic ones like "tell me about yourself"
- Never invent experience or facts not in the CV
- Write entirely in {lang_name}"""

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    json_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if json_match:
        raw = json_match.group(1)

    return json.loads(raw)


async def generate_adapted_cv(cv_text: str, job_description: str, gen_id: int, output_language: str = "auto") -> dict:
    lang_instruction = {
        "auto": "auto — detect from the job posting language and use that language for the entire CV",
        "en": "English — write the entire CV in English",
        "es": "Spanish (Español) — write the entire CV in Spanish",
        "fr": "French (Français) — write the entire CV in French",
        "pt": "Portuguese (Português) — write the entire CV in Portuguese",
        "de": "German (Deutsch) — write the entire CV in German",
        "it": "Italian (Italiano) — write the entire CV in Italian",
    }.get(output_language, f"{output_language} — write the entire CV in this language")

    system = SYSTEM_PROMPT.format(output_language=lang_instruction)

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": CV_PROMPT.format(
            cv_text=cv_text,
            job_description=job_description,
        )}],
    )

    raw = message.content[0].text.strip()
    json_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if json_match:
        raw = json_match.group(1)

    cv_data = json.loads(raw)
    pdf_path = _render_pdf(cv_data, gen_id)
    return {"cv_data": cv_data, "pdf_path": pdf_path}


# ── PDF ────────────────────────────────────────────────────────────────────────

BLACK     = colors.HexColor("#111111")
DARK_GRAY = colors.HexColor("#333333")
MID_GRAY  = colors.HexColor("#555555")
LIGHT_GRAY= colors.HexColor("#888888")
LINE_COLOR= colors.HexColor("#222222")


def _s():
    return {
        "name": ParagraphStyle("name", fontName="Times-Bold", fontSize=22, leading=28,
                               textColor=BLACK, alignment=TA_CENTER, spaceAfter=2),
        "contact": ParagraphStyle("contact", fontName="Times-Roman", fontSize=9, leading=13,
                                  textColor=MID_GRAY, alignment=TA_CENTER),
        "section": ParagraphStyle("section", fontName="Times-Bold", fontSize=11, leading=14,
                                  textColor=BLACK, alignment=TA_CENTER),
        "summary": ParagraphStyle("summary", fontName="Times-Roman", fontSize=9.5, leading=14.5,
                                  textColor=DARK_GRAY),
        "exp_title": ParagraphStyle("exp_title", fontName="Times-Bold", fontSize=10, leading=13,
                                    textColor=BLACK),
        "exp_company": ParagraphStyle("exp_company", fontName="Times-Italic", fontSize=9.5, leading=13,
                                      textColor=DARK_GRAY),
        "exp_date": ParagraphStyle("exp_date", fontName="Times-Roman", fontSize=9, leading=13,
                                   textColor=MID_GRAY, alignment=TA_RIGHT),
        "exp_loc": ParagraphStyle("exp_loc", fontName="Times-Italic", fontSize=9, leading=13,
                                  textColor=LIGHT_GRAY, alignment=TA_RIGHT),
        "bullet": ParagraphStyle("bullet", fontName="Times-Roman", fontSize=9.5, leading=13.5,
                                 textColor=DARK_GRAY, leftIndent=12, spaceAfter=1),
        "skill_bullet": ParagraphStyle("skill_bullet", fontName="Times-Roman", fontSize=9.5, leading=13,
                                       textColor=DARK_GRAY, leftIndent=8, spaceAfter=2),
        "edu_main": ParagraphStyle("edu_main", fontName="Times-Italic", fontSize=9.5, leading=13,
                                   textColor=DARK_GRAY),
        "lang": ParagraphStyle("lang", fontName="Times-Roman", fontSize=9.5, leading=13,
                               textColor=DARK_GRAY),
    }


def _section_header(story, title, W):
    story.append(Spacer(1, 7))
    story.append(HRFlowable(width=W, thickness=0.75, color=LINE_COLOR, spaceAfter=3))
    story.append(Paragraph(title, _s()["section"]))
    story.append(HRFlowable(width=W, thickness=0.75, color=LINE_COLOR, spaceAfter=6))


def _row(left, right, W, split=0.68):
    t = Table([[left, right]], colWidths=[W * split, W * (1 - split)])
    t.setStyle(TableStyle([
        ("VALIGN",  (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING",   (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 0),
    ]))
    return t


def _two_col_bullets(items, W, style):
    if not items:
        return []
    mid = (len(items) + 1) // 2
    col1, col2 = items[:mid], items[mid:]
    while len(col2) < len(col1):
        col2.append("")
    rows = []
    for a, b in zip(col1, col2):
        left  = Paragraph(f"• {a}", style) if a else Paragraph("", style)
        right = Paragraph(f"• {b}", style) if b else Paragraph("", style)
        rows.append([left, right])
    t = Table(rows, colWidths=[W * 0.5, W * 0.5])
    t.setStyle(TableStyle([
        ("VALIGN",  (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING",   (0,0), (-1,-1), 1),
        ("BOTTOMPADDING",(0,0), (-1,-1), 1),
    ]))
    return [t]


def _render_pdf(cv_data: dict, gen_id: int) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    filename = f"cv_{gen_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = os.path.join(OUTPUTS_DIR, filename)

    # Section labels come from the model (already in the output language)
    lbl = cv_data.get("section_labels") or {}
    L = {
        "summary":    lbl.get("summary")    or "Professional Summary",
        "skills":     lbl.get("skills")     or "Skills",
        "experience": lbl.get("experience") or "Experience",
        "education":  lbl.get("education")  or "Education",
        "projects":   lbl.get("projects")   or "Projects",
        "additional": lbl.get("additional") or "Additional Information",
        "degree_in":  lbl.get("degree_connector") or "in",
    }

    doc = SimpleDocTemplate(output_path, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=18*mm, bottomMargin=18*mm)
    W = A4[0] - 40 * mm
    S = _s()
    story = []

    # ── Name ──
    story.append(Paragraph(cv_data.get("name", ""), S["name"]))
    story.append(HRFlowable(width=W, thickness=1, color=LINE_COLOR, spaceAfter=4))

    # ── Contacts ──
    contacts = [v.strip() for f in ["location","email","phone","linkedin","portfolio"]
                if (v := cv_data.get(f,"")).strip()]
    if contacts:
        story.append(Paragraph("   ·   ".join(contacts), S["contact"]))
    story.append(Spacer(1, 2))

    # ── Summary ──
    if cv_data.get("professional_summary"):
        _section_header(story, L["summary"], W)
        story.append(Paragraph(cv_data["professional_summary"], S["summary"]))

    # ── Skills ──
    skills = cv_data.get("skills", {})
    items = skills.get("all_items", []) if isinstance(skills, dict) else []
    if items:
        _section_header(story, L["skills"], W)
        story.extend(_two_col_bullets(items, W, S["skill_bullet"]))

    # ── Experience ──
    experience = cv_data.get("experience", [])
    if experience:
        _section_header(story, L["experience"], W)
        for i, exp in enumerate(experience):
            story.append(_row(
                Paragraph(exp.get("company", ""), S["exp_company"]),
                Paragraph(exp.get("location", ""), S["exp_loc"]),
                W,
            ))
            story.append(_row(
                Paragraph(exp.get("title", ""), S["exp_title"]),
                Paragraph(f"{exp.get('start_date','')} – {exp.get('end_date','')}", S["exp_date"]),
                W,
            ))
            for bullet in exp.get("bullets", []):
                story.append(Paragraph(f"• {bullet}", S["bullet"]))
            if i < len(experience) - 1:
                story.append(Spacer(1, 7))

    # ── Education ──
    education = cv_data.get("education", [])
    if education:
        _section_header(story, L["education"], W)
        for edu in education:
            degree = edu.get("degree", "")
            if edu.get("field"):
                degree += f" {L['degree_in']} {edu['field']}"
            story.append(_row(
                Paragraph(edu.get("institution", ""), S["edu_main"]),
                Paragraph(edu.get("location", ""), S["exp_loc"]),
                W,
            ))
            story.append(_row(
                Paragraph(degree, S["edu_main"]),
                Paragraph(edu.get("graduation_year", ""), S["exp_date"]),
                W,
            ))
            if edu.get("honors"):
                story.append(Paragraph(edu["honors"], S["bullet"]))
            story.append(Spacer(1, 5))

    # ── Projects ──
    projects = cv_data.get("projects", [])
    if projects:
        _section_header(story, L["projects"], W)
        for proj in projects:
            story.append(Paragraph(proj.get("name", ""), S["exp_title"]))
            if proj.get("description"):
                story.append(Paragraph(proj["description"], S["summary"]))
            if proj.get("technologies"):
                story.append(Paragraph(", ".join(proj["technologies"]), S["contact"]))
            story.append(Spacer(1, 5))

    # ── Languages & Certifications ──
    langs = cv_data.get("languages", [])
    certs = cv_data.get("certifications", [])
    if langs or certs:
        _section_header(story, L["additional"], W)
        for lang in langs:
            story.append(Paragraph(
                f"<b>{lang.get('language','')}</b>: {lang.get('level','')}",
                S["lang"],
            ))
        for cert in certs:
            line = f"<b>{cert.get('name','')}</b>"
            if cert.get("issuer"):
                line += f", {cert['issuer']}"
            if cert.get("year"):
                line += f" ({cert['year']})"
            story.append(Paragraph(line, S["lang"]))

    doc.build(story)
    return output_path
