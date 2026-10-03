from __future__ import annotations

"""RevelaAI live web research provider.

The research subsystem supports:
- live/current web searches
- short-lived caching
- SerpAPI when configured
- Wikipedia + DuckDuckGo fallback
- source-page enrichment
- explicit runtime capability/status metadata
- realtime-query detection for freshness-sensitive requests

Important:
A connected research runtime is different from whether a particular
request actually required web research or whether that request returned
usable sources.
"""

import hashlib
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import ipaddress
from urllib.parse import quote, quote_plus, urlparse

LOGGER = logging.getLogger(__name__)

SERPAPI_ENDPOINT = "https://serpapi.com/search"

USER_AGENT = os.getenv(
    "REVELAAI_WEB_USER_AGENT",
    "RevelaAI/2.0 (+live research)",
)

TIMEOUT = max(4, int(os.getenv("REVELAAI_WEB_TIMEOUT", "12")))

RESULT_LIMIT = max(
    1,
    min(int(os.getenv("REVELAAI_WEB_RESULTS", "5")), 10),
)

ENRICH_LIMIT = max(
    0,
    min(int(os.getenv("REVELAAI_WEB_ENRICH_RESULTS", "3")), 5),
)

MAX_CONTENT_CHARS = max(
    1200,
    int(os.getenv("REVELAAI_WEB_MAX_CHARS", "7000")),
)

NORMAL_TTL = max(
    0,
    int(os.getenv("REVELAAI_WEB_CACHE_TTL", "900")),
)

REALTIME_TTL = max(
    0,
    int(os.getenv("REVELAAI_WEB_REALTIME_TTL", "60")),
)

CACHE_FILE = Path(
    os.getenv(
        "REVELAAI_WEB_CACHE_FILE",
        "/tmp/revelaai_web_cache.json",
    )
)

# Explicit freshness-sensitive language.
# These terms are intentionally broader than "latest"/"today".
_REALTIME_TERMS = (
    "latest",
    "newest",
    "recent",
    "recently",
    "today",
    "tonight",
    "yesterday",
    "tomorrow",
    "current",
    "currently",
    "now",
    "this week",
    "this month",
    "this year",
    "breaking",
    "live",
    "real-time",
    "real time",
    "realtime",
    "live information",
    "live data",
    "real-time information",
    "real-time data",
    "up to date",
    "up-to-date",
    "as of today",
    "as of now",
    "right now",
    "at the moment",
)

_NEWS_TERMS = (
    "news",
    "breaking",
    "headline",
    "headlines",
    "latest news",
    "today's news",
)

_SKIP_ENRICH = {
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
}

_CACHE: dict[str, dict] = {}

_LOCK = threading.RLock()
_THREAD_LOCAL = threading.local()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now().isoformat()


def _parse_iso(value: Any) -> datetime | None:
    try:
        text = str(value or "").strip().replace("Z", "+00:00")

        if not text:
            return None

        result = datetime.fromisoformat(text)

        if result.tzinfo is None:
            return result.replace(tzinfo=timezone.utc)

        return result
    except (TypeError, ValueError):
        return None


def _load_cache() -> dict[str, dict]:
    global _CACHE

    with _LOCK:
        if _CACHE:
            return _CACHE

        try:
            if CACHE_FILE.exists():
                data = json.loads(
                    CACHE_FILE.read_text(encoding="utf-8")
                )

                _CACHE = data if isinstance(data, dict) else {}

        except Exception as exc:
            LOGGER.warning("Web cache load failed: %s", exc)
            _CACHE = {}

        return _CACHE


