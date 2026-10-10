# API contract

All `/v1/*` routes require `Authorization: Bearer <team key>`. Unknown credentials return 401; cross-team job IDs return 404. No request field can select a different tenant. JSON errors use `{ "error": "message" }`.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/healthz` | Unauthenticated process readiness after index load |
| GET | `/v1/stats` | Active version, counts, model dimensions, recent server latency, cache metrics |
| GET | `/v1/documents` | Team source documents |
| POST | `/v1/documents` | Validate the complete batch then queue it; 202 + job_id |
| DELETE | `/v1/documents/{id}` | Queue idempotent removal; 202 + job_id |
| GET | `/v1/jobs/{id}` | Team-scoped status and resulting version |
| POST | `/v1/search` | Ranked passages with scores, branch ranks, captured version and server time |
| POST | `/v1/answer` | Quoted or local-generated answer with citations and its retrieval trace |

Search JSON: `{"query":"Kafka lag", "mode":"hybrid", "k":5}`. Modes: lexical/dense/hybrid; k 1–20; query 1–500 chars. Scores are not confidence probabilities.

Answer JSON: `{"query":"Kafka lag", "mode":"hybrid", "provider":"extractive"}`. Providers: extractive/ollama. The generator is called only for explicit ollama requests with sufficient evidence. If no evidence meets the heuristic guard, the API returns abstained=true with no citations.

Upsert JSON: `{"documents":[{"id":"runbook-1","title":"Recovery","body":"A runbook with at least ten characters.","source":"local://runbook-1"}]}`. IDs match `[a-zA-Z0-9_-]{1,80}`; duplicate IDs in a batch fail validation. Source must be a local:// or https:// label and is never fetched. Changes become visible after job completion, not at HTTP 202. Tenant capacity failures mark the job failed and retain the old version.

Errors: 400 invalid schema, 401 bad credentials, 403 mutation disabled, 404 endpoint/job absent, 413 body limit, 422 rejected generation/citation format, 429 rate/queue/generation capacity, 503 unconfigured/unavailable generation or HTTP handler capacity. A health check does not establish model availability. `generator_ready` indicates configuration, not a live model health probe.
