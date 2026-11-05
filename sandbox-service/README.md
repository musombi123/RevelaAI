# RevelaAI isolated Python execution

This is a separate execution service. Do not run untrusted Python in the RevelaAI web process or in the API container.

## Security boundary

The controller accepts only HMAC-authenticated calls from RevelaAI. It launches a fixed, prebuilt worker image with the gVisor Docker runtime. Each worker has no network, a read-only root filesystem, no Linux capabilities, no-new-privileges, a non-root UID, PID/CPU/memory limits, and temporary input/output mounts only. The worker receives no application environment variables or secrets. It is destroyed after each request.

The Docker socket is a host-administration capability. Run this controller only on a dedicated sandbox VM/host, never on the same machine that hosts the RevelaAI API, database, or secrets. Expose it only on a private network. The API verifies HMAC before it can submit jobs.

## Host prerequisites

- Dedicated Linux VM with Docker Engine.
- Install and configure gVisor/runsc as a Docker runtime; verify `docker info` lists a runtime named `runsc`.
- Minimum practical host size for the complete science image: 4 vCPU, 8 GB RAM, and 25 GB free disk. 16 GB RAM is preferable for Qiskit/QuTiP/Polars workloads and concurrent jobs.
- Do not place production credentials, databases, or source repositories on this host.

## Build

From this directory:

1. Build the fixed worker image: `docker build -f Dockerfile.runner -t revelaai-python-sandbox:phase1 .`
2. Create a host jobs directory, for example `/srv/revelaai-sandbox-jobs`.
3. Run the controller with `SANDBOX_SHARED_SECRET`, `SANDBOX_HOST_JOBS_DIR=/srv/revelaai-sandbox-jobs`, `SANDBOX_CONTAINER_JOBS_DIR=/jobs`, `SANDBOX_DOCKER_RUNTIME=runsc`, and `SANDBOX_RUNNER_IMAGE=revelaai-python-sandbox:phase1`.
4. Mount that same host jobs directory at `/jobs` in the controller, and mount the Docker socket. Keep the controller listener private.

The controller needs Docker socket access to create disposable containers; that access is why it belongs on a separate, dedicated host. The worker itself never receives the socket or any host directory except its temporary job folders.

## RevelaAI gateway settings

Configure on the RevelaAI server only:

- `SANDBOX_SERVICE_URL`: private HTTPS/service origin of this controller.
- `SANDBOX_SHARED_SECRET`: same randomly generated HMAC key on both services.

The sandbox endpoint remains unavailable until the controller is deployed and the HMAC key is configured. RevelaAI fails closed and does not execute code locally.

## Important limitation

A Docker container without gVisor is not considered an accepted production isolation runtime by this service. The controller checks for the configured runtime and refuses execution when it is missing. The current runner is a general purpose research/computation environment, not a guarantee against every unknown kernel or container-runtime vulnerability. Keep it patched and isolated.
