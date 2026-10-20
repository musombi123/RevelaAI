"""Live open-source research for civilian science and engineering only."""
DEFENSIVE_ONLY = True
import re
from datetime import datetime, timezone
from xml.etree import ElementTree
import requests

BLOCKLIST = ["how to hack", "ddos", "create virus to attack", "bypass paywall", "hack into", "make weapon", "build a weapon", "bioweapon", "ransomware", "reverse shell"]


class ResearchPolicyViolation(Exception):
    """Framework-neutral denial for requests outside the civilian research policy."""

    code = 403


def is_offensive_query(q):
    value = str(q or "").lower()
    if any(term in value for term in BLOCKLIST):
        raise ResearchPolicyViolation(
            "RevelaAI Sci-Core is defensive & civilian research only"
        )
    return False

def _summarize(text, limit=5):
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    sentences = [re.sub(r"\s+", " ", s).strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 45]
    if not sentences: return text[:1200]
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", text.lower())
    freq = {}
    for w in words: freq[w] = freq.get(w, 0) + 1
    scored = []
    for i, sentence in enumerate(sentences):
        terms = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", sentence.lower())
        score = sum(freq.get(w, 0) for w in terms) / max(1, len(terms))
        scored.append((score, i, sentence))
    return " ".join(x[2] for x in sorted(sorted(scored, reverse=True)[:limit], key=lambda x:x[1]))[:3500]

def run_research(query, topic="general"):
    is_offensive_query(query)
    sources, passages = [], []
    try:
        params = {"search_query": "all:" + str(query)[:180], "start": 0, "max_results": 5}
        r = requests.get("https://export.arxiv.org/api/query", params=params, timeout=12)
        if r.ok:
            root = ElementTree.fromstring(r.text)
            ns = {"a":"http://www.w3.org/2005/Atom"}
            for entry in root.findall("a:entry", ns):
                title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
                summary = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
                link = next((x.attrib.get("href") for x in entry.findall("a:link", ns) if x.attrib.get("rel") == "alternate"), "")
                if title or summary:
                    passages.append(title + ". " + summary)
                    sources.append({"provider":"arxiv","title":title,"url":link})
    except Exception: pass
    try:
        r = requests.get("https://en.wikipedia.org/w/api.php", params={"action":"query","generator":"search","gsrsearch":str(query)[:180],"gsrlimit":4,"prop":"extracts","exintro":1,"explaintext":1,"format":"json"}, headers={"User-Agent":"RevelaAI-SciCore/1.0 (civilian research)"}, timeout=10)
        if r.ok:
            for item in r.json().get("query",{}).get("pages",{}).values():
                extract = item.get("extract","")
                if extract:
                    passages.append(extract)
                    sources.append({"provider":"wikipedia","title":item.get("title",""),"url":"https://en.wikipedia.org/?curid="+str(item.get("pageid",""))})
    except Exception: pass
    findings = _summarize(" ".join(passages)) if passages else "No source results were retrieved. Check network access and retry; no findings are inferred."
    result = {"topic":topic,"query":query,"findings":findings,"sources":sources,"timestamp":datetime.now(timezone.utc).isoformat(),"status":"research_complete" if sources else "no_sources","defensive_only":True}
    topic_l = str(topic).lower()
    query_l = str(query).lower()
    if any(x in topic_l+" "+query_l for x in ("electronics","software","hardware","esp32","sensor","irrigation","pump")):
        result.update({"bom":[{"item":"ESP32 development board","purpose":"low-cost controller"},{"item":"Sensor selected for the measurement","purpose":"environmental input"},{"item":"Fused, appropriately rated power supply","purpose":"protected power"},{"item":"Enclosure and wiring","purpose":"environmental and electrical protection"}],"circuit_concept":"Sensor output to ESP32 GPIO/ADC; power through a correctly rated protected supply; optional relay/MOSFET driver sized for the load with flyback protection for inductive loads. Keep mains voltage isolated and professionally installed.","pseudocode":"read sensor; validate range; apply hysteresis; send authenticated telemetry over TLS; on sensor/network failure enter safe state; never energize a pump without hardware interlocks."})
    try:
        from .storage import collection
        col = collection("research")
        col.insert_one(result.copy())
        result["storage_backend"] = getattr(col, "backend", "mongodb")
    except Exception as exc:
        result["audit_persisted"] = False
        result["storage_warning"] = "Research could not be persisted; check MongoDB configuration."
    else: result["audit_persisted"] = True
    return result
