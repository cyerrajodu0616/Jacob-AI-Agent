"""Validation suite for the Jacob RAG agent (built 2026-08-22).

Two tiers:
  retrieval — does the RAG pipeline return the right section + weak flag?
              (needs Postgres + the embedder; no Claude model, no cost)
  agent     — does Jacob answer/refuse/deflect correctly on real questions?
              (needs the full stack incl. the model; consumes subscription usage)

Run:  python -m evals.run retrieval | agent | all
"""
