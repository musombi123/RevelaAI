# ai/tools.py
import math
import requests
import os

# -----------------------
# Basic calculator (kept)
# -----------------------
def calculate(expression: str) -> str:
    try:
        return str(eval(expression, {"__builtins__": {}}, math.__dict__))
    except Exception as e:
        return f"Error: {str(e)}"


# -----------------------
# Web search (API-based)
# -----------------------
def web_search(query: str, limit: int = 5) -> list:
    """
    Uses SerpAPI or compatible search API.
    """
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return []

    params = {
        "q": query,
        "api_key": api_key,
        "engine": "google",
        "num": limit
    }

    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return [
            {
                "title": r.get("title"),
                "snippet": r.get("snippet"),
                "link": r.get("link")
            }
            for r in data.get("organic_results", [])
        ]
    except Exception:
        return []


# -----------------------
# Fetch public web page
# -----------------------
def fetch_url_text(url: str) -> str:
    """
    Fetches and returns raw text from a public URL.
    """
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "RevelaAI/1.0"})
        r.raise_for_status()
        return r.text[:8000]  # hard cap for safety
    except Exception as e:
        return f"Error fetching URL: {str(e)}"
