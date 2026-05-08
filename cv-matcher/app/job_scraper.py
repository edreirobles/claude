import httpx
import re


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _extract_linkedin_job_id(url: str) -> str | None:
    # Matches /jobs/view/1234567890/ or /jobs/view/some-title-1234567890/
    match = re.search(r"/jobs/view/(?:[^/]+-)?(\d{7,})", url)
    return match.group(1) if match else None


async def _scrape_linkedin(job_id: str) -> dict:
    """Use LinkedIn's public guest API — works without authentication."""
    guest_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    try:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            r = await client.get(guest_url)
            if r.status_code != 200:
                return {"success": False, "error": f"LinkedIn returned HTTP {r.status_code}"}
            text = _extract_text_from_html(r.text)
            if len(text) < 100:
                return {"success": False, "error": "Could not extract job content from LinkedIn"}
            return {"success": True, "text": text}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def scrape_job_url(url: str) -> dict:
    """Try to scrape a job URL. Returns dict with text and metadata."""
    url = url.strip()

    # LinkedIn jobs — use guest API
    if "linkedin.com/jobs" in url:
        job_id = _extract_linkedin_job_id(url)
        if not job_id:
            return {"success": False, "error": "Could not extract job ID from LinkedIn URL. Paste the job description instead."}
        return await _scrape_linkedin(job_id)

    # Generic URL — direct HTTP fetch
    try:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return {"success": False, "error": f"HTTP {response.status_code}"}
            text = _extract_text_from_html(response.text)
            if len(text) < 100:
                return {"success": False, "error": "Could not extract enough content from the URL"}
            return {"success": True, "text": text}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _extract_text_from_html(html: str) -> str:
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    return text
