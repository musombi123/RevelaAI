from flask import Blueprint, request, jsonify
import requests
import xml.etree.ElementTree as ET

rss_bp = Blueprint("rss_bp", __name__)

RSS_SOURCES = {
    "BBC News": "http://feeds.bbci.co.uk/news/rss.xml",
    "Reuters Tech": "https://www.reutersagency.com/feed/?best-topics=technology",
    "TechCrunch": "https://techcrunch.com/feed/",
    "Hacker News": "https://news.ycombinator.com/rss",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
}

@rss_bp.route("/api/research", methods=["POST"])
def research_rss():
    payload = request.get_json(silent=True) or {}
    query = payload.get("query", "").strip()

    if not query:
        return jsonify({"error": "query is required"}), 400

    results = []

    for name, url in RSS_SOURCES.items():
        try:
            resp = requests.get(url, timeout=10)
            root = ET.fromstring(resp.content)

            for item in root.findall(".//item"):
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                desc = item.findtext("description", "")

                text = (title + " " + desc).lower()
                if query.lower() in text:
                    results.append({
                        "source": name,
                        "title": title,
                        "url": link,
                        "snippet": desc
                    })
        except Exception as e:
            continue

    return jsonify({
        "query": query,
        "sources": results,
        "realtime": True
    })
