"""Interface message processing stub.

**Honest scope**: there is no real external system (no EDIFACT gateway, no
partner HTTP endpoint) behind Interface Messages yet. ``process_message`` is a
*simulator* used by the retry endpoint so the console can demonstrate the
retry → result loop without pretending an integration happened.

Decision (documented per Track C4):
- Retry is **synchronous**. The router re-queues the row (status=pending,
  retry_count += 1, last_retry_at = now) and then immediately runs this stub.
- Inbound messages whose payload is parse-shaped JSON (a JSON object, or a
  string that parses to one) are marked ``success``.
- Everything else is marked ``failed`` with an explicit stub reason — outbound
  delivery is never faked as success.

When a real adapter lands, replace this function body with the actual
send/parse call and keep the (status, error_message) return contract.
"""

from __future__ import annotations

import json

from app.models_interface import InterfaceMessage


def process_message(msg: InterfaceMessage) -> tuple[str, str | None]:
    """Run the stub processor. Returns ``(status, error_message)``.

    Status is one of ``success`` / ``failed``. Caller has already set the row
    to ``pending`` (re-queued) and bumped ``retry_count`` / ``last_retry_at``.
    """
    if msg.direction == "outbound":
        return "failed", "stub processor: no external delivery channel configured"

    payload = msg.payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            payload = None
    if isinstance(payload, dict):
        return "success", None
    return "failed", "stub processor: inbound payload is not parse-shaped JSON"
