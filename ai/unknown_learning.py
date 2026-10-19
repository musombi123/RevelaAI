"""Unknown-topic detection and consent-aware persistence for user-taught knowledge.

Public JSON records contain no uploaded image bytes: only a caller-supplied SHA-256.
Cross-user retrieval is limited to explicitly shared records with a human publication review.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_STORE_LOCK = threading.RLock()
_STOP = {
    "a","an","the","how","what","where","when","why","can","could","would","should",
    "to","for","with","in","on","at","from","my","me","you","your","it","this","that",
    "please","help","make","create","build","design","need","want","use","using","steps",
    "step","guide","tool","system","know","learn","teach","user","country","price","cost",
    "and","or","of","is","are","do","does","i","we","they","be","as","by","into","about",
    "kwa","ya","na","ni","je","jinsi","kutengeneza","namna","wa","za","kuna",
}
_SPECIALIZED = re.compile(
    r"\b(retrofit|auto.?weigh|posho.?mill|load.?cell|circuit|hardware|machine|machinery|"
    r"motor|pump|industrial|factory|wiring|electrical|bill of materials|bom|"
    r"repair|troubleshoot|sensor|actuator|plc|inverter|voltage|calibration|"
    r"fabricat|technician|fundi|kamukunji|cctv|solar controller|grain mill)\b",
    re.I,
)
_RESTRICTED = (
    "weapon construction", "explosive device", "credential theft", "malware deployment",
    "covert surveillance", "non-consensual tracking", "disable safety interlock",
    "bypass safety controls", "steal passwords", "ransomware deployment",
    "bombe bauen", "sprengsatz", "vol de mots de passe", "fabriquer une bombe",
    "construir una bomba", "制造炸弹", "窃取密码", "kutengeneza bomu",
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SHA_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_COMMIT_RE = re.compile(r"^[a-fA-F0-9]{7,40}$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def learning_root() -> Path:
    configured = os.getenv("REVELAAI_LEARNING_ROOT", "").strip()
    return Path(configured).expanduser() if configured else _ROOT / "living-brain"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def topic_slug(topic: str) -> str:
    value = str(topic or "").strip().lower()
    value = _SLUG_RE.sub("-", value).strip("-")
    if not value:
        value = "topic-" + hashlib.sha256(str(topic).encode("utf-8")).hexdigest()[:10]
    return value[:72].strip("-") or "topic"


def _terms(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]{2,}", str(text or "").lower()) if word not in _STOP}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
        if len(raw) > 2_000_000:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _atomic_json(path: Path, data: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".learning-", suffix=".tmp", dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _inventory_terms(root: Path) -> set[str]:
    collected: set[str] = set()
    for relative in ("core-one/inventions", "core-one/libraries/created"):
        base = root / relative
        if not base.is_dir():
            continue
        for path in list(base.iterdir())[:500]:
            collected |= _terms(path.name)
            if path.is_dir():
                for child in list(path.iterdir())[:24]:
                    collected |= _terms(child.name)
    return collected


def known_records(root: Path | None = None) -> list[dict[str, Any]]:
    base = root or learning_root()
    folder = base / "known"
    if not folder.is_dir():
        return []
    result = []
    for path in sorted(folder.glob("*.json"))[:1000]:
        item = _read_json(path)
        if not item:
            continue
        if item.get("status") == "known" and item.get("consent_to_share") is True and item.get("human_review", {}).get("published") is True:
            result.append(item)
    return result


def known_matches(message: str, root: Path | None = None, limit: int = 3) -> list[dict[str, Any]]:
    query = _terms(message)
    found: list[tuple[float, dict[str, Any]]] = []
    for item in known_records(root):
        topic = str(item.get("topic") or "")
        terms = query & _terms(topic + " " + " ".join(item.get("keywords", [])))
        if not terms:
            continue
        score = len(terms) / max(1, len(_terms(topic)))
        if score < 0.34:
            continue
        # Return only reviewed, explicitly shared, low-sensitivity learning summaries.
        found.append((score, {
            "topic": topic,
            "tool_name": str(item.get("tool_name") or ""),
            "endpoint": str(item.get("endpoint") or ""),
            "country": str(item.get("country") or "KE"),
            "language": str(item.get("language") or "en"),
            "steps": [str(x)[:500] for x in item.get("steps", [])[:8]],
            "review_status": "human_reviewed",
            "evidence_reference": str(item.get("human_review", {}).get("merge_commit") or ""),
        }))
    found.sort(key=lambda row: (-row[0], row[1]["topic"]))
    return [item for _, item in found[:max(1, min(limit, 5))]]


def assess_unknown(message: str, user_id: str | None = None, country: str = "KE",
                   language: str = "", root: Path | None = None) -> dict[str, Any]:
    text = str(message or "").strip()[:8000]
    is_specialized = bool(_SPECIALIZED.search(text))
    available_known = known_records(root)
    memory_match = known_matches(text, root)
    corpus = _inventory_terms(_ROOT)
    query = _terms(text)
    overlap = len(query & corpus) / max(1, len(query))
    tool_found = overlap >= 0.55 and bool(query & corpus)
    library_found = bool(overlap >= 0.7 and len(query & corpus) >= 2)
    memory_found = bool(memory_match or any(
        (str(item.get("topic") or "").lower() in text.lower()) for item in available_known
    ))
    if memory_found:
        score = 0.90
    elif tool_found or library_found:
        score = 0.62
    elif is_specialized:
        score = 0.20
    else:
        # The detector is scoped to niche how-to/tool demands; ordinary conversation
        # remains with the existing provider path.
        score = 0.65
    topic_terms = [word for word in re.findall(r"[a-z0-9]{2,}", text.lower()) if word not in _STOP]
    topic = " ".join(dict.fromkeys(topic_terms[:6]))[:120] or "unclassified topic"
    unknown = bool(is_specialized and score < 0.5 and not memory_found)
    return {
        "is_unknown": unknown,
        "topic": topic,
        "topic_key": topic_slug(topic),
        "wisdom_score": round(score, 3),
        "threshold": 0.5,
        "signals": {"tool_found": tool_found, "library_found": library_found, "memory_found": memory_found},
        "country": str(country or "KE").strip().upper()[:8],
        "language": str(language or "").strip().lower()[:12],
        "next_action": "ask_user_once" if unknown else "use_existing_knowledge",
        "automatic_retries": False,
        "known_matches": memory_match,
        "user_bound": bool(user_id),
        "interpretation": "Local corpus heuristic, not proof that no answer exists elsewhere.",
    }


def _guardian_reason(text: str) -> str | None:
    lower = str(text or "").lower()
    for signal in _RESTRICTED:
        if signal in lower:
            return "Teaching content matched a configured restricted-intent indicator; nothing was stored or sent to Genesis."
    return None


def _log_blocked(root: Path, user_id: str, topic: str, reason: str) -> None:
    audit_dir = root
    audit_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": _utc_now(),
        "event": "teaching_rejected_before_storage",
        "user_id_hash": hashlib.sha256(str(user_id).encode("utf-8")).hexdigest(),
        "topic_sha256": hashlib.sha256(str(topic).encode("utf-8")).hexdigest(),
        "reason_code": "worldwide_guardian_block",
        "reason": reason[:240],
        "saved_user_steps": False,
        "genesis_called": False,
    }
    path = audit_dir / "guardian" / "blocked.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _STORE_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            os.chmod(path, 0o600)
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def save_teaching(topic: str, user_id: str, steps: list[str], country: str = "KE",
                  language: str = "", photo_hash: str = "", consent_to_share: bool = False,
                  source_request: str = "", root: Path | None = None) -> dict[str, Any]:
    topic = str(topic or "").strip()
    user_id = str(user_id or "").strip()
    if not topic or len(topic) > 240:
        raise ValueError("topic must contain 1–240 characters")
    if not user_id or len(user_id) > 200:
        raise ValueError("authenticated user identity is required")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
        raise ValueError("steps must be a list containing 1–12 items")
    clean_steps = [str(step or "").strip()[:500] for step in steps]
    clean_steps = [step for step in clean_steps if step]
    if not clean_steps or sum(len(step) for step in clean_steps) > 5000:
        raise ValueError("teaching steps must contain useful text and stay under 5,000 characters")
    if photo_hash and not _SHA_RE.fullmatch(photo_hash):
        raise ValueError("photo_hash must be a SHA-256 hex digest; image bytes are not accepted")
    screened = topic + "\n" + "\n".join(clean_steps)
    reason = _guardian_reason(screened)
    base = root or learning_root()
    if reason:
        _log_blocked(base, user_id, topic, reason)
        raise PermissionError(reason)
    from ai.worldwide_context import resolve_worldwide_context
    profile = resolve_worldwide_context(country, language)
    slug = topic_slug(topic)
    now = _utc_now()
    submission = {
        "submission_id": hashlib.sha256((user_id + "|" + slug + "|" + now).encode()).hexdigest()[:24],
        "user_id": user_id,
        "steps": clean_steps,
        "photo_hash": photo_hash or None,
        "source_request": str(source_request or "")[:800],
        "country": profile["country"],
        "language": profile["language"],
        "consent_to_share": bool(consent_to_share),
        "submitted_at": now,
        "guardian_status": "no_configured_match_existing_core_guardians_still_apply",
    }
    path = base / "unknown" / (slug + ".json")
    with _STORE_LOCK:
        record = _read_json(path) or {
            "schema_version": "revelaai.learning.v1",
            "topic": topic,
            "topic_key": slug,
            "status": "awaiting_genesis",
            "submissions": [],
            "created_at": now,
            "proposal": None,
            "tool_name": None,
        }
        submissions = record.get("submissions")
        if not isinstance(submissions, list):
            submissions = []
        if record.get("status") != "known":
            submissions.append(submission)
        record["submissions"] = submissions[-100:]
        record["updated_at"] = now
        record["country"] = profile["country"]
        record["language"] = profile["language"]
        record["consent_to_share"] = bool(consent_to_share or record.get("consent_to_share", False))
        record["private_until_reviewed"] = True
        record["status"] = record.get("status") if record.get("status") == "known" else "awaiting_genesis"
        _atomic_json(path, record)
    return {
        "topic": topic,
        "topic_key": slug,
        "status": record["status"],
        "consent_to_share": bool(consent_to_share),
        "genesis_needed": record.get("proposal") is None,
        "submission_id": submission["submission_id"],
        "country": profile["country"],
        "language": profile["language"],
    }


def attach_genesis_proposal(topic_key: str, proposal: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,71}", str(topic_key or "")):
        raise ValueError("topic key is invalid")
    base = root or learning_root()
    path = base / "unknown" / (topic_key + ".json")
    with _STORE_LOCK:
        record = _read_json(path)
        if not record:
            raise FileNotFoundError("unknown-topic record was not found")
        public = {k: proposal[k] for k in ("status", "id", "name", "title", "tool_name", "await_merge_path", "created_at") if k in proposal}
        record["proposal"] = public
        record["tool_name"] = str(proposal.get("name") or proposal.get("tool_name") or "")[:64]
        record["status"] = "await_merge"
        record["updated_at"] = _utc_now()
        _atomic_json(path, record)
        return {"topic": record.get("topic"), "topic_key": topic_key, "status": record["status"], "proposal": public}


def publish_known(topic_key: str, operator_id: str, tool_name: str, endpoint: str,
                  merge_commit: str, root: Path | None = None) -> dict[str, Any]:
    topic_key = str(topic_key or "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,71}", topic_key):
        raise ValueError("topic key is invalid")
    if not _NAME_RE.fullmatch(str(tool_name or "")):
        raise ValueError("tool_name is invalid")
    if not str(endpoint or "").startswith("/v1/") or len(endpoint) > 180:
        raise ValueError("endpoint must be a documented /v1/ path")
    if not _COMMIT_RE.fullmatch(str(merge_commit or "")):
        raise ValueError("merge_commit must be a 7–40 character Git commit SHA")
    if not str(operator_id or "").strip():
        raise ValueError("authenticated operator identity is required")
    base = root or learning_root()
    source = base / "unknown" / (topic_key + ".json")
    with _STORE_LOCK:
        record = _read_json(source)
        if not record or record.get("status") != "await_merge" or not isinstance(record.get("proposal"), dict):
            raise ValueError("only a topic with a staged Genesis proposal can be published")
        candidates = [x for x in record.get("submissions", []) if isinstance(x, dict) and x.get("consent_to_share") is True]
        if not candidates:
            raise PermissionError("no teaching submission has explicit cross-user sharing consent")
        chosen = candidates[-1]
        target = base / "known" / (topic_key + ".json")
        published = {
            "schema_version": "revelaai.learning.v1",
            "topic": str(record.get("topic") or "")[:240],
            "topic_key": topic_key,
            "status": "known",
            "country": chosen.get("country", "KE"),
            "language": chosen.get("language", "en"),
            "steps": chosen.get("steps", [])[:8],
            "keywords": sorted(_terms(str(record.get("topic") or "") + " " + " ".join(chosen.get("steps", []))))[:40],
            "consent_to_share": True,
            "tool_name": tool_name,
            "endpoint": endpoint,
            "proposal": record["proposal"],
            "human_review": {
                "published": True,
                "operator_id": str(operator_id)[:200],
                "merge_commit": merge_commit.lower(),
                "reviewed_at": _utc_now(),
                "note": "Human attested that the tool merge/release and shared-content review are complete."
            },
            "created_at": record.get("created_at"),
            "published_at": _utc_now(),
        }
        _atomic_json(target, published)
        record["status"] = "known"
        record["tool_name"] = tool_name
        record["endpoint"] = endpoint
        record["human_review"] = published["human_review"]
        record["updated_at"] = _utc_now()
        _atomic_json(source, record)
        return {"topic": published["topic"], "topic_key": topic_key, "status": "known", "tool_name": tool_name, "endpoint": endpoint, "published": True}


def list_known(root: Path | None = None) -> list[dict[str, Any]]:
    items = []
    for item in known_records(root):
        items.append({
            "topic": item.get("topic"),
            "topic_key": item.get("topic_key"),
            "country": item.get("country", "KE"),
            "language": item.get("language", "en"),
            "steps": item.get("steps", [])[:8],
            "tool_name": item.get("tool_name"),
            "endpoint": item.get("endpoint"),
            "published_at": item.get("published_at"),
            "review_status": "human_reviewed",
            "mind_proposal": item.get("mind_proposal"),
        })
    return items



def attach_improvement_proposal(topic_key: str, proposal: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,71}", str(topic_key or "")):
        raise ValueError("topic key is invalid")
    base = root or learning_root()
    path = base / "known" / (topic_key + ".json")
    with _STORE_LOCK:
        record = _read_json(path)
        if not record or record.get("status") != "known" or record.get("human_review", {}).get("published") is not True:
            raise ValueError("only human-reviewed shared knowledge can receive an improvement proposal")
        summary = {k: proposal[k] for k in ("status", "version", "tool_name", "selected_mutation", "await_merge_path", "created_at") if k in proposal}
        summary["human_approval_required"] = True
        summary["automatic_merge"] = False
        record["mind_proposal"] = summary
        record["updated_at"] = _utc_now()
        _atomic_json(path, record)
        return {"topic": record.get("topic"), "mind_proposal": summary}