def _save_cache() -> None:
    with _LOCK:
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

            tmp = CACHE_FILE.with_suffix(
                CACHE_FILE.suffix + ".tmp"
            )

            tmp.write_text(
                json.dumps(
                    _CACHE,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            tmp.replace(CACHE_FILE)

        except Exception as exc:
            LOGGER.warning(
                "Web cache save failed: %s",
                exc,
            )


def _cache_key(query: str, news: bool) -> str:
    raw = (
        f"{query.strip().lower()}|"
        f"{'news' if news else 'web'}"
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def _cache_get(
    key: str,
    ttl: int,
) -> dict | None:
    if ttl <= 0:
        return None

    item = _load_cache().get(key)

    if not isinstance(item, dict):
        return None

    retrieved_at = _parse_iso(
        item.get("retrieved_at")
    )

    if not retrieved_at:
        return None

    age_seconds = (
        _now() - retrieved_at
    ).total_seconds()

    if age_seconds > ttl:
        return None

    payload = item.get("payload")

    return payload if isinstance(payload, dict) else None


def _cache_set(
    key: str,
    payload: dict,
) -> None:
    with _LOCK:
        _load_cache()[key] = {
            "retrieved_at": payload.get(
                "retrieved_at",
                _iso(),
            ),
            "payload": payload,
        }

        _save_cache()


def _session() -> requests.Session:
    """
    One requests Session per worker thread.

    This preserves connection pooling without sharing a Session
    across concurrent enrichment threads.
    """
    session = getattr(
        _THREAD_LOCAL,
        "session",
        None,
    )

    if session is not None:
        return session

    session = requests.Session()

    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.35,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=10,
        pool_maxsize=10,
    )

    session.mount(
        "https://",
        adapter,
    )

    session.mount(
        "http://",
        adapter,
    )

    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.8",
            "Cache-Control": "no-cache",
        }
    )

    _THREAD_LOCAL.session = session

    return session


def normalize_query(query: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(query or "").strip(),
    )


def _contains_phrase(
    text: str,
    phrase: str,
) -> bool:
    """
    Match complete words/phrases where possible.

    This prevents simple substring false positives such as:
    "live" matching a larger unrelated token.
    """
    normalized_text = normalize_query(text).lower()
    normalized_phrase = normalize_query(phrase).lower()

    if not normalized_phrase:
        return False

    if " " in normalized_phrase or "-" in normalized_phrase:
        return normalized_phrase in normalized_text

    pattern = rf"\b{re.escape(normalized_phrase)}\b"

    return bool(
        re.search(
            pattern,
            normalized_text,
            flags=re.IGNORECASE,
        )
    )


def is_realtime_query(query: str) -> bool:
    text = normalize_query(query)

    return any(
        _contains_phrase(text, term)
        for term in _REALTIME_TERMS
    )


def is_news_query(query: str) -> bool:
    text = normalize_query(query)

    return any(
        _contains_phrase(text, term)
        for term in _NEWS_TERMS
    )


