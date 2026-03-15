import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

load_dotenv()

from app.database import (
    create_generation,
    get_all_generations,
    get_generation,
    init_db,
    update_generation,
)
from app.cv_generator import generate_adapted_cv
from app.cv_parser import parse_cv
from app.job_scraper import scrape_job_url

BASE_DIR = Path(__file__).parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="CV Matcher")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    generations = get_all_generations()
    return templates.TemplateResponse(
        "history.html", {"request": request, "generations": generations}
    )


@app.post("/api/scrape-url")
async def scrape_url(url: str = Form(...)):
    result = await scrape_job_url(url)
    return result


@app.post("/api/generate")
async def generate(
    cv_file: UploadFile = File(...),
    job_text: str = Form(""),
    job_url: str = Form(""),
    output_language: str = Form("auto"),
):
    if not job_text and not job_url:
        raise HTTPException(status_code=400, detail="Provide a job URL or paste the job description")

    allowed_extensions = {".pdf", ".docx", ".doc"}
    ext = Path(cv_file.filename).suffix.lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Use PDF or DOCX.")

    # Save uploaded CV
    unique_name = f"{uuid.uuid4().hex}{ext}"
    cv_path = UPLOADS_DIR / unique_name
    with open(cv_path, "wb") as f:
        shutil.copyfileobj(cv_file.file, f)

    # Resolve job description
    final_job_text = job_text
    scraped_url = job_url.strip() if job_url.strip() else None

    if not final_job_text and scraped_url:
        result = await scrape_job_url(scraped_url)
        if not result.get("success"):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Could not load the URL automatically: {result.get('error')}. "
                    "Please paste the job description text instead."
                ),
            )
        final_job_text = result["text"]

    # Parse CV
    try:
        cv_text = parse_cv(str(cv_path))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not read your CV: {e}")

    if len(cv_text.strip()) < 50:
        raise HTTPException(status_code=422, detail="Your CV appears to be empty or unreadable.")

    # Create DB record
    gen_id = create_generation(
        job_title="Processing...",
        company="Processing...",
        job_url=scraped_url or "",
        job_text=final_job_text[:2000],
        original_cv_filename=cv_file.filename,
    )

    # Generate adapted CV
    try:
        result = await generate_adapted_cv(cv_text, final_job_text, gen_id, output_language)
        cv_data = result["cv_data"]
        pdf_path = result["pdf_path"]

        update_generation(
            gen_id,
            output_pdf_path=pdf_path,
            status="completed",
        )

        # Update job title/company from parsed data
        from app.database import get_db
        conn = get_db()
        conn.execute(
            "UPDATE generations SET job_title=?, company=? WHERE id=?",
            (
                cv_data.get("job_title_applied", "Unknown Role"),
                cv_data.get("company_applied", "Unknown Company"),
                gen_id,
            ),
        )
        conn.commit()
        conn.close()

    except Exception as e:
        update_generation(gen_id, output_pdf_path="", status="failed")
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    return {
        "id": gen_id,
        "job_title": cv_data.get("job_title_applied", ""),
        "company": cv_data.get("company_applied", ""),
        "download_url": f"/api/download/{gen_id}",
    }


@app.get("/api/download/{gen_id}")
async def download(gen_id: int):
    gen = get_generation(gen_id)
    if not gen:
        raise HTTPException(status_code=404, detail="Generation not found")
    if gen["status"] != "completed" or not gen["output_pdf_path"]:
        raise HTTPException(status_code=404, detail="PDF not available")

    pdf_path = gen["output_pdf_path"]
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    company = gen.get("company") or "company"
    job_title = gen.get("job_title") or "cv"
    safe_name = f"CV_{company}_{job_title}".replace(" ", "_").replace("/", "-")[:60]

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"{safe_name}.pdf",
    )


@app.get("/api/history")
async def api_history():
    return get_all_generations()
