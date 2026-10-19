# RVX Mesh — Encrypted Python Adapters

The Python client in mesh/rvx_mesh.py uses explicitly configured routes in REVELA_RVX_ROUTES. Public tool invocations are sent as authenticated AES-GCM RVXP1 envelopes; a non-RVX response, missing route, stale hour/day, duplicate message ID, or authentication failure fails closed.

Python adapter authors can use mesh.receiver.create_rvx_receiver_router:

    from fastapi import FastAPI
    from mesh.receiver import create_rvx_receiver_router

    app = FastAPI()
    app.include_router(create_rvx_receiver_router({
        "tool.example": my_validated_handler,
        "one.genesis": my_genesis_handler,
    }))

Keep the receiver private behind service-to-service networking, configure an independently managed REVELA_RVX_MESH_SECRET on each configured peer, and give the caller an HTTPS URL. Handlers must validate the input schema and re-check operation-specific authorization. Message IDs are deduplicated in-process for each hourly window; distributed/multi-worker deployments need a shared replay store or sticky single-worker routing to enforce replay protection across workers.

The existing Core-Zero, Core-One, and Core-Two implementations are Go services and do not yet implement RVXP1 receivers. Do not configure this Python sender to call those cores until equivalent protocol support, peer authentication, and acceptance tests are deployed on the receiver side.
