"""Runs only inside a non-root gVisor worker container."""
import json,sys,traceback,resource
from pathlib import Path
# Bound individual writes, file handles, processes and address space.
resource.setrlimit(resource.RLIMIT_FSIZE,(5*1024*1024,5*1024*1024))
resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
try: resource.setrlimit(resource.RLIMIT_NPROC,(32,32))
except (ValueError,AttributeError): pass
try: resource.setrlimit(resource.RLIMIT_AS,(640*1024*1024,640*1024*1024))
except (ValueError,AttributeError): pass
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
