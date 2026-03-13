# Vector Memory Architecture Plan

This document describes the vector-backed memory retrieval roadmap. Each phase builds on the previous so the agent can query only the most relevant memory snippets.

## Phase 1 — Chunking foundation (completed)
- Chunk workspace memory files (`AGENT_HANDOFF.md`, `NEXT_STEPS.md`, `README.md`, `docs/*.md`) into readable pieces via `tools/index_memory.py`.
- Persist chunk metadata (`source_file`, `chunk_index`, `text`) in `memory/index_chunks.jsonl` for inspection.
- Provide `tradebot/memory_store.py` as the shared abstraction for indexing (`index_chunks`) and querying (`query_chunks`).
- Implement `tools/query_memory.py` as a placeholder keyword search to verify the pipeline and keep the interface stable for future upgrades.

## Phase 2 — Embeddings + Qdrant ingestion (completed)
- Add `sentence-transformers/all-MiniLM-L6-v2` embeddings via `SentenceTransformer` and store vectors in a local Qdrant instance (`qdrant/qdrant` on port 6333).
- Update `tradebot/memory_store.py` to:
  - Lazily load the embedding model and chunk vectors in batches.
  - Recreate the `memory_chunks` Qdrant collection (cosine distance, 384d) before each index run and upsert vectors with metadata (`source_file`, `chunk_index`, `text`).
  - Perform nearest-neighbor searches by embedding the query and hitting Qdrant via `client.query_points`, falling back to keyword lookup when the vector backend is unavailable.
- `tools/index_memory.py` now leverages the same `index_chunks` helper, so running it refreshes both the local JSONL archive and the Qdrant collection.
- `tools/query_memory.py` calls `memory_store.query_chunks` to fetch the top 5 semantically similar chunks, so you can verify retrieval
environments before rerouting prompts.

## Phase 3 — Prompt injection & retrieval caching (completed)
- `tools/prompt_builder.py` now wraps `memory_store.query_chunks(...)`, embeds each user query, and injects just the top few chunks (with source annotations) into the prompt instead of dumping entire files.
- Retrieval caching is handled automatically via `state/memory_retrieval_cache.json`, so repeated queries reuse cached chunk lists without hitting Qdrant until the TTL expires.
- Every prompt build is logged to `state/memory_usage_log.jsonl`, keeping an audit trail of which chunk IDs were used and whether the cache satisfied the request.
- `tools/build_agent_prompt.py` demonstrates the integration by printing the final prompt and the retrieved chunk references for debugging or downstream reuse.
- Future iterations can expand the cache invalidation logic (e.g., hash comparison vs. `index_chunks.jsonl`) and filter retrieval results by metadata tags.

With Phase 3 in place, the prompt builder only sees relevant snippets, keeping token usage low while still giving the agent the memory it needs.