def clean_text(text: Any) -> str:
    value = str(text or "")

    # Remove common bracket-style citation markers such as [1], [25].
    value = re.sub(
        r"\[\d{1,4}\]",
        "",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def fetch(
    url: str,
    timeout: int | None = None,
) -> str:
    target = str(url or "").strip()

    if not target:
        return ""

    try:
        response = _session().get(
            target,
            timeout=timeout or TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code >= 400:
            return ""

        return response.text

    except requests.RequestException as exc:
        LOGGER.info(
            "Live fetch failed for %s: %s",
            target,
            exc,
        )
        return ""

# =========================================================
# DIRECT URL RETRIEVAL
# =========================================================

_DIRECT_URL_PATTERN = re.compile(
    r"https?://[^\s<>\[\]\"']+",
    re.IGNORECASE,
)

DIRECT_URL_MAX_CHARS = max(
    1200,
    int(
        os.getenv(
            "REVELAAI_DIRECT_URL_MAX_CHARS",
            "12000",
        )
    ),
)


def extract_urls(
    text: str,
) -> list[str]:
    """
    Extract explicit HTTP/HTTPS URLs supplied by the user.
    """

    value = str(
        text or ""
    ).strip()

    if not value:
        return []

    matches = (
        _DIRECT_URL_PATTERN.findall(
            value
        )
    )

    urls: list[str] = []

    for raw in matches:

        url = raw.rstrip(
            ".,;:!?)]}>"
        ).strip()

        if not url:
            continue

        parsed = urlparse(
            url
        )

        if parsed.scheme not in {
            "http",
            "https",
        }:
            continue

        if not parsed.netloc:
            continue

        if url not in urls:
            urls.append(url)

    return urls[:10]


def _is_safe_public_url(
    url: str,
) -> tuple[bool, str | None]:
    """
    Basic SSRF protection for direct URL retrieval.

    Direct user URLs may only use HTTP/HTTPS and may not
    explicitly target loopback/private/link-local hosts.
    """

    try:

        parsed = urlparse(
            str(url or "").strip()
        )

        if parsed.scheme not in {
            "http",
            "https",
        }:
            return (
                False,
                "unsupported_url_scheme",
            )

        if not parsed.hostname:
            return (
                False,
                "missing_hostname",
            )

        hostname = (
            parsed.hostname
            .strip()
            .lower()
        )

        if (
            parsed.username
            or parsed.password
        ):
            return (
                False,
                "embedded_credentials_not_allowed",
            )

        # Check literal IP addresses.
        try:

            ip = ipaddress.ip_address(
                hostname
            )

            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                return (
                    False,
                    "private_or_reserved_address",
                )

        except ValueError:
            # Normal public hostname.
            pass

        blocked_hosts = {
            "localhost",
            "localhost.localdomain",
            "ip6-localhost",
            "ip6-loopback",
        }

        if hostname in blocked_hosts:
            return (
                False,
                "localhost_not_allowed",
            )

        return (
            True,
            None,
        )

    except Exception:
        return (
            False,
            "invalid_url",
        )


def _extract_direct_response_content(
    response: requests.Response,
    url: str,
) -> dict[str, Any]:
    """
    Normalize HTML, JSON, and plain-text direct URL
    responses into one source structure.
    """

    content_type = (
        response.headers.get(
            "Content-Type",
            "",
        )
        or ""
    ).lower()

    raw_text = (
        response.text
        or ""
    ).strip()

    # -----------------------------------------------------
    # JSON
    # -----------------------------------------------------

    looks_like_json = (
        "json" in content_type
        or raw_text.startswith("{")
        or raw_text.startswith("[")
    )

    if looks_like_json:

        try:

            payload = response.json()

            if isinstance(
                payload,
                dict,
            ):

                data = payload

                nested = payload.get(
                    "data"
                )

                if isinstance(
                    nested,
                    dict,
                ):
                    data = nested

                content = str(
                    data.get(
                        "content",
                        "",
                    )
                    or data.get(
                        "text",
                        "",
                    )
                    or data.get(
                        "full_text",
                        "",
                    )
                    or data.get(
                        "description",
                        "",
                    )
                    or ""
                ).strip()

                title = str(
                    data.get(
                        "title",
                        "",
                    )
                    or data.get(
                        "name",
                        "",
                    )
                    or payload.get(
                        "type",
                        "",
                    )
                    or ""
                ).strip()

                if content:

                    return {
                        "title": title,
                        "description": "",
                        "content": content[
                            :DIRECT_URL_MAX_CHARS
                        ],
                        "url": url,
                        "retrieved": True,
                        "provider": "direct_url",
                        "content_type": (
                            content_type
                        ),
                    }

        except Exception as exc:

            LOGGER.info(
                "Direct JSON parsing failed for %s: %s",
                url,
                exc,
            )

    # -----------------------------------------------------
    # HTML
    # -----------------------------------------------------

    if (
        "html" in content_type
        or "<html" in raw_text[:500].lower()
        or "<!doctype" in raw_text[:500].lower()
    ):

        page = extract_page(
            url,
            raw_text,
        )

        return {
            "title": page.get(
                "title",
                "",
            ),
            "description": page.get(
                "description",
                "",
            ),
            "content": str(
                page.get(
                    "content",
                    "",
                )
                or ""
            )[
                :DIRECT_URL_MAX_CHARS
            ],
            "url": url,
            "retrieved": bool(
                page.get(
                    "content",
                    "",
                )
                or page.get(
                    "description",
                    "",
                )
            ),
            "provider": "direct_url",
            "content_type": content_type,
        }

    # -----------------------------------------------------
    # PLAIN TEXT / OTHER TEXT
    # -----------------------------------------------------

    clean = clean_text(
        raw_text
    )

    return {
        "title": "",
        "description": "",
        "content": clean[
            :DIRECT_URL_MAX_CHARS
        ],
        "url": url,
        "retrieved": bool(
            clean
        ),
        "provider": "direct_url",
        "content_type": content_type,
    }


def fetch_url_source(
    url: str,
    timeout: int | None = None,
) -> dict[str, Any]:
    """
    Fetch a single user-provided public URL.

    This supports:
        - JSON APIs
        - HTML pages
        - plain text
    """

    target = str(
        url or ""
    ).strip()

    if not target:

        return {
            "url": target,
            "retrieved": False,
            "provider": "direct_url",
            "error": {
                "code": "empty_url",
                "message": "URL is empty.",
            },
        }

    safe, reason = (
        _is_safe_public_url(
            target
        )
    )

    if not safe:

        return {
            "url": target,
            "retrieved": False,
            "provider": "direct_url",
            "error": {
                "code": "unsafe_url",
                "message": reason,
            },
        }

    try:

        response = _session().get(
            target,
            timeout=timeout or TIMEOUT,
            allow_redirects=True,
        )

        response.raise_for_status()

        result = (
            _extract_direct_response_content(
                response,
                target,
            )
        )

        result[
            "retrieved_at"
        ] = _iso()

        result[
            "status_code"
        ] = response.status_code

        result[
            "final_url"
        ] = response.url

        return result

    except requests.RequestException as exc:

        LOGGER.info(
            "Direct URL retrieval failed for %s: %s",
            target,
            exc,
        )

        return {
            "url": target,
            "retrieved": False,
            "provider": "direct_url",
            "retrieved_at": _iso(),
            "error": {
                "code": "direct_url_fetch_failed",
                "message": str(exc),
            },
        }


def fetch_direct_urls(
    urls: list[str],
    limit: int = 5,
) -> dict[str, Any]:
    """
    Retrieve multiple explicit user-provided URLs.
    """

    normalized_urls = []

    for url in urls:

        value = str(
            url or ""
        ).strip()

        if (
            value
            and value not in normalized_urls
        ):

            normalized_urls.append(
                value
            )

        if len(
            normalized_urls
        ) >= limit:

            break

    sources: list[dict] = []
    errors: list[dict] = []

    for url in normalized_urls:

        result = (
            fetch_url_source(
                url
            )
        )

        if result.get(
            "retrieved",
            False,
        ):

            result[
                "freshness"
            ] = "live"

            sources.append(
                result
            )

        else:

            error = result.get(
                "error"
            )

            if isinstance(
                error,
                dict,
            ):

                errors.append({
                    "url": url,
                    **error,
                })

            else:

                errors.append({
                    "url": url,
                    "code": (
                        "direct_url_unavailable"
                    ),
                    "message": (
                        "The URL could not be retrieved."
                    ),
                })

    return {
        "available": bool(
            sources
        ),

        "runtime_available": True,

        "runtime_status": "connected",

        "status": (
            "active"
            if sources
            else "required_but_unavailable"
        ),

        "provider": "direct_url",

        "query": (
            " ".join(
                normalized_urls
            )
        ),

        "realtime": True,

        "freshness": "live",

        "retrieved_at": _iso(),

        "source_count": len(
            sources
        ),

        "sources": sources,

        "errors": errors,
    }


def extract_paragraphs(
    html: str,
    limit_chars: int = MAX_CONTENT_CHARS,
) -> list[str]:
    if not html:
        return []

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "nav",
            "footer",
            "header",
            "form",
            "aside",
        ]
    ):
        tag.decompose()

    output: list[str] = []
    total = 0

    for node in soup.find_all("p"):
        text = clean_text(
            node.get_text(
                " ",
                strip=True,
            )
        )

        if len(text) < 40:
            continue

        lowered = text.lower()

        if any(
            marker in lowered
            for marker in (
                "skip to main content",
                "privacy policy",
                "cookie policy",
                "sign up",
                "log in",
            )
        ):
            continue

        remaining = limit_chars - total

        if remaining <= 0:
            break

        if len(text) > remaining:
            shortened = text[:remaining]

            if " " in shortened:
                shortened = shortened.rsplit(
                    " ",
                    1,
                )[0]

            text = shortened

        if text:
            output.append(text)
            total += len(text)

    return output


