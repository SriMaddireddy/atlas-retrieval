# Technical status

## Completion audit (2026-11-11 UTC)

The bounded local demonstration scope is complete. The final audit and hosted
CI passed on implementation/test commit `8dd6e312d253fff29583b41e708e021cf22f04a9`.
The next active project is `ad-impression-telemetry`.
See [completion evidence](COMPLETION.md).


## Search during queue admission (2026-11-10 UTC)

AI-assisted implementation and verification by ChatGPT Work. Queue admission
and shutdown now share a separate lock. A slow queue insert no longer holds the
lock search needs to capture the current snapshot. Publication still holds its
own lock across the database commit and snapshot swap.

The concurrency regression pauses queue admission and checks that search returns
the current version before the insert resumes. It times out on the parent
commit and passes with the fix. All 36 unit and HTTP integration tests passed
on Linux with Python 3.12.14 and NumPy 2.3.5. The 36-query synthetic retrieval
evaluation matched the existing recall and MRR baselines, with 3/3 abstentions.
This test isolates lock behavior and does not measure production latency.
Retained-version storage and queue overload remain open review items.

## Reject work without a live indexer (2026-11-06 UTC)

AI-assisted implementation and verification by ChatGPT Work. Job admission now
checks worker liveness and the shutdown signal under the publication lock;
shutdown sets that signal under the same lock. A closed or already-dead worker
cannot silently accept a durable job that it will never process. The HTTP layer
maps this explicit unavailability to 503. Jobs accepted before shutdown remain
durable and retain existing restart recovery.

Two regression cases verify closed-service and dead-worker rejection without
new persisted jobs. All 35 unit/HTTP tests and the 36-query retrieval evaluation
pass in the cloud runtime. Prior commit d88f0bb hosted CI passed. This change's
hosted CI must verify the pinned environment and Docker path. This is an
admission-time check, not a guarantee against a worker failing afterward.

## Transient queue-claim contention

AI-assisted implementation and cloud verification by ChatGPT Work on
2026-11-05 UTC. This is a catch-up development run with the real current date.

The indexing worker now retries SQLite BUSY/LOCKED claim errors, including
extended codes, after an interruptible 100 ms delay. Previously a transient
claim error terminated the worker and left accepted jobs pending. The retry
does not re-enqueue jobs or change publication semantics.

Evidence from Linux, Python 3.12.14 and NumPy 2.3.5:

- Busy and extended locked error regression cases fail on the parent code
  (worker termination and pending-job timeout), then pass with the fix.
- A separate regression verifies unrelated database errors are not retried.
- All 33 unit/HTTP integration tests pass (1.716 seconds).
- Live source-server HTTP smoke passes.
- The 36-query retrieval evaluation retains the recorded baseline metrics;
  all three unknown queries abstain. No relevance improvement is claimed.
- Hosted CI for this commit must verify pinned dependencies and Docker.

Limitations: persistent lock contention can delay the queue indefinitely;
errors after claiming a job retain existing failed-job behavior. This does
not provide general database repair or distributed-writer support.

## Writer ownership during shutdown

AI-assisted change by ChatGPT Work, verified in a managed Linux cloud runtime
on 2026-11-05 UTC (Python 3.12.14, NumPy 2.3.5).

Previously `Service.close()` released the process lock after its 20-second join
deadline even when the indexing thread remained alive. A second service could
then acquire ownership while the old worker could still publish a snapshot.
Shutdown now raises an explicit error and retains the lock until the worker
exits. Call `close()` again after indexing finishes to release ownership.

Evidence:

- New regression fails against the original implementation and passes with the fix.
- All 31 unit and HTTP integration tests pass in the cloud (1.357 seconds).
- Live source-server HTTP smoke passes: auth, tenant isolation, caching, durable
  indexing, publication, and cited extractive answers.
- All 36 retrieval regression queries retain the recorded baseline results:
  BM25 recall@5 1.0000 / MRR@5 0.9583; LSA 0.9444 / 0.9097;
  hybrid 0.9722 / 0.9375. All three unknown queries abstain.
- Runtime NumPy differs from the pinned requirements. Hosted CI must verify the
  pinned environment and Docker path; no new model inference was performed.

## Earlier completion checklist

The queue, recovery and retained-storage checks above are superseded by the
completion audit linked below. Verify its hosted CI before transition.
Existing retrieval labels were authored with the synthetic corpus and do not
establish independent relevance or production capacity.

After Atlas meets its documented scope and all completion checks, assess
`ad-impression-telemetry`, then review `autonomous-crm-simulator` for backend
coverage. New repositories require a verified repository-creation capability.
No interview preparation belongs in public project records.
