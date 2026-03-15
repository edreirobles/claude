import anthropic
import json
import os
import re
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from datetime import datetime


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


def _render_pdf(cv_data: dict, gen_id: int) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template("cv_template.html")
    html_content = template.render(cv=cv_data, generated_at=datetime.now().strftime("%B %d, %Y"))

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    filename = f"cv_{gen_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = os.path.join(OUTPUTS_DIR, filename)

    HTML(string=html_content).write_pdf(output_path)
    return output_path
