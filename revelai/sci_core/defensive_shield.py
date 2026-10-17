"""Defensive monitoring and hardening recommendations only."""
DEFENSIVE_ONLY = True
import os, re, time\nfrom importlib import metadata
from pathlib import Path
from datetime import datetime, timezone
import requests
from flask import jsonify, request
from .storage import collection
LOG_PATH=Path(os.getenv("REVELAAI_ACCESS_LOG","revelai/logs/access.log"))
ROOT=Path(__file__).resolve().parents[2]
PATTERNS=[(re.compile(r"\beval\s*\("),"high","Avoid eval; parse structured input with json or ast.literal_eval."),(re.compile(r"os\.system\s*\(\s*(?:request\.|.*request\.data)"),"critical","Avoid shell execution with request-controlled data; use fixed argument lists."),(re.compile(r"(?:api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{12,}['\"]",re.I),"high","Move credentials to environment or a managed secret store; rotate exposed credentials.")]
def scan_codebase():
    findings=[]
    base=ROOT/"revelai"
    if base.exists():
        for path in base.rglob("*.py"):
            try:
                if any(part in {".git","venv","__pycache__"} for part in path.parts): continue
                for number,line in enumerate(path.read_text(encoding="utf-8",errors="ignore").splitlines(),1):
                    for pattern,severity,fix in PATTERNS:
                        if pattern.search(line):
                            finding={"type":"vulnerable_pattern","file":str(path.relative_to(ROOT)),"line":number,"severity":severity,"fix_suggestion":fix,"timestamp":datetime.now(timezone.utc).isoformat()}
                            findings.append(finding)
                            try: collection("shields").insert_one(finding.copy())
                            except Exception: pass
            except OSError: continue
    return findings
def scan_auth_logs():
    if not LOG_PATH.exists(): return []
    now=time.time(); counts={}
    try: lines=LOG_PATH.read_text(encoding="utf-8",errors="ignore").splitlines()[-20000:]
    except OSError: return []
    for line in lines:
        if not re.search(r"(failed|invalid).{0,30}(auth|login|token)|(auth|login|token).{0,30}(failed|invalid)",line,re.I): continue
        ts=re.search(r"(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d)",line)
        if ts:
            try:
                from datetime import datetime
                if (datetime.now()-datetime.strptime(ts.group(1)[:19],"%Y-%m-%dT%H:%M:%S")).total_seconds()>300: continue
            except Exception: pass
        ip=re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b",line)
        if ip: counts[ip.group(0)]=counts.get(ip.group(0),0)+1
    found=[]
    for ip,count in counts.items():
        if count>50:
            item={"ip":ip,"type":"brute_force_attempt","count":count,"timestamp":datetime.now(timezone.utc).isoformat(),"action":"blocklist_recommendation_only","auto_blocked":False}
            found.append(item)
            try: collection("threats").insert_one(item.copy())
            except Exception: pass
    return found
def dependency_scan():
    req=ROOT/"requirements.txt"
    if not req.exists(): return []
    findings=[]
    try: packages=[x.strip() for x in req.read_text(encoding="utf-8").splitlines() if x.strip() and not x.lstrip().startswith("#")]
    except OSError: return []
    for line in packages:
        match=re.match(r"([A-Za-z0-9_.-]+)\s*(?:[<>=!~]+\s*([^;\s]+))?",line)
        if not match: continue
        name,version=match.group(1),match.group(2) or ""
        try:
            r=requests.post("https://api.osv.dev/v1/query",json={"package":{"name":name,"ecosystem":"PyPI"},"version":version} if version else {"package":{"name":name,"ecosystem":"PyPI"}},timeout=5)
            if r.ok:
                for vuln in r.json().get("vulns",[]):
                    item={"type":"dependency_cve","package":name,"version_constraint":version,"id":vuln.get("id"),"summary":vuln.get("summary","")[:500],"severity":"review","fix_suggestion":"Review OSV affected/fixed ranges and upgrade to a compatible patched release.","timestamp":datetime.now(timezone.utc).isoformat()}
                    findings.append(item)
                    try: collection("shields").insert_one(item.copy())
                    except Exception: pass
        except Exception: continue
    return findings
def firewall_recommendations():
    return {"nginx":"limit_req_zone $binary_remote_addr zone=revelai_limit:10m rate=100r/m;\nserver { if ($http_user_agent = \"\") { return 403; } location / { limit_req zone=revelai_limit burst=30 nodelay; } }","ufw":"# Review and adapt before applying; preserve SSH/admin access.\n# ufw limit 443/tcp\n# ufw limit 80/tcp","note":"Configuration text only; nothing is applied automatically."}
def run_scan():
    vulns=scan_codebase(); threats=scan_auth_logs(); cves=dependency_scan()
    try: collection("shields").insert_one({"type":"scan_summary","timestamp":datetime.now(timezone.utc).isoformat(),"vulnerabilities":len(vulns),"cves":len(cves),"threats":len(threats)})
    except Exception: pass
    return {"vulnerabilities":vulns,"threats":threats,"cves":cves,"firewall_recommendations":firewall_recommendations(),"status":"shield_active","defensive_only":True}
def register_routes(bp):
    @bp.get("/shield/status")
    def status():
        try:
            db_counts={}
            for name in ("threats","shields","disasters","research"):
                db_counts[name]=collection(name).count_documents({})
            return jsonify({"status":"shield_active","defensive_only":True,"counts":db_counts,"firewall_recommendations":firewall_recommendations()})
        except Exception: return jsonify({"status":"degraded","error":"MongoDB shield status unavailable"}),503
    @bp.post("/shield/scan")
    def scan():
        try: return jsonify(run_scan())
        except Exception: return jsonify({"status":"degraded","error":"Scan incomplete; inspect service logs and MongoDB configuration"}),503