def extract_page(
    url: str,
    html: str,
) -> dict:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    title = clean_text(
        soup.title.get_text(
            " ",
            strip=True,
        )
        if soup.title
        else ""
    )

    description = ""

    meta = soup.find(
        "meta",
        attrs={
            "name": re.compile(
                r"^description$",
                re.I,
            )
        },
    )

    if meta:
        description = clean_text(
            meta.get(
                "content",
                "",
            )
        )

    paragraphs = extract_paragraphs(html)

    return {
        "title": title,
        "description": description,
        "content": clean_text(
            " ".join(paragraphs)
        ),
        "url": url,
    }


def _serp_key() -> str:
    return (
        os.getenv("SERPAPI_API_KEY")
        or os.getenv("SERPAPI_KEY")
        or ""
    ).strip()


def _search_serpapi(
    query: str,
    limit: int,
    realtime: bool,
) -> dict:
    key = _serp_key()

    if not key:
        return {
            "available": False,
            "provider": "serpapi",
            "sources": [],
            "error": {
                "code": "missing_search_key",
                "message": (
                    "SERPAPI_API_KEY or SERPAPI_KEY "
                    "is not configured."
                ),
            },
        }

    news = is_news_query(query)

    params = {
        "engine": (
            "google_news"
            if news
            else "google"
        ),
        "q": query,
        "api_key": key,
        "hl": "en",
        "gl": "ke",
        "num": limit,
        "no_cache": (
            "true"
            if realtime
            else "false"
        ),
    }

    if news:
        params["so"] = "1"

    try:
        response = _session().get(
            SERPAPI_ENDPOINT,
            params=params,
            timeout=TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError(
                "Invalid search response"
            )

        if data.get("error"):
            return {
                "available": False,
                "provider": "serpapi",
                "sources": [],
                "error": {
                    "code": "search_provider_error",
                    "message": str(
                        data["error"]
                    ),
                },
            }

        raw = (
            data.get("news_results", [])
            if news
            else data.get(
                "organic_results",
                [],
            )
        )

        sources: list[dict] = []

        for item in (
            raw
            if isinstance(raw, list)
            else []
        ):
            if not isinstance(item, dict):
                continue

            url = str(
                item.get("link")
                or item.get("redirect_link")
                or ""
            ).strip()

            title = clean_text(
                item.get("title")
            )

            snippet = clean_text(
                item.get("snippet")
                or item.get("description")
            )

            if not (
                url
                or title
                or snippet
            ):
                continue

            sources.append(
                {
                    "title": title,
                    "snippet": snippet,
                    "url": url,
                    "source": clean_text(
                        item.get("source")
                    ),
                    "published": clean_text(
                        item.get("date")
                    ),
                    "author": clean_text(
                        item.get("author")
                    ),
                    "provider": "serpapi",
                    "position": item.get(
                        "position"
                    ),
                }
            )

        return {
            "available": bool(sources),
            "provider": "serpapi",
            "sources": sources[:limit],
        }

    except Exception as exc:
        return {
            "available": False,
            "provider": "serpapi",
            "sources": [],
            "error": {
                "code": "search_request_failed",
                "message": str(exc),
            },
        }


def wikipedia_search(query: str) -> str:
    try:
        response = _session().get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "utf8": "1",
                "srlimit": 1,
            },
            timeout=TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        rows = (
            data.get("query", {})
            .get("search", [])
        )

        if not rows:
            return ""

        title = str(
            rows[0].get("title")
            or ""
        ).strip()

        if not title:
            return ""

        return (
            "https://en.wikipedia.org/wiki/"
            + quote(
                title.replace(" ", "_"),
                safe="_()",
            )
        )

    except Exception as exc:
        LOGGER.info(
            "Wikipedia search failed: %s",
            exc,
        )
        return ""


