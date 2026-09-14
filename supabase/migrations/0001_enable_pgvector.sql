-- Phase 1: enable pgvector now so Phase 9 (repository-level RAG) doesn't hit
-- a migration surprise later. No product tables exist yet — those start in
-- Phase 2 (installations, repositories, pull_requests, review_runs,
-- findings) and Phase 9 (repository_chunks, embeddings, import_graph_edges).

create extension if not exists vector;
