"""Per-conversation arcId boundary (JACOB_SESSION_ARCID).

    python -m tests.test_scope

Pins the two enforcement layers added 2026-08-23 for the in-eApp chat:
  • appstate.server.get_application_state — HARD gate: a bound session may only
    look up its own arcId (exact, case-sensitive); any other id returns the
    SCOPE refusal WITHOUT touching the platform.
  • agent.load_system_prompt — a bound session's prompt carries the scope
    section (auto-use the bound arcId, decline others); unbound prompts don't.
"""
from __future__ import annotations

import os

from appstate import platform, server

BOUND = "ARCF26999Z479"
OTHER = "ARCF26999Q101"


def run() -> None:
    calls: list[str] = []

    def fake_read(arc_id: str) -> dict:
        calls.append(arc_id)
        return {"productId": "511801", "arcidStatus": "Interview in Progress",
                "appDecisionCode": 99}

    real_read = platform.read_memapp
    platform.read_memapp = fake_read
    try:
        # unbound session → any valid arcId proceeds to the platform read
        os.environ.pop("JACOB_SESSION_ARCID", None)
        out = server.get_application_state(OTHER)
        assert "Live status" in out and calls == [OTHER], out

        # bound session → a different arcId is refused BEFORE any platform read
        os.environ["JACOB_SESSION_ARCID"] = BOUND
        calls.clear()
        out = server.get_application_state(OTHER)
        assert out.startswith("SCOPE:") and BOUND in out and calls == [], out

        # exact match is case-sensitive: a near-miss id is still out of scope
        calls.clear()
        out = server.get_application_state(BOUND.replace("Z479", "z479"))
        assert out.startswith("SCOPE:") and calls == [], out

        # bound session + its own arcId → proceeds normally
        calls.clear()
        out = server.get_application_state(BOUND)
        assert "Live status" in out and calls == [BOUND], out

        # prompt layer: bound → scope section with the arcId; unbound → absent
        import agent
        p = agent.load_system_prompt()
        assert "This conversation's application" in p and BOUND in p
        os.environ.pop("JACOB_SESSION_ARCID", None)
        p = agent.load_system_prompt()
        assert "This conversation's application" not in p
    finally:
        platform.read_memapp = real_read
        os.environ.pop("JACOB_SESSION_ARCID", None)

    print("scope boundary: ALL PASS (server hard-gate + prompt injection)")


if __name__ == "__main__":
    run()
