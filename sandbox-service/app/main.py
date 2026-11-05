"""Private Docker/gVisor execution controller. The worker container has no network."""
from __future__ import annotations
import base64, hashlib, hmac, json, os, re, shutil, tempfile, time, uuid
from pathlib import Path
from typing import Any
import docker
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from threading import BoundedSemaphore

app=FastAPI(title="RevelaAI isolated execution service",docs_url=None,redoc_url=None)
JOBS=Path(os.getenv("SANDBOX_CONTAINER_JOBS_DIR","/jobs")).resolve()
HOST_JOBS=Path(os.getenv("SANDBOX_HOST_JOBS_DIR","/srv/revelaai-sandbox-jobs")).resolve()
SECRET=os.getenv("SANDBOX_SHARED_SECRET","")
IMAGE=os.getenv("SANDBOX_RUNNER_IMAGE","revelaai-python-sandbox:phase1")
RUNTIME=os.getenv("SANDBOX_DOCKER_RUNTIME","runsc")
MAX_INPUT=8*1024*1024
MAX_OUTPUT=12*1024*1024
MAX_CONCURRENT_JOBS=max(1,min(int(os.getenv("SANDBOX_MAX_CONCURRENT_JOBS","2")),4))
_JOB_SLOTS=BoundedSemaphore(MAX_CONCURRENT_JOBS)

class ExecuteInput(BaseModel):
    code:str=Field(min_length=1,max_length=30000)
    files:list[dict[str,str]]=Field(default_factory=list,max_length=10)
    timeout_seconds:int=Field(default=10,ge=1,le=30)

@app.get("/health")
def health():
    if len(SECRET.encode())<32: return {"status":"not_configured","runtime":RUNTIME}
    try:
        client=docker.from_env()
        runtimes=(client.info() or {}).get("Runtimes",{})
        return {"status":"ready" if RUNTIME in runtimes else "runtime_missing","runtime":RUNTIME,"runner_image_present":any(x.tags and IMAGE in x.tags for x in client.images.list())}
    except Exception:
        return {"status":"unavailable","runtime":RUNTIME}

async def _read_body(request:Request)->tuple[bytes,dict[str,Any]]:
    raw=await request.body()
    if not raw or len(raw)>MAX_INPUT: raise HTTPException(413,"Job input exceeds the allowed size.")
    expected=hmac.new(SECRET.encode(),raw,hashlib.sha256).hexdigest()
    supplied=request.headers.get("X-Revela-Sandbox-Signature","")
    if len(SECRET.encode())<32 or not hmac.compare_digest(expected,supplied):
        raise HTTPException(401,"Invalid service authentication.")
    try: payload=json.loads(raw)
    except ValueError: raise HTTPException(400,"Invalid JSON job.") from None
    if not isinstance(payload,dict): raise HTTPException(400,"A JSON object is required.")
    return raw,payload

@app.post("/v1/execute")
async def execute(request:Request):
    _raw,payload=await _read_body(request)
    try: body=ExecuteInput.model_validate(payload)
    except Exception: raise HTTPException(422,"Invalid job input.") from None
    try:
        client=docker.from_env()
        runtimes=(client.info() or {}).get("Runtimes",{})
        if RUNTIME not in runtimes:
            raise HTTPException(503,"Required gVisor runtime is unavailable; execution is disabled.")
        if not any(x.tags and IMAGE in x.tags for x in client.images.list()):
            raise HTTPException(503,"The approved sandbox runner image has not been installed.")
    except HTTPException: raise
    except Exception: raise HTTPException(503,"Isolated execution host is unavailable.") from None
    if not _JOB_SLOTS.acquire(blocking=False):
        raise HTTPException(503,"Sandbox is busy. Retry after an active job finishes.")
    job=uuid.uuid4().hex
    # The controller writes through its /jobs bind mount. Docker receives the
    # corresponding host path because volume sources are resolved by dockerd.
    host_root=HOST_JOBS/job
    container_root=JOBS/job
    input_dir=container_root/"input"; output_dir=container_root/"output"
    host_input=host_root/"input"; host_output=host_root/"output"
    try:
        input_dir.mkdir(parents=True,exist_ok=False); output_dir.mkdir(parents=True,exist_ok=True)
        (input_dir/"main.py").write_text(body.code,encoding="utf-8")
        total=len(body.code.encode("utf-8"))
        for item in body.files:
            name=str(item.get("name") or "")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}",name) or name in {"main.py",".",".."}:
                raise HTTPException(400,"Invalid uploaded filename.")
            try: content=base64.b64decode(item.get("content_base64",""),validate=True)
            except Exception: raise HTTPException(400,"Invalid base64 file payload.") from None
            total+=len(content)
            if total>MAX_INPUT: raise HTTPException(413,"Job input exceeds the allowed size.")
            (input_dir/name).write_bytes(content)
        for path in input_dir.iterdir(): path.chmod(0o444)
        output_dir.chmod(0o777)
        timeout=body.timeout_seconds
        container=client.containers.run(
            IMAGE,
            command=["python","-I","-B","/opt/revelaai/runner.py","/input/main.py"],
            detach=True, auto_remove=False, runtime=RUNTIME, network_mode="none",
            read_only=True, user="65532:65532", cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"], mem_limit="768m",
            memswap_limit="768m", nano_cpus=1_000_000_000, pids_limit=64,
            tmpfs={"/tmp":"rw,noexec,nosuid,nodev,size=64m"},
            volumes={
                str(host_input):{"bind":"/input","mode":"ro"},
                str(host_output):{"bind":"/output","mode":"rw"},
            },
            environment={"HOME":"/tmp","TMPDIR":"/tmp","PYTHONDONTWRITEBYTECODE":"1"},
            labels={"revelaai.managed":"true","revelaai.job":job},
            network_disabled=True,
        )
        try:
            status=container.wait(timeout=timeout)
        except Exception:
            container.kill()
            raise HTTPException(408,"Execution exceeded its time limit.") from None
        logs=(container.logs(stdout=True,stderr=True) or b"")[:200_000].decode("utf-8",errors="replace")
        exit_code=int(status.get("StatusCode",1))
        result_file=output_dir/"result.json"
        result={}
        if result_file.is_file() and not result_file.is_symlink():
            try: result=json.loads(result_file.read_text(encoding="utf-8"))
            except ValueError: result={"status":"invalid_result"}
        exported=[]
        output_total=0
        for path in output_dir.iterdir():
            if path.is_symlink() or not path.is_file() or path.name=="result.json": continue
            size=path.stat().st_size; output_total+=size
            if output_total>MAX_OUTPUT: break
            exported.append({"name":path.name,"size_bytes":size,"content_base64":base64.b64encode(path.read_bytes()).decode("ascii")})
        return {"job_id":job,"status":"completed" if exit_code==0 else "failed","exit_code":exit_code,"stdout":logs,"result":result,"files":exported,"network":"disabled","runtime":RUNTIME}
    except HTTPException: raise
    except Exception:
        raise HTTPException(503,"The isolated execution job failed; no host-level execution was attempted.") from None
    finally:
        try:
            for container_obj in client.containers.list(all=True,filters={"label":f"revelaai.job={job}"}):
                try: container_obj.remove(force=True)
                except Exception: pass
        except Exception: pass
        shutil.rmtree(container_root,ignore_errors=True)
        _JOB_SLOTS.release()
