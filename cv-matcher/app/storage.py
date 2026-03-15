"""
PDF storage: local filesystem in dev, Supabase Storage in production.
"""
import os
from pathlib import Path
from functools import lru_cache

BUCKET = "cv-pdfs"
USE_CLOUD = bool(os.environ.get("SUPABASE_URL"))


@lru_cache()
def _sb():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def save_pdf(local_path: str, user_id: str) -> str:
    """Save PDF and return a storage reference string."""
    if not USE_CLOUD:
        return local_path  # local path is the reference in dev

    filename = Path(local_path).name
    storage_path = f"{user_id}/{filename}"
    with open(local_path, "rb") as f:
        _sb().storage.from_(BUCKET).upload(
            storage_path, f, {"content-type": "application/pdf", "upsert": "true"}
        )
    # Clean up local temp file
    try:
        os.remove(local_path)
    except Exception:
        pass
    return f"cloud:{storage_path}"


def get_pdf_response(storage_ref: str, download_filename: str):
    """Return the FastAPI response to serve or redirect to the PDF."""
    from fastapi.responses import FileResponse, RedirectResponse

    if not storage_ref.startswith("cloud:"):
        # Local file
        return FileResponse(path=storage_ref, media_type="application/pdf", filename=download_filename)

    # Cloud: generate signed URL (valid 1 hour)
    cloud_path = storage_ref[len("cloud:"):]
    result = _sb().storage.from_(BUCKET).create_signed_url(cloud_path, 3600)
    return RedirectResponse(url=result["signedURL"])
