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

SYSTEM_PROMPT = """You are a professional CV editor. Your ONLY job is to REWRITE and REFRAME the candidate's existing CV content to better align with a specific job posting.

ABSOLUTE RULES — VIOLATIONS ARE NOT ACCEPTABLE:
1. NEVER add skills, tools, technologies, certifications, companies, roles, achievements, or ANY fact that does not explicitly appear in the original CV text.
2. The job posting is REFERENCE ONLY — use its vocabulary and tone to rephrase what already exists in the CV. Nothing from the job posting becomes a CV fact.
3. If the CV does not mention a skill or experience, it CANNOT appear in the output, even if the job requires it.
4. You may REPHRASE existing content using keywords from the job posting — only when the meaning remains accurate.
5. You may REORDER bullet points to put the most relevant ones first.
6. You may write a PROFESSIONAL SUMMARY based solely on what IS in the CV.

SELF-CHECK before returning JSON: For every bullet point, skill, and fact — ask "Is this explicitly in the original CV text?" If no → remove it.

Your output MUST be a valid JSON object with no text before or after it."""

CV_PROMPT = """TASK: Adapt the CV below to better match the job posting. Do NOT add anything that is not already in the CV.

=== ORIGINAL CV (the ONLY source of truth) ===
{cv_text}

=== JOB POSTING (vocabulary/tone reference only — do NOT copy facts from here) ===
{job_description}

Return ONLY a JSON object with this structure:
{{
  "name": "Full Name from CV",
  "email": "email from CV or empty string",
  "phone": "phone from CV or empty string",
  "location": "location from CV or empty string",
  "linkedin": "linkedin from CV or empty string",
  "portfolio": "portfolio/website from CV or empty string",
  "job_title_applied": "job title from the posting",
  "company_applied": "company name from the posting",
  "professional_summary": "2-3 sentences synthesizing only what IS in the CV, using the tone/keywords of the job posting where appropriate",
  "experience": [
    {{
      "title": "exact job title from CV",
      "company": "exact company from CV",
      "location": "location from CV or empty string",
      "start_date": "date from CV",
      "end_date": "date from CV",
      "bullets": [
        "Rewritten bullet using job posting keywords, but describing only what the CV actually says",
        "Most relevant bullets listed first"
      ]
    }}
  ],
  "education": [
    {{
      "degree": "degree from CV",
      "field": "field from CV or empty string",
      "institution": "institution from CV",
      "location": "location from CV or empty string",
      "graduation_year": "year from CV",
      "honors": "honors from CV or empty string"
    }}
  ],
  "skills": {{
    "all_items": ["skill1 from CV", "skill2 from CV", "skill3 from CV"]
  }},
  "languages": [
    {{"language": "language from CV", "level": "level from CV"}}
  ],
  "certifications": [
    {{"name": "cert from CV", "issuer": "issuer from CV or empty string", "year": "year from CV or empty string"}}
  ],
  "projects": [
    {{
      "name": "project name from CV",
      "description": "description from CV reworded for relevance",
      "technologies": ["tech from CV only"]
    }}
  ]
}}

Rules:
- Omit certifications if none in original CV
- Omit projects if none in original CV
- Omit languages if none in original CV
- skills.all_items: flat list of ALL skills from CV (combine all categories)
- Experience: most recent first, most relevant bullets first
- DO NOT invent or add ANYTHING not present in the original CV text"""


# ── GENERATE ───────────────────────────────────────────────────────────────────

async def generate_adapted_cv(cv_text: str, job_description: str, gen_id: int) -> dict:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
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

BLACK = colors.HexColor("#111111")
DARK_GRAY = colors.HexColor("#333333")
MID_GRAY = colors.HexColor("#555555")
LIGHT_GRAY = colors.HexColor("#888888")
LINE_COLOR = colors.HexColor("#222222")


