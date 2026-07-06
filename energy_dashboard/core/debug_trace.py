"""Session debug tracing — append NDJSON to the Cursor debug log."""
from __future__ import annotations

import json
import time

_DEBUG_LOG = "/home/user/PowerModel/.cursor/debug-4ad131.log"
_SESSION = "4ad131"


def debug_trace(
    location: str,
    message: str,
    *,
    data: dict | None = None,
    hypothesis_id: str = "",
    run_id: str = "pre-fix",
) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": _SESSION,
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "hypothesisId": hypothesis_id,
            "runId": run_id,
        }
        with open(_DEBUG_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass
    # #endregion


__all__ = ["debug_trace"]
