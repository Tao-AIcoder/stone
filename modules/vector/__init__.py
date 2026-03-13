"""
modules/vector package - Vector store / embedding search (Phase 3).

TODO: Phase 3 - implement vector similarity search for long-term memory.

Planned implementations:
- ChromaDB (local, recommended for single-node)
- Qdrant (self-hosted, for production scale)
- LanceDB (embedded, no server required)

Key patterns:
- Embedding model: bge-m3 (local via Ollama) or text-embedding-3-small (cloud)
- Collections: stone_memory_{user_id}, stone_notes_{user_id}
- Metadata filtering: category, created_at range, tags
- Hybrid search: dense + BM25 sparse for better recall
"""

# Phase 3 - no exports yet
