import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from core import rate_limit
from core.errors import RateLimitExceededError


@pytest.fixture(autouse=True)
def reset_global_state():
    """Each test gets a clean global counter so tests don't interfere with each other."""
    rate_limit._global_state["count"] = 0
    rate_limit._global_state["window_start"] = time.time()
    yield


def test_fresh_session_has_no_limit_issues():
    session = {}
    rate_limit.check_session_limit(session)  # should not raise


def test_session_cap_enforced():
    session = {}
    for _ in range(rate_limit.MAX_REQUESTS_PER_SESSION):
        rate_limit.check_session_limit(session)
        # simulate no-cooldown-issue by backdating last_request beyond cooldown
        rate_limit.record_session_request(session)
        session["_rl_last_request"] = time.time() - rate_limit.COOLDOWN_SECONDS - 1

    with pytest.raises(RateLimitExceededError):
        rate_limit.check_session_limit(session)


def test_cooldown_enforced_between_requests():
    session = {}
    rate_limit.check_session_limit(session)
    rate_limit.record_session_request(session)

    # Immediately trying again should hit the cooldown, not the session cap
    with pytest.raises(RateLimitExceededError) as exc_info:
        rate_limit.check_session_limit(session)
    assert "wait" in str(exc_info.value).lower()


def test_cooldown_clears_after_window():
    session = {}
    rate_limit.record_session_request(session)
    # Backdate the last request past the cooldown window
    session["_rl_last_request"] = time.time() - rate_limit.COOLDOWN_SECONDS - 1
    rate_limit.check_session_limit(session)  # should not raise


def test_sessions_remaining_counts_down():
    session = {}
    assert rate_limit.sessions_remaining(session) == rate_limit.MAX_REQUESTS_PER_SESSION
    rate_limit.record_session_request(session)
    assert rate_limit.sessions_remaining(session) == rate_limit.MAX_REQUESTS_PER_SESSION - 1


def test_global_cap_enforced():
    for _ in range(rate_limit.MAX_GLOBAL_REQUESTS_PER_DAY):
        rate_limit.check_global_limit()
        rate_limit.record_global_request()

    with pytest.raises(RateLimitExceededError):
        rate_limit.check_global_limit()


def test_two_independent_sessions_dont_share_session_cap():
    session_a = {}
    session_b = {}
    for _ in range(rate_limit.MAX_REQUESTS_PER_SESSION):
        rate_limit.check_session_limit(session_a)
        rate_limit.record_session_request(session_a)
        session_a["_rl_last_request"] = time.time() - rate_limit.COOLDOWN_SECONDS - 1

    with pytest.raises(RateLimitExceededError):
        rate_limit.check_session_limit(session_a)

    # session_b is a fresh session and should be unaffected by session_a's cap
    rate_limit.check_session_limit(session_b)  # should not raise
