# Five-minute demo and interview preparation

1. Ask “How can search continue while a new index is being built?” Show the citation and both retrieval ranks. Explain that the default output quotes evidence and uses no LLM.
2. Compare three modes. Separate a single-query result from aggregate relevance evaluation. Open evaluation-local.json and explain why BM25 beat hybrid here rather than presenting fusion as automatically better.
3. Switch to Payments and ask about ledger retention. Explain that credentials determine tenant scope; the request body cannot. Switch back to Platform and show that it cannot retrieve the payments-only policy.
4. Open Index workspace, queue the Quasar example, and observe the published version. Search for Quasar. Explain the durable job, background full rebuild, old snapshot, transaction, cache invalidation, and swap.
5. Choose Local LLM / Ollama. Ask a supported question and inspect its references. Explain unknown-citation rejection, abstention limitations, and why a citation is not proof of factual grounding.
6. Open benchmark-local.json. Quote the actual cold, eight-worker p95 separately from the warm-cache result. The in-process benchmark excludes HTTP and LLM latency. The local-model report measures those model calls separately.

Prepare to answer:

- Why exact vectors and SQLite here? What would trigger moving to ANN and a shared query service?
- What does TF-IDF/LSA learn? What happens to an unseen token, an empty document, or a changed model dimension?
- What happens if a process dies during build, before commit, or between commit and pointer publication?
- Why must tenant and model version be in the cache key?
- What does this relevance set fail to measure? How would independent human labeling, difficult paraphrases, and an unseen corpus change the evaluation?
- What requires redesign before multiple Cloud Run replicas? What would be stored in a database versus object storage?

A concise accurate project pitch, after you can demonstrate and explain it:

“Atlas is a local incident-knowledge retrieval service. It has credential-scoped tenants, a durable indexing queue, atomic model-version publication, and BM25/latent-vector retrieval with rank provenance. I evaluate relevance and latency separately, and the optional local language model must return valid retrieved citations. The current implementation is a single-node lab; scaling the shared index lifecycle is the next design problem.”

Use this as a study guide; customize the service and know its failure cases before discussing design ownership. The repository contains present-day implementation and measured synthetic tests, not historical employer work.
