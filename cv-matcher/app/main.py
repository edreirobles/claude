import os
import shutil
import uuid
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request, Depends
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

from app.auth import get_current_user, get_current_user_optional, AUTH_ENABLED
from app.cv_generator import generate_adapted_cv
from app.cv_parser import parse_cv
from app.job_scraper import scrape_job_url

# ── Feature flags ──────────────────────────────────────────
PAYMENTS_ENABLED = bool(os.environ.get("STRIPE_SECRET_KEY"))
FREE_LIMIT = int(os.environ.get("FREE_GENERATIONS_LIMIT", "3"))

BASE_DIR = Path(__file__).parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="CV Matcher")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def ctx(request: Request, **extra):
    """Base template context with config vars injected."""
    return {
        "request": request,
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", ""),
        "auth_enabled": AUTH_ENABLED,
        "payments_enabled": PAYMENTS_ENABLED,
        "free_limit": FREE_LIMIT,
        "price_single_display": os.environ.get("PRICE_SINGLE_DISPLAY", "$1.99"),
        "price_monthly_display": os.environ.get("PRICE_MONTHLY_DISPLAY", "$9.99/mo"),
        "price_extra_display": os.environ.get("PRICE_EXTRA_DISPLAY", "$0.99"),
        **extra,
    }


# ── Local SQLite fallback (dev mode) ──────────────────────
if not AUTH_ENABLED:
    from app.database import init_db, create_generation as _local_create, \
        update_generation as _local_update, get_all_generations, get_generation
    init_db()


@app.on_event("startup")
async def startup():
    if not AUTH_ENABLED:
        from app.database import init_db
        init_db()
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        import asyncio
        from app.telegram_bot import run_bot
        asyncio.create_task(run_bot())


# ── Pages ──────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", ctx(request))


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not AUTH_ENABLED:
        return RedirectResponse(url="/")
    return templates.TemplateResponse("login.html", ctx(request))


@app.get("/auth/callback", response_class=HTMLResponse)
async def auth_callback(request: Request):
    return templates.TemplateResponse("auth_callback.html", ctx(request))


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    if not AUTH_ENABLED:
        from app.database import get_all_generations
        generations = get_all_generations()
        return templates.TemplateResponse("history.html", ctx(request, generations=generations))
    return templates.TemplateResponse("history.html", ctx(request, generations=None))


@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success(request: Request):
    return templates.TemplateResponse("payment_success.html", ctx(request))


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse("privacy.html", ctx(request))


@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse("terms.html", ctx(request))


# ── API ────────────────────────────────────────────────────

@app.get("/api/user")
async def api_user(user=Depends(get_current_user)):
    if not AUTH_ENABLED:
        return {"plan": "dev", "credits": 999, "free_used": 0, "free_limit": FREE_LIMIT, "email": "dev@local"}
    from app.supabase_db import get_or_create_profile, can_generate
    profile = get_or_create_profile(user.id, user.email)
    allowed, reason = can_generate(profile)
    free_remaining = max(0, FREE_LIMIT - profile.get("free_generations_used", 0))
    return {
        "email": user.email,
        "plan": profile.get("plan", "free"),
        "credits": profile.get("credits", 0),
        "free_used": profile.get("free_generations_used", 0),
        "free_limit": FREE_LIMIT,
        "free_remaining": free_remaining,
        "can_generate": allowed,
        "subscription_end": profile.get("subscription_end"),
    }


@app.post("/api/scrape-url")
async def scrape_url(url: str = Form(...)):
    return await scrape_job_url(url)


