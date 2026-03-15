import anthropic
import json
import os
import re
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER


TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs")

SYSTEM_PROMPT = """You are an expert CV/resume writer and career coach with 20+ years of experience.
Your task is to adapt a candidate's CV to better match a specific job posting.

CRITICAL RULES:
- NEVER invent experience, skills, certifications, education, or any fact not present in the original CV
- You MAY reorder bullet points to highlight the most relevant achievements first
- You MAY rephrase descriptions using keywords from the job posting (while keeping the meaning accurate)
- You MAY write a tailored professional summary based on what's actually in the CV
- You MAY reorganize sections for better impact
- Keep everything truthful and verifiable

Your output MUST be a valid JSON object with no additional text before or after it."""

CV_PROMPT = """Adapt the following CV to match the job posting below.

=== ORIGINAL CV ===
{cv_text}

=== JOB POSTING ===
{job_description}

Return ONLY a JSON object with this exact structure:
{{
  "name": "Full Name",
  "email": "email@example.com",
  "phone": "+1 234 567 8900",
  "location": "City, Country",
  "linkedin": "linkedin.com/in/username or empty string",
  "portfolio": "portfolio URL or empty string",
  "job_title_applied": "Exact job title from the posting",
  "company_applied": "Company name from the posting",
  "professional_summary": "2-3 sentences tailored to this specific job, highlighting the most relevant experience and value proposition",
  "experience": [
    {{
      "title": "Job Title",
      "company": "Company Name",
      "location": "City, Country",
      "start_date": "Month Year",
      "end_date": "Month Year or Present",
      "bullets": [
        "Most relevant achievement or responsibility for this job (reworded with job keywords if accurate)",
        "Second most relevant achievement",
        "Third achievement"
      ]
    }}
  ],
  "education": [
    {{
      "degree": "Degree Name",
      "field": "Field of Study",
      "institution": "Institution Name",
      "location": "City, Country",
      "graduation_year": "Year",
      "honors": "Honors/GPA if notable, otherwise empty string"
    }}
  ],
  "skills": {{
    "categories": [
      {{
        "name": "Category name (e.g. Programming Languages, Frameworks, Tools)",
        "items": ["skill1", "skill2", "skill3"]
      }}
    ]
  }},
  "languages": [
    {{"language": "English", "level": "Native"}}
  ],
  "certifications": [
    {{"name": "Certification Name", "issuer": "Issuing Organization", "year": "Year"}}
  ],
  "projects": [
    {{
      "name": "Project Name",
      "description": "Brief description relevant to the job",
      "technologies": ["tech1", "tech2"]
    }}
  ]
}}

Notes:
- Include only sections that have actual data from the original CV
- Omit certifications array if none exist in the original
- Omit projects array if none exist in the original
- Order experience entries from most recent to oldest
- Order skill categories so the most relevant ones for this job appear first
- Keep bullet points concise and impact-focused (start with strong action verbs)"""


async def generate_adapted_cv(cv_text: str, job_description: str, gen_id: int) -> dict:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    prompt = CV_PROMPT.format(cv_text=cv_text, job_description=job_description)

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Extract JSON if wrapped in markdown code blocks
    json_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if json_match:
        raw = json_match.group(1)

    cv_data = json.loads(raw)

    pdf_path = _render_pdf(cv_data, gen_id)
    return {"cv_data": cv_data, "pdf_path": pdf_path}


BLUE = colors.HexColor("#2563EB")
DARK = colors.HexColor("#0F172A")
GRAY = colors.HexColor("#475569")
LIGHT_GRAY = colors.HexColor("#94A3B8")
BLUE_LIGHT = colors.HexColor("#EFF6FF")