def _styles():
    return {
        "name": ParagraphStyle(
            "name", fontName="Times-Bold", fontSize=22, leading=28,
            textColor=BLACK, alignment=TA_CENTER, spaceAfter=2,
        ),
        "contact": ParagraphStyle(
            "contact", fontName="Times-Roman", fontSize=9, leading=13,
            textColor=MID_GRAY, alignment=TA_CENTER, spaceAfter=0,
        ),
        "section": ParagraphStyle(
            "section", fontName="Times-Bold", fontSize=11, leading=14,
            textColor=BLACK, alignment=TA_CENTER, spaceAfter=0, spaceBefore=0,
        ),
        "summary": ParagraphStyle(
            "summary", fontName="Times-Roman", fontSize=9.5, leading=14,
            textColor=DARK_GRAY, spaceAfter=0,
        ),
        "exp_title": ParagraphStyle(
            "exp_title", fontName="Times-Bold", fontSize=10, leading=13, textColor=BLACK,
        ),
        "exp_company": ParagraphStyle(
            "exp_company", fontName="Times-Italic", fontSize=9.5, leading=13, textColor=DARK_GRAY,
        ),
        "exp_date": ParagraphStyle(
            "exp_date", fontName="Times-Roman", fontSize=9, leading=13,
            textColor=MID_GRAY, alignment=TA_RIGHT,
        ),
        "exp_location": ParagraphStyle(
            "exp_location", fontName="Times-Italic", fontSize=9, leading=13,
            textColor=MID_GRAY, alignment=TA_RIGHT,
        ),
        "bullet": ParagraphStyle(
            "bullet", fontName="Times-Roman", fontSize=9.5, leading=13,
            textColor=DARK_GRAY, leftIndent=12, spaceAfter=1,
        ),
        "skill_bullet": ParagraphStyle(
            "skill_bullet", fontName="Times-Roman", fontSize=9.5, leading=13,
            textColor=DARK_GRAY, leftIndent=8, spaceAfter=2,
        ),
        "edu_degree": ParagraphStyle(
            "edu_degree", fontName="Times-Italic", fontSize=9.5, leading=13, textColor=DARK_GRAY,
        ),
        "edu_institution": ParagraphStyle(
            "edu_institution", fontName="Times-Italic", fontSize=9.5, leading=13, textColor=DARK_GRAY,
        ),
        "lang": ParagraphStyle(
            "lang", fontName="Times-Roman", fontSize=9.5, leading=13, textColor=DARK_GRAY,
        ),
    }


def _section_header(story, title, W):
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width=W, thickness=0.75, color=LINE_COLOR, spaceAfter=3))
    story.append(Paragraph(title, _styles()["section"]))
    story.append(HRFlowable(width=W, thickness=0.75, color=LINE_COLOR, spaceAfter=6))


def _two_col_table(items, W, style):
    """Split a list of items into two balanced columns of bullets."""
    if not items:
        return []
    mid = (len(items) + 1) // 2
    col1 = items[:mid]
    col2 = items[mid:]
    # Pad to same length
    while len(col2) < len(col1):
        col2.append("")

    rows = []
    for a, b in zip(col1, col2):
        left = Paragraph(f"• {a}", style) if a else Paragraph("", style)
        right = Paragraph(f"• {b}", style) if b else Paragraph("", style)
        rows.append([left, right])

    t = Table(rows, colWidths=[W * 0.5, W * 0.5])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return [t]


