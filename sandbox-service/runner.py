"""Runs only inside a non-root gVisor worker container."""
import json,sys,traceback
from pathlib import Path
source=Path(sys.argv[1]); output=Path("/output")
result={"status":"ok","files":[]}
try:
    namespace={"__name__":"__main__","__file__":str(source)}
    exec(compile(source.read_text(encoding="utf-8"),str(source),"exec"),namespace,namespace)
    result["status"]="completed"
except BaseException as exc:
    result={"status":"error","error_type":type(exc).__name__,"message":str(exc)[:1000],"traceback":traceback.format_exc(limit=8)[-4000:]}
for path in output.iterdir():
    if path.is_file() and path.name!="result.json": result["files"].append({"name":path.name,"size_bytes":path.stat().st_size})
(output/"result.json").write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8")
