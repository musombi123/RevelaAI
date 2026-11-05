# RevelaAI isolated sandbox service

**Do not deploy this service on the same host as the web API with a privileged Docker socket.**
Use a dedicated worker host with rootless Docker and gVisor `runsc` installed. The API container needs access only to that host's restricted Docker endpoint; do not mount the host filesystem or app secrets into workers.

## Required deployment properties
- Dedicated VM/host; rootless Docker daemon; gVisor runtime registered as `runsc`.
- Firewall: only RevelaAI API may reach port 8080; workers have no network.
- API signing secret shared with RevelaAI; at least 32 random bytes.
- Build worker image from `worker.Dockerfile` as `revelaai-python-worker:phase1`.
- API container: non-root, no public Docker socket, no cloud credentials; expose HTTPS behind an authenticated private service gateway.
- Worker: `--network=none`, read-only root, no capabilities, no-new-privileges, non-root UID, CPU 1, RAM 768 MiB, 64 PIDs, 30-second job limit, ephemeral input/output only.
- For stronger isolation at scale, replace the rootless Docker worker executor with Firecracker microVMs.

## Environment
- `SANDBOX_SHARED_SECRET`: request HMAC key.
- `SANDBOX_RUNTIME=runsc`: gVisor runtime name.
- `SANDBOX_WORKER_IMAGE`: worker image identifier.

## API integration
Set `SANDBOX_SERVICE_URL` and `SANDBOX_SHARED_SECRET` on the RevelaAI web service. The app does not execute user code locally. It returns an explicit unavailable response until the isolated service is provisioned.

## File contract
Inputs use `files[].{name,content_base64}`; outputs are base64 files. The web API must validate output type, size and ownership before moving outputs into private app storage. Do not add network access to the worker.