@app.post("/api/generate")
async def generate(
    cv_file: UploadFile = File(...),
    job_text: str = Form(""),
    job_url: str = Form(""),
    output_language: str = Form("auto"),
    user=Depends(get_current_user_optional),
):
    if not job_text and not job_url:
        raise HTTPException(400, "Provide a job URL or paste the job description")

    ext = Path(cv_file.filename).suffix.lower()
    if ext not in {".pdf", ".docx", ".doc"}:
        raise HTTPException(400, f"Unsupported file type: {ext}. Use PDF or DOCX.")

    anonymous = AUTH_ENABLED and user is None

    # ── Check usage limits (only for authenticated users) ──
    if AUTH_ENABLED and not anonymous:
        from app.supabase_db import get_or_create_profile, can_generate
        profile = get_or_create_profile(user.id, user.email)
        allowed, reason = can_generate(profile)
        if not allowed:
            raise HTTPException(402, detail=reason)

    # ── Save uploaded CV ──
    cv_path = UPLOADS_DIR / f"{uuid.uuid4().hex}{ext}"
    with open(cv_path, "wb") as f:
        shutil.copyfileobj(cv_file.file, f)

    # ── Resolve job description ──
    final_job_text = job_text
    scraped_url = job_url.strip() or None
    if not final_job_text and scraped_url:
        result = await scrape_job_url(scraped_url)
        if not result.get("success"):
            raise HTTPException(422, f"Could not load that URL: {result.get('error')}. Please paste the job text instead.")
        final_job_text = result["text"]

    # ── Parse CV ──
    try:
        cv_text = parse_cv(str(cv_path))
    except Exception as e:
        raise HTTPException(422, f"Could not read your CV: {e}")
    if len(cv_text.strip()) < 50:
        raise HTTPException(422, "Your CV appears to be empty or unreadable.")

    # ── Create DB record ──
    claim_token = None
    if anonymous:
        from app.supabase_db import create_anonymous_generation as _create, update_generation as _update
        claim_token = uuid.uuid4().hex
        gen_id = _create("Processing...", "Processing...", scraped_url or "", final_job_text, claim_token)
    elif AUTH_ENABLED:
        from app.supabase_db import create_generation as _create, update_generation as _update
        gen_id = _create(user.id, "Processing...", "Processing...", scraped_url or "", final_job_text, cv_file.filename)
    else:
        from app.database import create_generation as _create, update_generation as _update
        gen_id = _create("Processing...", "Processing...", scraped_url or "", final_job_text, cv_file.filename)

    # ── Generate ──
    try:
        result = await generate_adapted_cv(cv_text, final_job_text, gen_id, output_language)
        cv_data = result["cv_data"]
        local_pdf = result["pdf_path"]
    except Exception as e:
        _update(gen_id, "", status="failed")
        raise HTTPException(500, f"Generation failed: {e}")

    # ── Store PDF ──
    if AUTH_ENABLED:
        from app.storage import save_pdf
        storage_user = "anonymous" if anonymous else user.id
        pdf_ref = save_pdf(local_pdf, storage_user if not anonymous else f"anonymous/{claim_token}")
    else:
        pdf_ref = local_pdf

    job_title = cv_data.get("job_title_applied", "Unknown Role")
    company = cv_data.get("company_applied", "Unknown Company")
    _update(gen_id, pdf_ref, job_title=job_title, company=company, status="completed", cv_data=cv_data)

    # ── Deduct credit (authenticated users only) ──
    if AUTH_ENABLED and not anonymous:
        from app.supabase_db import get_profile, consume_credit
        profile = get_profile(user.id)
        if profile:
            consume_credit(user.id, profile)

    if anonymous:
        return {"claim_token": claim_token, "job_title": job_title, "company": company}
    return {"id": gen_id, "job_title": job_title, "company": company, "download_url": f"/api/download/{gen_id}"}


@app.post("/api/claim")
async def claim_cv(
    claim_token: str = Form(...),
    user=Depends(get_current_user),
):
    """Claim an anonymously generated CV after the user logs in."""
    if not AUTH_ENABLED:
        raise HTTPException(503, "Auth not enabled")

    from app.supabase_db import get_or_create_profile, can_generate, consume_credit, claim_generation

    profile = get_or_create_profile(user.id, user.email)
    allowed, reason = can_generate(profile)
    if not allowed:
        raise HTTPException(402, detail=reason)

    gen = claim_generation(claim_token, user.id)
    if not gen:
        raise HTTPException(404, "CV not found or already claimed")

    consume_credit(user.id, profile)

    return {"id": gen["id"], "download_url": f"/api/download/{gen['id']}"}


@app.get("/api/download/{gen_id}")
async def download(gen_id: str):
    # No auth required — the UUID gen_id acts as the capability token (128-bit random)
    if AUTH_ENABLED:
        from app.supabase_db import get_generation
    else:
        from app.database import get_generation

    gen = get_generation(gen_id)
    if not gen:
        raise HTTPException(404, "Not found")
    if gen.get("status") != "completed":
        raise HTTPException(404, "PDF not available")

    pdf_ref = gen.get("pdf_storage_path") or gen.get("output_pdf_path", "")
    if not pdf_ref:
        raise HTTPException(404, "PDF not found")

    company = (gen.get("company") or "company").replace(" ", "_")[:30]
    job_title = (gen.get("job_title") or "cv").replace(" ", "_")[:30]
    filename = f"CV_{company}_{job_title}.pdf"

    from fastapi.responses import Response
    if AUTH_ENABLED:
        from app.storage import download_pdf_bytes
        try:
            data = download_pdf_bytes(pdf_ref)
        except Exception:
            raise HTTPException(404, "PDF file not found in storage")
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if not os.path.exists(pdf_ref):
        raise HTTPException(404, "PDF file not found on disk")
    return FileResponse(path=pdf_ref, media_type="application/pdf", filename=filename)


