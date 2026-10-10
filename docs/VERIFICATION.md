# Verification

Measured on October 10, 2026. Reports alongside this file preserve the observed results.

- 30 unit and HTTP integration tests passed (1.575 seconds).
- Live HTTP smoke passed: authentication, tenant scope, cache hit, queued indexing, atomic publication, and cited quotation.
- Three real local Qwen2.5:1.5b calls passed citation-ID checks in 4.579, 5.493, and 9.297 seconds. This checks wiring and references, not general factuality or injection resistance.

## Retrieval regression set

36 authored questions over original synthetic runbooks, excluded from index training. This is not an independent benchmark.

| Method | Recall@5 | MRR@5 |
| --- | ---: | ---: |
| SQLite BM25 | 1.0000 | 0.9583 |
| Corpus-trained LSA | 0.9444 | 0.9097 |
| Reciprocal rank fusion | 0.9722 | 0.9375 |

BM25 performed best on this set. Three unanswerable questions abstained. Hybrid retrieval is exposed as a design to evaluate, with no claim of universal improvement.

## Local performance

474 synthetic documents/chunks, 48 latent dimensions, 600 queries, eight workers. In-process retrieval excludes HTTP, authentication, rate limits, and generation.

| Path | Queries/sec | p50 ms | p95 ms | p99 ms |
| --- | ---: | ---: | ---: | ---: |
| Cache disabled | 627.03 | 12.374 | 18.661 | 22.453 |
| Warm cache | 23459.15 | 0.032 | 0.587 | 2.932 |

Zero empty results; warm cache had 600 hits. Nine queued rebuilds took 0.289 seconds. Replicated synthetic text and small exact scans do not establish production capacity.

## Reproduce

See README for tests, evaluation, benchmark, Docker, and optional local-model checks. GitHub Actions also runs the tests and a Docker HTTP smoke check; local Docker was unavailable during development. Check the repository Actions page for its recorded outcome.
