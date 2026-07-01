"""
Basic abuse/cost protection for the public demo.

Two layers, both intentionally simple (no external infra, no database --
appropriate for a portfolio demo, not a production rate limiter):

1. Per-session limits (via Streamlit session_state): caps how many analyses
   one browser session can run, plus a cooldown between requests to stop
   rapid clicking/scripted spam from a single tab.

2. A process-wide global counter (plain module-level state): Streamlit
   Community Cloud runs a single Python process shared by all visitors, so a
   module-level variable is a cheap way to cap total analyses across
   *everyone* per day, as a hard ceiling on worst-case cost regardless of
   how many different sessions hit the app.

LIMITATION (disclosed, not hidden): both counters live in process memory.
They reset if the app restarts/redeploys, and would NOT work as a global
limit if this were ever scaled to multiple server instances. For a single-
instance Streamlit Cloud demo this is a reasonable, honest tradeoff -- a
real production deployment would use a shared store (Redis, a database) instead.
"""

import time

from core.errors import RateLimitExceededError

# --- Tunables ---
MAX_REQUESTS_PER_SESSION = 8
COOLDOWN_SECONDS = 20
MAX_GLOBAL_REQUESTS_PER_DAY = 150

# --- Process-wide (global) state ---
_global_state = {"count": 0, "window_start": time.time()}


def _reset_global_window_if_new_day():
    now = time.time()
    if now - _global_state["window_start"] > 24 * 60 * 60:
        _global_state["count"] = 0
        _global_state["window_start"] = now


def check_global_limit():
    _reset_global_window_if_new_day()
    if _global_state["count"] >= MAX_GLOBAL_REQUESTS_PER_DAY:
        raise RateLimitExceededError(
            "This demo has hit its daily usage cap. Please check back later, "
            "or run the project locally with your own API keys (see README)."
        )


def record_global_request():
    _reset_global_window_if_new_day()
    _global_state["count"] += 1


def check_session_limit(session_state) -> None:
    """
    session_state: pass st.session_state directly. Raises RateLimitExceededError
    if the session has hit its cap or is still in cooldown.
    """
    count = session_state.get("_rl_count", 0)
    last_request = session_state.get("_rl_last_request", 0)

    if count >= MAX_REQUESTS_PER_SESSION:
        raise RateLimitExceededError(
            f"You've reached the limit of {MAX_REQUESTS_PER_SESSION} analyses for this session "
            "(this demo runs on a real API key, so this cap keeps costs sane). "
            "Refresh the page to start a new session, or run it locally with your own key."
        )

    elapsed = time.time() - last_request
    if last_request and elapsed < COOLDOWN_SECONDS:
        wait = COOLDOWN_SECONDS - elapsed
        raise RateLimitExceededError(
            f"Please wait {wait:.0f} more second(s) before running another analysis."
        )


def record_session_request(session_state) -> None:
    session_state["_rl_count"] = session_state.get("_rl_count", 0) + 1
    session_state["_rl_last_request"] = time.time()
    record_global_request()


def sessions_remaining(session_state) -> int:
    return max(0, MAX_REQUESTS_PER_SESSION - session_state.get("_rl_count", 0))
