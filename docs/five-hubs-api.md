# Free Five-Hub API

The existing production entrypoint is Flask/Python in `app.py`. The new blueprint is registered there; no parallel Node server is introduced.

## Routes

- `GET /api/revelaai/hubs/` — list the five supported hub IDs.
- `POST /api/revelaai/hubs/respond` — deterministic response from text and optional device vision measurements.

Example request:

```json
{
  "message": "What do you see?",
  "hub": "general",
  "sessionId": "a-random-chat-session-id",
  "visionDescription": "Detected labels: book (91% confidence). Brightness: 42/255 (dark). Contour count: 7. Text detected: ROMANS 8:28.",
  "vision": {
    "objects": [{"class": "book", "score": 0.91}],
    "brightness": 42,
    "contourCount": 7,
    "text": "ROMANS 8:28"
  }
}
```

The response includes `hub`, `reply`, `engine`, `paidModel: false`, and `visionUsed`. It does not accept image bytes or invoke a model provider.

## Hubs

`mkulima`, `biashara`, `elimu`, `mahubiri`, `general`.

## Memory and cache

The engine uses bounded in-process response caching and stores short, bounded conversation notes in `data/hub_memory.json`. The session ID is preferred as the memory scope; clients should send an unguessable random session identifier. Local JSON persistence requires a writable persistent disk and is not a multi-instance database.

## Tests

Run from the repository root:

```powershell
python -m unittest tests.test_hub_personas
```

The endpoint is rule-based. It is not an LLM, does not guarantee correctness, and must not infer object identity from brightness or contours alone.
