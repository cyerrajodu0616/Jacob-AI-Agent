"""Central configuration. Values come from the environment, with .env as the
local override file (gitignored — the ngrok URL rotates, credentials never
belong in code).
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_dotenv(path: Path = HERE / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

# ── product / knowledge ──────────────────────────────────────────────────────
PRODUCT = os.getenv("JACOB_PRODUCT", "511801")
# Agent-/customer-facing names. The control JSON's `productName` ("Avant …") is
# the carrier's internal name and must NOT be shown to agents — use these.
PRODUCT_NAME = os.getenv("JACOB_PRODUCT_NAME", "NewBridge Final Expense")
CARRIER_NAME = os.getenv("JACOB_CARRIER_NAME", "Continental General")
KNOWLEDGE_DIR = Path(os.getenv("JACOB_KNOWLEDGE_DIR", HERE / "knowledge"))

# ── database ─────────────────────────────────────────────────────────────────
DB_DSN = os.getenv("JACOB_DB_DSN", "postgresql:///jacob")

# ── live application state (platform-infra, read-only) ───────────────────────
# Jacob reads the live memApp (application state) for an arcId through the
# platform-infra Valkey read endpoint, over the intra network. Read-only: the
# request's operationType is always "retrieve". The agent process never touches
# this — it lives behind the appstate MCP server (appstate/server.py). Set
# JACOB_PLATFORM_ENV=dev in .env to point at dev instead of production.
PLATFORM_ENV = os.getenv("JACOB_PLATFORM_ENV", "prod")
PLATFORM_BASE_URL = os.getenv(
    "JACOB_PLATFORM_BASE_URL",
    f"https://platform-infra.afficiency-{PLATFORM_ENV}.az.intra.afficiency.com",
).rstrip("/")
PLATFORM_TIMEOUT = float(os.getenv("JACOB_PLATFORM_TIMEOUT", "30"))

# ── embeddings (Ollama-compatible /api/embed) ────────────────────────────────
EMBED_BASE_URL = os.getenv("JACOB_EMBED_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
EMBED_MODEL = os.getenv("JACOB_EMBED_MODEL", "mxbai-embed-large")
EMBED_DIM = int(os.getenv("JACOB_EMBED_DIM", "1024"))
EMBED_BATCH = int(os.getenv("JACOB_EMBED_BATCH", "16"))

# ── retrieval ────────────────────────────────────────────────────────────────
SEARCH_TOP_K = int(os.getenv("JACOB_TOP_K", "4"))
# Weak-match floor: if the best hit's cosine similarity is below this AND it has
# no full-text match, retrieval is flagged weak → Jacob says "not covered".
# Calibrated on the seed corpus (correct paraphrase ≈0.62, uncovered ≈0.45);
# re-tune when the real 511801 sources land.
SIM_FLOOR = float(os.getenv("JACOB_SIM_FLOOR", "0.55"))
SNIPPET_CHARS = int(os.getenv("JACOB_SNIPPET_CHARS", "700"))