# Backward-compatible public alias.
scrape_wikipedia = wikipedia_search


def duckduckgo_search(
    query: str,
) -> list[str]:
    html = fetch(
        "https://duckduckgo.com/html/?q="
        + quote_plus(query)
    )

    if not html:
        return []

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    links: list[str] = []

    for anchor in soup.select(".result__a"):
        href = str(
            anchor.get("href")
            or ""
        ).strip()

        if (
            href.startswith("http")
            and href not in links
        ):
            links.append(href)

        if len(links) >= 5:
            break

    return links


def _fallback_search(
    query: str,
    limit: int,
) -> list[dict]:
    sources: list[dict] = []

    wiki = wikipedia_search(query)

    if wiki:
        sources.append(
            {
                "title": "Wikipedia",
                "snippet": "",
                "url": wiki,
                "source": "Wikipedia",
                "published": "",
                "provider": "wikipedia",
            }
        )

    for url in duckduckgo_search(query):
        if url == wiki:
            continue

        sources.append(
            {
                "title": "",
                "snippet": "",
                "url": url,
                "source": "",
                "published": "",
                "provider": "duckduckgo",
            }
        )

        if len(sources) >= limit:
            break

    return sources[:limit]


def _host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()

        if host.startswith("www."):
            host = host[4:]

        return host

    except Exception:
        return ""


