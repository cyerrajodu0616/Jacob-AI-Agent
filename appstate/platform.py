"""Read the live application record (memApp) from platform-infra.

This is the ONLY module that reaches the platform network, and it does exactly
one thing: a READ. The application state for an arcId lives as a RedisJSON
document at the Valkey key = the bare arcId; the platform exposes it through one
endpoint whose path says `update` but whose `operationType: retrieve` is a read.

stdlib urllib + certifi, matching rag/embedder.py — no new dependency. Requires
the intra network (same private DNS as the Postgres host Jacob already uses).
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

import certifi

import config

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())
_HEADERS = {"Content-Type": "application/json"}


class Unavailable(Exception):
    """The platform could not be reached (network / HTTP / bad response)."""


def _read(key: str, subkey: str = ""):
    """One Valkey read. `subkey` is an optional dotted JSONPath into the record, so
    a caller can fetch just the slice it needs instead of a whole document. Returns
    whatever `data` holds (or None). Raises Unavailable on a transport/HTTP error."""
    payload = {
        "redisKeyName": key,
        "redisSubKeyName": subkey,
        "operationType": "retrieve",   # a READ, despite the endpoint name
        "env": config.PLATFORM_ENV.upper(),
        "prsCode": "redisCRUD",
    }
    req = urllib.request.Request(
        f"{config.PLATFORM_BASE_URL}/infra/database/redis/update",
        data=json.dumps(payload).encode(),
        headers=_HEADERS,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.PLATFORM_TIMEOUT, context=_SSL_CTX) as resp:
            body = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as err:
        raise Unavailable(f"{type(err).__name__}: {err}") from err
    return body.get("data") if isinstance(body, dict) else None


def read_memapp(arc_id: str) -> dict:
    """The live memApp for one arcId, or {} if there is no live record.

    Raises Unavailable on a transport/HTTP error, so the caller can tell
    "no such application" (returns {}) from "couldn't reach the platform"
    (raises) and word the two very differently to the agent.
    """
    data = _read(arc_id)
    return data if isinstance(data, dict) else {}