@app.get("/api/tips/{gen_id}")
async def interview_tips(gen_id: str, user=Depends(get_current_user)):
    if AUTH_ENABLED:
        from app.supabase_db import get_generation, save_generation_tips
    else:
        from app.database import get_generation, save_generation_tips

    gen = get_generation(gen_id)
    if not gen or gen.get("status") != "completed":
        raise HTTPException(404, "Generation not found or not completed")

    # Return cached tips if available
    cached = gen.get("interview_tips")
    if cached:
        return {"tips": cached}

    cv_data = gen.get("cv_data")
    if not cv_data:
        raise HTTPException(422, "CV data not available for this generation (regenerate the CV to enable tips)")

    from app.cv_generator import generate_interview_tips
    try:
        tips = await generate_interview_tips(cv_data, gen.get("job_text", ""))
    except Exception as e:
        raise HTTPException(500, f"Could not generate tips: {e}")

    save_generation_tips(gen_id, tips)
    return {"tips": tips}


@app.get("/api/history")
async def api_history(user=Depends(get_current_user)):
    if AUTH_ENABLED:
        from app.supabase_db import get_user_generations
        return get_user_generations(user.id)
    else:
        from app.database import get_all_generations
        return get_all_generations()


# ── Payments ───────────────────────────────────────────────

@app.post("/api/create-checkout")
async def create_checkout(
    product: str = Form(...),  # "single" | "monthly" | "extra"
    user=Depends(get_current_user),
):
    if not PAYMENTS_ENABLED:
        raise HTTPException(503, "Payments not configured")
    if not AUTH_ENABLED:
        raise HTTPException(503, "Auth not configured")

    from app.supabase_db import get_or_create_stripe_customer, get_profile
    from app.payments import create_checkout as _checkout

    customer_id = get_or_create_stripe_customer(user.id, user.email)
    base_url = os.environ.get("APP_URL", "http://localhost:8001")

    if product == "single":
        url = _checkout(
            customer_id=customer_id,
            price_id=os.environ["STRIPE_PRICE_SINGLE"],
            mode="payment",
            success_url=f"{base_url}/payment/success?product=single",
            cancel_url=f"{base_url}/",
            metadata={"user_id": user.id, "product": "single"},
        )
    elif product == "monthly":
        url = _checkout(
            customer_id=customer_id,
            price_id=os.environ["STRIPE_PRICE_MONTHLY"],
            mode="subscription",
            success_url=f"{base_url}/payment/success?product=monthly",
            cancel_url=f"{base_url}/",
            metadata={"user_id": user.id, "product": "monthly"},
        )
    elif product == "extra":
        profile = get_profile(user.id)
        if not profile or profile.get("plan") != "monthly":
            raise HTTPException(403, "Extra credits are only available for active subscribers")
        url = _checkout(
            customer_id=customer_id,
            price_id=os.environ["STRIPE_PRICE_EXTRA"],
            mode="payment",
            success_url=f"{base_url}/payment/success?product=extra",
            cancel_url=f"{base_url}/",
            metadata={"user_id": user.id, "product": "extra"},
        )
    else:
        raise HTTPException(400, "Invalid product")

    return {"checkout_url": url}


@app.post("/api/billing-portal")
async def billing_portal(user=Depends(get_current_user)):
    if not PAYMENTS_ENABLED:
        raise HTTPException(503, "Payments not configured")
    from app.supabase_db import get_profile
    from app.payments import create_portal
    profile = get_profile(user.id)
    if not profile or not profile.get("stripe_customer_id"):
        raise HTTPException(404, "No billing account found")
    base_url = os.environ.get("APP_URL", "http://localhost:8001")
    url = create_portal(profile["stripe_customer_id"], f"{base_url}/")
    return {"portal_url": url}


@app.post("/api/stripe-webhook")
async def stripe_webhook(request: Request):
    if not PAYMENTS_ENABLED:
        raise HTTPException(503, "Payments not configured")

    from app.payments import verify_webhook
    from app.supabase_db import activate_subscription, add_credits, cancel_subscription

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    event = verify_webhook(payload, sig)

    etype = event["type"]
    data = event["data"]["object"]

    if etype == "checkout.session.completed":
        customer_id = data.get("customer")
        mode = data.get("mode")
        if mode == "payment":
            # single CV ($1.99) or extra CV ($0.99) — always 1 credit
            add_credits(customer_id, 1)
        # subscriptions handled by invoice.payment_succeeded to avoid double-crediting

    elif etype == "customer.subscription.deleted":
        cancel_subscription(data.get("customer"))

    elif etype == "invoice.payment_succeeded":
        # Fires on new subscription AND renewals — grants 30 credits each time
        customer_id = data.get("customer")
        sub_id = data.get("subscription")
        if sub_id:
            import stripe
            stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
            sub = stripe.Subscription.retrieve(sub_id)
            activate_subscription(customer_id, sub_id, sub["current_period_end"])

    return {"ok": True}