def _side_by_side(left_para, right_para, W):
    t = Table([[left_para, right_para]], colWidths=[W * 0.68, W * 0.32])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _render_pdf(cv_data: dict, gen_id: int) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    filename = f"cv_{gen_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = os.path.join(OUTPUTS_DIR, filename)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    W = A4[0] - 40 * mm
    S = _styles()
    story = []

    # ── NAME ──
    story.append(Paragraph(cv_data.get("name", ""), S["name"]))
    story.append(HRFlowable(width=W, thickness=1, color=LINE_COLOR, spaceAfter=4))

    # ── CONTACTS ──
    contacts = []
    for f in ["location", "email", "phone", "linkedin", "portfolio"]:
        v = cv_data.get(f, "").strip()
        if v:
            contacts.append(v)
    if contacts:
        story.append(Paragraph("   ·   ".join(contacts), S["contact"]))
    story.append(Spacer(1, 2))

    # ── SUMMARY ──
    if cv_data.get("professional_summary"):
        _section_header(story, "Professional Summary", W)
        story.append(Paragraph(cv_data["professional_summary"], S["summary"]))

    # ── SKILLS ──
    skills = cv_data.get("skills", {})
    items = skills.get("all_items", []) if isinstance(skills, dict) else []
    if items:
        _section_header(story, "Skills", W)
        story.extend(_two_col_table(items, W, S["skill_bullet"]))

    # ── EXPERIENCE ──
    experience = cv_data.get("experience", [])
    if experience:
        _section_header(story, "Experience", W)
        for i, exp in enumerate(experience):
            company = exp.get("company", "")
            location = exp.get("location", "")
            title = exp.get("title", "")
            dates = f"{exp.get('start_date', '')} – {exp.get('end_date', '')}"

            # Company (left) + Location (right)
            story.append(_side_by_side(
                Paragraph(company, S["exp_company"]),
                Paragraph(location, S["exp_location"]),
                W,
            ))
            # Title (left) + Dates (right)
            story.append(_side_by_side(
                Paragraph(title, S["exp_title"]),
                Paragraph(dates, S["exp_date"]),
                W,
            ))
            for bullet in exp.get("bullets", []):
                story.append(Paragraph(f"• {bullet}", S["bullet"]))
            if i < len(experience) - 1:
                story.append(Spacer(1, 7))

    # ── EDUCATION ──
    education = cv_data.get("education", [])
    if education:
        _section_header(story, "Education", W)
        for edu in education:
            institution = edu.get("institution", "")
            location = edu.get("location", "")
            degree = edu.get("degree", "")
            if edu.get("field"):
                degree += f" in {edu['field']}"
            year = edu.get("graduation_year", "")
            honors = edu.get("honors", "")

            story.append(_side_by_side(
                Paragraph(institution, S["edu_institution"]),
                Paragraph(location, S["exp_location"]),
                W,
            ))
            story.append(_side_by_side(
                Paragraph(degree, S["edu_degree"]),
                Paragraph(year, S["exp_date"]),
                W,
            ))
            if honors:
                story.append(Paragraph(honors, S["bullet"]))
            story.append(Spacer(1, 5))

    # ── PROJECTS ──
    projects = cv_data.get("projects", [])
    if projects:
        _section_header(story, "Projects", W)
        for proj in projects:
            story.append(Paragraph(proj.get("name", ""), S["exp_title"]))
            if proj.get("description"):
                story.append(Paragraph(proj["description"], S["summary"]))
            techs = proj.get("technologies", [])
            if techs:
                story.append(Paragraph(", ".join(techs), S["contact"]))
            story.append(Spacer(1, 5))

    # ── LANGUAGES & CERTIFICATIONS ──
    langs = cv_data.get("languages", [])
    certs = cv_data.get("certifications", [])

    if langs or certs:
        _section_header(story, "Additional Information", W)
        rows = []
        if langs:
            for lang in langs:
                rows.append(Paragraph(
                    f"<b>{lang.get('language', '')}</b>: {lang.get('level', '')}",
                    S["lang"],
                ))
        if certs:
            for cert in certs:
                line = f"<b>{cert.get('name', '')}</b>"
                if cert.get("issuer"):
                    line += f", {cert['issuer']}"
                if cert.get("year"):
                    line += f" ({cert['year']})"
                rows.append(Paragraph(line, S["lang"]))
        for r in rows:
            story.append(r)

    doc.build(story)
    return output_path
