"""
Tests for core/vision.py's error handling and non-footwear detection.

These mock the Anthropic client entirely (no real API calls / no API key needed)
so they can run in CI or locally without credentials, and so they deterministically
exercise each failure path described in the review: auth errors, rate limits,
timeouts/connection issues, and malformed JSON responses.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
import httpx
import pytest

from core.errors import AIServiceError, NotFootwearError
from core.vision import assess_item

FAKE_IMAGE = (b"\xff\xd8\xff\xe0fake-jpeg-bytes", "image/jpeg")


def _mock_response(json_dict: dict):
    """Builds a fake anthropic.Message-like response with the given JSON as text output."""
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(json_dict)
    resp = MagicMock()
    resp.content = [block]
    return resp


def _httpx_response(status_code=500):
    return httpx.Response(status_code, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


def _httpx_request():
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


VALID_FOOTWEAR_JSON = {
    "is_footwear": True,
    "brand": "Nike",
    "model": "Air Max 90",
    "colorway": "White/Grey",
    "identification_confidence": "high",
    "condition": "good",
    "condition_confidence": "medium",
    "visible_flaws": ["light sole scuffing"],
    "notes": "",
}

NON_FOOTWEAR_JSON = {
    "is_footwear": False,
    "brand": "Unknown",
    "model": "Unknown",
    "colorway": None,
    "identification_confidence": "low",
    "condition": "good",
    "condition_confidence": "low",
    "visible_flaws": [],
    "notes": "This appears to be a photo of a coffee mug, not footwear.",
}


@patch("core.vision.anthropic.Anthropic")
def test_valid_footwear_response_parses_correctly(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_response(VALID_FOOTWEAR_JSON)
    mock_anthropic_cls.return_value = mock_client

    result = assess_item([FAKE_IMAGE], "Nike Air Max 90")
    assert result.brand == "Nike"
    assert result.is_footwear is True


@patch("core.vision.anthropic.Anthropic")
def test_non_footwear_raises_friendly_error(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_response(NON_FOOTWEAR_JSON)
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(NotFootwearError) as exc_info:
        assess_item([FAKE_IMAGE])
    assert "coffee mug" in str(exc_info.value)


@patch("core.vision.anthropic.Anthropic")
def test_non_footwear_allowed_when_flag_set(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_response(NON_FOOTWEAR_JSON)
    mock_anthropic_cls.return_value = mock_client

    result = assess_item([FAKE_IMAGE], allow_non_footwear=True)
    assert result.is_footwear is False


@patch("core.vision.anthropic.Anthropic")
def test_authentication_error_wrapped_cleanly(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.AuthenticationError(
        "invalid api key", response=_httpx_response(401), body=None
    )
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(AIServiceError) as exc_info:
        assess_item([FAKE_IMAGE])
    # The raw exception text should NOT leak through
    assert "invalid api key" not in str(exc_info.value)
    assert "authentication" in str(exc_info.value).lower()


@patch("core.vision.anthropic.Anthropic")
def test_rate_limit_error_wrapped_cleanly(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.RateLimitError(
        "rate limited", response=_httpx_response(429), body=None
    )
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(AIServiceError) as exc_info:
        assess_item([FAKE_IMAGE])
    assert "rate limited" not in str(exc_info.value).lower() or "rate-limited" in str(exc_info.value).lower()
    assert "wait" in str(exc_info.value).lower()


@patch("core.vision.anthropic.Anthropic")
def test_timeout_error_wrapped_cleanly(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.APITimeoutError(request=_httpx_request())
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(AIServiceError) as exc_info:
        assess_item([FAKE_IMAGE])
    assert "connection" in str(exc_info.value).lower() or "timeout" in str(exc_info.value).lower()


@patch("core.vision.anthropic.Anthropic")
def test_connection_error_wrapped_cleanly(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.APIConnectionError(request=_httpx_request())
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(AIServiceError):
        assess_item([FAKE_IMAGE])


@patch("core.vision.anthropic.Anthropic")
def test_malformed_json_response_wrapped_cleanly(mock_anthropic_cls):
    block = MagicMock()
    block.type = "text"
    block.text = "Sorry, I can't format this as JSON: {not valid json!!"
    resp = MagicMock()
    resp.content = [block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = resp
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(AIServiceError) as exc_info:
        assess_item([FAKE_IMAGE])
    # Should be a clean message, not a raw JSONDecodeError string
    assert "Expecting" not in str(exc_info.value)  # that's json module's internal error text
