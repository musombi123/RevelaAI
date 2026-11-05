"""Isolated one-job Python runner. Deploy only on a dedicated gVisor-enabled host."""
from __future__ import annotations
import hashlib,hmac,json,os,re,secrets,subprocess,tempfile,time,uuid
from pathlib import Path
from fastapi import FastAPI,Request,HTTPException
from pydantic import BaseModel,Field

app=FastAPI(title="RevelaAI Isolated Sandbox",docs_url=None,redoc_url=None)
SHARED=os.getenv("SANDBOX_SHARED_SECRET","").encode()
RUNTIME=os.getenv("SANDBOX_RUNTIME","runsc")
IMAGE=os.getenv("SANDBOX_WORKER_IMAGE","revelaai-python-worker:phase1")
MAX_CODE=30000
MAX_FILES=10
MAX_FILE_BYTES=5*1024*1024
ALLOWED={"csv","json","txt","xlsx","docx","pptx","pdf","png","jpg","jpeg"}

class Job(BaseModel):
 code:str=Field(min_length=1,max_length=MAX_CODE)
 files:list[dict[str,str]]=Field(default_factory=list,max_length=MAX_FILES)
 timeout_seconds:int=Field(default=10,ge=1,le=30)

def _verify(raw:bytes,signature:str):
 if len(SHARED)<32: raise HTTPException(503,"Sandbox signing is not configured.")
 expected=hmac.new(SHARED,raw,hashlib.sha256).hexdigest()
 if not hmac.compare_digest(expected,signature or ""): raise HTTPException(401,"Invalid service signature.")

def _run(job:Job):
 job_id=uuid.uuid4().hex
 with tempfile.TemporaryDirectory(prefix="revela-job-") as temp:
  root=Path(temp); (root/"input").mkdir(); (root/"output").mkdir()
  manifest=[]
  for item in job.files:
   name=str(item.get("name") or "")
   suffix=Path(name).suffix.lower().lstrip(".")
   if suffix not in ALLOWED: raise HTTPException(415,"Unsupported input file type.")
   try: data=__import__("base64").b64decode(item.get("content_base64",""),validate=True)
   except Exception: raise HTTPException(400,"Invalid file encoding.")
   if len(data)>MAX_FILE_BYTES: raise HTTPException(413,"Input file exceeds the per-file limit.")
   safe=re.sub(r"[^A-Za-z0-9._-]","_",Path(name).name)[:100]
   if not safe or safe in {".",".."}: raise HTTPException(400,"Invalid file name.")
   (root/"input"/safe).write_bytes(data)
   manifest.append({"name":safe,"size":len(data),"sha256":hashlib.sha256(data).hexdigest()})
  script=root/"job.py"; script.write_text(job.code,encoding="utf-8")
  command=[
   "docker","run","--rm","--runtime="+RUNTIME,"--network=none","--read-only",
   "--cpus=1","--memory=768m","--memory-swap=768m","--pids-limit=64",
   "--cap-drop=ALL","--security-opt=no-new-privileges",
   "--user=65532:65532","--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
   "--mount",f"type=bind,src={root}/job.py,dst=/job.py,readonly",
   "--mount",f"type=bind,src={root}/input,dst=/input,readonly",
   "--mount",f"type=bind,src={root}/output,dst=/output",
   "--env","PYTHONDONTWRITEBYTECODE=1","--env","PYTHONUNBUFFERED=1",
   IMAGE,"python","-I","/job.py"
  ]
  started=time.monotonic()
  try:
   result=subprocess.run(command,capture_output=True,text=True,timeout=job.timeout_seconds+5,check=False,env={"PATH":"/usr/bin:/bin","HOME":"/tmp"})
  except subprocess.TimeoutExpired:
   raise HTTPException(408,"Execution time limit exceeded.")
  if result.returncode!=0:
   return {"job_id":job_id,"status":"error","exit_code":result.returncode,"stderr":result.stderr[-8000:],"stdout":result.stdout[-4000:],"duration_ms":round((time.monotonic()-started)*1000)}
  outputs=[]
  for path in sorted((root/"output").iterdir()):
   if not path.is_file() or path.is_symlink(): continue
   data=path.read_bytes()
   if len(data)>10*1024*1024: continue
   outputs.append({"name":path.name,"size":len(data),"content_base64":__import__("base64").b64encode(data).decode()})
  return {"job_id":job_id,"status":"success","stdout":result.stdout[-8000:],"stderr":result.stderr[-4000:],"duration_ms":round((time.monotonic()-started)*1000),"input_files":manifest,"outputs":outputs}

@app.get("/health")
def health(): return {"status":"ok","isolation_runtime":RUNTIME,"network":"disabled_per_job"}

@app.post("/v1/execute")
async def execute(request:Request):
 raw=await request.body()
 if len(raw)>40*1024*1024: raise HTTPException(413,"Job payload too large.")
 _verify(raw,request.headers.get("X-Revela-Sandbox-Signature",""))
 try: job=Job.model_validate_json(raw)
 except Exception: raise HTTPException(422,"Invalid sandbox job.")
 return _run(job)