def _render_pdf(cv_data: dict, gen_id: int) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    filename = f"cv_{gen_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = os.path.join(OUTPUTS_DIR, filename)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    story = []
    W = A4[0] - 36 * mm  # usable width

    # ── Styles ──
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, leading=14, textColor=DARK)
    name_style = ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=DARK)
    target_style = ParagraphStyle("target", fontName="Helvetica", fontSize=11, leading=14, textColor=BLUE)
    contact_style = ParagraphStyle("contact", fontName="Helvetica", fontSize=8.5, leading=12, textColor=GRAY)
    section_title = ParagraphStyle("sectiontitle", fontName="Helvetica-Bold", fontSize=8.5, leading=11,
                                   textColor=BLUE, spaceAfter=4, spaceBefore=10,
                                   letterSpacing=1.2, textTransform="uppercase")
    exp_title_style = ParagraphStyle("exptitle", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=DARK)
    exp_company_style = ParagraphStyle("expcompany", fontName="Helvetica", fontSize=9, leading=12, textColor=GRAY)
    exp_date_style = ParagraphStyle("expdate", fontName="Helvetica", fontSize=8.5, leading=12, textColor=LIGHT_GRAY, alignment=TA_RIGHT)
    bullet_style = ParagraphStyle("bullet", fontName="Helvetica", fontSize=9, leading=13, textColor=GRAY,
                                  leftIndent=10, spaceAfter=1)
    summary_style = ParagraphStyle("summary", fontName="Helvetica", fontSize=9.5, leading=15, textColor=GRAY)
    skill_cat_style = ParagraphStyle("skillcat", fontName="Helvetica-Bold", fontSize=8.5, leading=12,
                                     textColor=GRAY, textTransform="uppercase")
    skill_val_style = ParagraphStyle("skillval", fontName="Helvetica", fontSize=9, leading=12, textColor=DARK)
    lang_style = ParagraphStyle("lang", fontName="Helvetica", fontSize=9, leading=13, textColor=DARK)

    from reportlab.platypus import Table, TableStyle

    def section_header(title):
        story.append(Spacer(1, 6))
        story.append(Paragraph(title.upper(), section_title))
        story.append(HRFlowable(width=W, thickness=0.75, color=BLUE_LIGHT, spaceAfter=6))

    # ── Header ──
    story.append(Paragraph(cv_data.get("name", ""), name_style))
    if cv_data.get("job_title_applied"):
        label = cv_data["job_title_applied"]
        if cv_data.get("company_applied"):
            label += f" · {cv_data['company_applied']}"
        story.append(Paragraph(label, target_style))
    story.append(Spacer(1, 4))

    contacts = []
    for field in ["email", "phone", "location", "linkedin", "portfolio"]:
        val = cv_data.get(field, "").strip()
        if val:
            contacts.append(val)
    story.append(Paragraph("   ·   ".join(contacts), contact_style))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width=W, thickness=2, color=BLUE, spaceAfter=10))

    # ── Summary ──
    if cv_data.get("professional_summary"):
        section_header("Professional Summary")
        story.append(Paragraph(cv_data["professional_summary"], summary_style))

    # ── Experience ──
    if cv_data.get("experience"):
        section_header("Professional Experience")
        for exp in cv_data["experience"]:
            date_str = f"{exp.get('start_date', '')} – {exp.get('end_date', '')}"
            row = [[Paragraph(exp.get("title", ""), exp_title_style),
                    Paragraph(date_str, exp_date_style)]]
            t = Table(row, colWidths=[W * 0.72, W * 0.28])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 0),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            story.append(t)
            company = exp.get("company", "")
            if exp.get("location"):
                company += f" · {exp['location']}"
            story.append(Paragraph(company, exp_company_style))
            for bullet in exp.get("bullets", []):
                story.append(Paragraph(f"• {bullet}", bullet_style))
            story.append(Spacer(1, 6))

    # ── Education ──
    if cv_data.get("education"):
        section_header("Education")
        for edu in cv_data["education"]:
            degree = edu.get("degree", "")
            if edu.get("field"):
                degree += f" in {edu['field']}"
            institution = edu.get("institution", "")
            if edu.get("location"):
                institution += f" · {edu['location']}"
            year = edu.get("graduation_year", "")
            row = [[Paragraph(degree, exp_title_style), Paragraph(year, exp_date_style)]]
            t = Table(row, colWidths=[W * 0.72, W * 0.28])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 0),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            story.append(t)
            story.append(Paragraph(institution, exp_company_style))
            if edu.get("honors"):
                story.append(Paragraph(edu["honors"], exp_company_style))
            story.append(Spacer(1, 5))

    # ── Skills ──
    skills = cv_data.get("skills", {})
    categories = skills.get("categories", []) if isinstance(skills, dict) else []
    if categories:
        section_header("Skills")
        for cat in categories:
            row = [[Paragraph(cat.get("name", ""), skill_cat_style),
                    Paragraph(" · ".join(cat.get("items", [])), skill_val_style)]]
            t = Table(row, colWidths=[W * 0.22, W * 0.78])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 1),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            story.append(t)

    # ── Projects ──
    if cv_data.get("projects"):
        section_header("Projects")
        for proj in cv_data["projects"]:
            story.append(Paragraph(proj.get("name", ""), exp_title_style))
            if proj.get("description"):
                story.append(Paragraph(proj["description"], exp_company_style))
            techs = proj.get("technologies", [])
            if techs:
                story.append(Paragraph(" · ".join(techs), contact_style))
            story.append(Spacer(1, 5))

    # ── Languages & Certifications (two-col) ──
    langs = cv_data.get("languages", [])
    certs = cv_data.get("certifications", [])
    if langs or certs:
        story.append(Spacer(1, 4))
        left_parts = []
        right_parts = []

        if langs:
            left_parts.append(Paragraph("LANGUAGES", section_title))
            left_parts.append(HRFlowable(width=(W / 2) - 5 * mm, thickness=0.75, color=BLUE_LIGHT, spaceAfter=4))
            for lang in langs:
                left_parts.append(Paragraph(
                    f"<b>{lang.get('language', '')}</b>  <font color='#94A3B8'>{lang.get('level', '')}</font>",
                    lang_style))

        if certs:
            right_parts.append(Paragraph("CERTIFICATIONS", section_title))
            right_parts.append(HRFlowable(width=(W / 2) - 5 * mm, thickness=0.75, color=BLUE_LIGHT, spaceAfter=4))
            for cert in certs:
                line = f"<b>{cert.get('name', '')}</b>"
                if cert.get("issuer"):
                    line += f" · {cert['issuer']}"
                if cert.get("year"):
                    line += f" ({cert['year']})"
                right_parts.append(Paragraph(line, lang_style))

        from reportlab.platypus import KeepTogether
        col_data = [[left_parts or [""], right_parts or [""]]]
        t = Table(col_data, colWidths=[W / 2, W / 2])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        story.append(t)

    doc.build(story)
    return output_path