def _enrich(source: dict) -> dict:
    result = dict(source)

    url = str(
        source.get("url")
        or ""
    ).strip()

    host = _host(url)

    if (
        not url
        or not host
        or host in _SKIP_ENRICH
        or any(
            host.endswith("." + domain)
            for domain in _SKIP_ENRICH
        )
    ):
        result["retrieved"] = False
        return result

    html = fetch(url)

    if not html:
        result["retrieved"] = False
        return result

    try:
        page = extract_page(
            url,
            html,
        )

        result["title"] = (
            result.get("title")
            or page.get("title", "")
        )

        result["snippet"] = (
            result.get("snippet")
            or page.get(
                "description",
                "",
            )
        )

        result["content"] = page.get(
            "content",
            "",
        )

        result["retrieved"] = bool(
            result.get("content")
            or result.get("snippet")
        )

    except Exception:
        result["retrieved"] = False

    return result


def _rank(
    sources: list[dict],
    query: str,
) -> list[dict]:
    words = {
        word
        for word in re.findall(
            r"\b\w+\b",
            query.lower(),
        )
        if len(word) >= 3
    }

    def score(item: dict) -> float:
        title = str(
            item.get("title")
            or ""
        ).lower()

        snippet = str(
            item.get("snippet")
            or ""
        ).lower()

        content = str(
            item.get("content")
            or ""
        ).lower()

        value = 0.0

        for word in words:
            value += (
                4
                if word in title
                else 0
            )

            value += (
                2
                if word in snippet
                else 0
            )

            value += (
                1
                if word in content
                else 0
            )

        value += (
            0.5
            if item.get("retrieved")
            else 0
        )

        value += (
            0.2
            if item.get("published")
            else 0
        )

        return value

    return sorted(
        sources,
        key=score,
        reverse=True,
    )


