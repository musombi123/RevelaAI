import feedparser
import urllib.parse
import time
import requests
from bs4 import BeautifulSoup
from services.rss_sources import RSS_SOURCES

def extract_text_from_url(url: str, max_chars: int = 2000) -> str:
    """Extract first 2k chars of text from any URL (lightweight)."""
    try:
        r = requests.get(url, timeout=5)
        soup = BeautifulSoup(r.text, "html.parser")
        texts = soup.find_all("p")
        full_text = " ".join([t.get_text() for t in texts])
        return full_text[:max_chars]
    except Exception:
        return ""

def fetch_rss_sources(query: str, limit: int = 8) -> list[dict]:
    """
    Fetch RSS sources and return top results with optional full text snippet.
    """
    results = []
    query_lower = query.lower().strip()

    for src in RSS_SOURCES:
        feed_url = src.get("url")
        if "url_template" in src:
            feed_url = src["url_template"].format(query=urllib.parse.quote(query))

        if not feed_url:
            continue

        try:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:limit]:
                title = getattr(entry, "title", "") or ""
                link = getattr(entry, "link", "") or ""
                snippet = getattr(entry, "summary", "") or ""
                full_text = extract_text_from_url(link)

                text_blob = f"{title} {snippet}".lower()
                if query_lower in text_blob or "url_template" in src:
                    results.append({
                        "source": src["name"],
                        "title": title.strip(),
                        "url": link.strip(),
                        "snippet": snippet.strip(),
                        "full_text": full_text,
                        "published_parsed": time.mktime(entry.get("published_parsed", time.gmtime()))
                    })

        except Exception:
            continue

    # Limit to top results
    return results[:limit]
