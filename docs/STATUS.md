# Technical status

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

## Remaining completion evidence

Atlas is still the active project. Verify CI for this change before declaring
it complete. Review queue overload, shutdown recovery and retained-version
storage bounds, and record reproducible evidence for any further changes.
Existing retrieval labels were authored with the synthetic corpus and do not
establish independent relevance or production capacity.

After Atlas meets its documented scope and all completion checks, assess
`ad-impression-telemetry`, then review `autonomous-crm-simulator` for backend
coverage. New repositories require a verified repository-creation capability.
No interview preparation belongs in public project records.
