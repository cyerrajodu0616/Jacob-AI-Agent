"""Embeddings client — Ollama /api/embed wire format, stdlib only.

The embedder is a seam: anything that serves this API shape (local Ollama, the
ngrok-tunnelled laptop, an Ollama container in Azure) is interchangeable via
JACOB_EMBED_BASE_URL. Model + dimension are recorded per document in the store,
so a model change is a controlled re-embed, never a silent drift.
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request

import certifi

import config

_HEADERS = {
    "Content-Type": "application/json",
    # Required by ngrok's free tier; harmless for direct Ollama hosts.
    "ngrok-skip-browser-warning": "true",
}
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _post(payload: dict, timeout: float = 120.0) -> dict:
    req = urllib.request.Request(
        f"{config.EMBED_BASE_URL}/api/embed",
        data=json.dumps(payload).encode(),
        headers=_HEADERS,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return json.loads(resp.read())


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts in batches; returns vectors in input order."""
    out: list[list[float]] = []
    for i in range(0, len(texts), config.EMBED_BATCH):
        batch = texts[i : i + config.EMBED_BATCH]
        payload = {"model": config.EMBED_MODEL, "input": batch}
        try:
            data = _post(payload)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2)  # one retry — tunnels hiccup
            data = _post(payload)
        vecs = data.get("embeddings")
        if not isinstance(vecs, list) or len(vecs) != len(batch):
            raise RuntimeError(f"embedding server returned {len(vecs or [])} vectors for {len(batch)} inputs")
        for v in vecs:
            if len(v) != config.EMBED_DIM:
                raise RuntimeError(f"expected dim {config.EMBED_DIM}, got {len(v)} — wrong model?")
        out.extend(vecs)
    return out


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
