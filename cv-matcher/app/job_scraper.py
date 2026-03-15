import httpx
import re


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


async def scrape_job_url(url: str) -> dict:
    """Try to scrape a job URL. Returns dict with text and metadata."""
    try:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return {"success": False, "error": f"HTTP {response.status_code}"}
            html = response.text
            text = _extract_text_from_html(html)
            if len(text) < 100:
                return {"success": False, "error": "Could not extract enough content from the URL"}
            return {"success": True, "text": text}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _extract_text_from_html(html: str) -> str:
    # Remove scripts and styles
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Clean whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    return text