class LiveWebResearcher:
    """
    Live research service.

    runtime_available describes whether the research subsystem itself
    is operationally connected.

    available describes whether this particular query returned usable
    sources.
    """

    def search(
        self,
        query: str,
        limit: int = RESULT_LIMIT,
        *,
        realtime: bool | None = None,
        force_refresh: bool = False,
    ) -> dict:
        query = normalize_query(query)

        if not query:
            return {
                "available": False,
                "runtime_available": True,
                "runtime_status": "connected",
                "status": "required_but_unavailable",
                "query": "",
                "sources": [],
                "realtime": False,
                "freshness": "none",
                "retrieved_at": _iso(),
                "provider": None,
                "errors": [
                    {
                        "code": "empty_query",
                        "message": (
                            "A search query is required."
                        ),
                    }
                ],
            }

        limit = max(
            1,
            min(int(limit), 10),
        )

        realtime_mode = (
            is_realtime_query(query)
            if realtime is None
            else bool(realtime)
        )

        news = is_news_query(query)

        ttl = (
            REALTIME_TTL
            if realtime_mode
            else NORMAL_TTL
        )

        key = _cache_key(
            query,
            news,
        )

        if not force_refresh:
            cached = _cache_get(
                key,
                ttl,
            )

            if cached is not None:
                cached = dict(cached)

                cached["cache"] = "hit"
                cached["freshness"] = "cached"

                # The runtime remains connected even when
                # this result came from cache.
                cached.setdefault(
                    "runtime_available",
                    True,
                )

                cached.setdefault(
                    "runtime_status",
                    "connected",
                )

                cached["status"] = (
                    "active"
                    if cached.get("available")
                    else "required_but_unavailable"
                )

                return cached

        retrieved_at = _iso()

        result = _search_serpapi(
            query,
            limit,
            realtime_mode,
        )

        errors: list[dict] = []

        if isinstance(
            result.get("error"),
            dict,
        ):
            errors.append(
                result["error"]
            )

        sources = (
            result.get("sources", [])
            if isinstance(
                result.get("sources"),
                list,
            )
            else []
        )

        provider = (
            result.get("provider")
            or None
        )

        # If SerpAPI returned no usable sources,
        # use the fallback stack.
        if not sources:
            fallback = _fallback_search(
                query,
                limit,
            )

            if fallback:
                sources = fallback
                provider = "fallback"

        enrich_n = min(
            ENRICH_LIMIT,
            len(sources),
        )

        enriched: list[dict] = []

        if enrich_n:
            with ThreadPoolExecutor(
                max_workers=enrich_n
            ) as pool:
                futures = [
                    pool.submit(
                        _enrich,
                        source,
                    )
                    for source in sources[
                        :enrich_n
                    ]
                ]

                for future in as_completed(
                    futures
                ):
                    try:
                        enriched.append(
                            future.result()
                        )
                    except Exception as exc:
                        LOGGER.info(
                            "Source enrichment failed: %s",
                            exc,
                        )

            enriched = _rank(
                enriched,
                query,
            )

            seen = {
                x.get("url")
                for x in enriched
            }

            enriched.extend(
                x
                for x in sources[
                    enrich_n:
                ]
                if x.get("url")
                not in seen
            )

        else:
            enriched = sources

        final_sources: list[dict] = []

        for source in enriched[:limit]:
            item = dict(source)

            content = str(
                item.get("content")
                or ""
            )

            item["content"] = content[
                :MAX_CONTENT_CHARS
            ]

            item["retrieved_at"] = (
                retrieved_at
            )

            item["freshness"] = (
                "live"
                if realtime_mode
                else "recent"
            )

            item["source_domain"] = _host(
                str(
                    item.get("url")
                    or ""
                )
            )

            final_sources.append(item)

        available = bool(final_sources)

        if available:
            status = "active"
        else:
            status = (
                "required_but_unavailable"
            )

        payload = {
            "available": available,

            # This is the important distinction for the
            # orchestrator/system prompt.
            "runtime_available": True,
            "runtime_status": "connected",
            "status": status,

            "query": query,
            "realtime": realtime_mode,
            "provider": provider,
            "retrieved_at": retrieved_at,
            "freshness": (
                "live"
                if realtime_mode
                else "recent"
            ),
            "source_count": len(final_sources),
            "sources": final_sources,
            "errors": errors,
            "cache": "miss",
        }

        if final_sources:
            _cache_set(
                key,
                payload,
            )

        return payload

    def scrape_knowledge(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict]:
        return scrape_knowledge(
            query,
            limit=limit,
        )


_RESEARCHER = LiveWebResearcher()


def scrape_knowledge(
    query: str,
    limit: int = 5,
    *,
    realtime: bool | None = None,
    force_refresh: bool = False,
) -> list[dict]:
    result = _RESEARCHER.search(
        query,
        limit=limit,
        realtime=realtime,
        force_refresh=force_refresh,
    )

    output: list[dict] = []

    for source in result.get(
        "sources",
        [],
    ):
        output.append(
            {
                "query": query,
                "title": source.get(
                    "title",
                    "",
                ),
                "text": (
                    source.get("content")
                    or source.get(
                        "snippet",
                        "",
                    )
                ),
                "url": source.get(
                    "url",
                    "",
                ),
                "source": source.get(
                    "source",
                    "",
                ),
                "published": source.get(
                    "published",
                    "",
                ),
                "retrieved_at": source.get(
                    "retrieved_at",
                    result.get(
                        "retrieved_at"
                    ),
                ),
                "realtime": result.get(
                    "realtime",
                    False,
                ),
                "freshness": result.get(
                    "freshness",
                    "unknown",
                ),
                "timestamp": time.time(),
            }
        )

    return output


def get_live_research(
    query: str,
    limit: int = 5,
    *,
    realtime: bool | None = None,
    force_refresh: bool = False,
) -> dict:
    return _RESEARCHER.search(
        query,
        limit=limit,
        realtime=realtime,
        force_refresh=force_refresh,
    )


__all__ = [
    "LiveWebResearcher",
    "get_live_research",
    "scrape_knowledge",
    "fetch",
    "extract_paragraphs",
    "extract_page",
    "scrape_wikipedia",
    "wikipedia_search",
    "duckduckgo_search",
    "normalize_query",
    "is_realtime_query",
    "is_news_query",
]
