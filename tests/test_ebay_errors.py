"""
Tests for core/ebay_client.py's error handling: network issues mid-request
and the zero-comps-found case. Mocks requests entirely so no real eBay
credentials or network access are needed.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import requests

from core import config
from core.errors import CompDataError, NoCompsFoundError
from core.ebay_client import get_comps, _token_cache


@pytest.fixture(autouse=True)
def sandbox_mode_with_fake_creds():
    """Force sandbox/production code path (not mock) so we're exercising the real network logic."""
    original_env = config.EBAY_ENV
    original_url = config.EBAY_BROWSE_URL
    original_oauth = config.EBAY_OAUTH_URL
    config.EBAY_ENV = "sandbox"
    config.EBAY_BROWSE_URL = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
    config.EBAY_OAUTH_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    config.EBAY_CLIENT_ID = "fake-id"
    config.EBAY_CLIENT_SECRET = "fake-secret"
    _token_cache["token"] = "fake-cached-token"
    _token_cache["expires_at"] = 9999999999  # far future, so we skip the OAuth call entirely
    yield
    config.EBAY_ENV = original_env
    config.EBAY_BROWSE_URL = original_url
    config.EBAY_OAUTH_URL = original_oauth
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0


@patch("core.ebay_client.requests.get")
def test_connection_error_wrapped_cleanly(mock_get):
    mock_get.side_effect = requests.exceptions.ConnectionError("Failed to establish a new connection")
    with pytest.raises(CompDataError) as exc_info:
        get_comps("Nike Air Max 90")
    assert "Failed to establish" not in str(exc_info.value)
    assert "connect" in str(exc_info.value).lower()


@patch("core.ebay_client.requests.get")
def test_timeout_wrapped_cleanly(mock_get):
    mock_get.side_effect = requests.exceptions.Timeout("Read timed out")
    with pytest.raises(CompDataError) as exc_info:
        get_comps("Nike Air Max 90")
    assert "Read timed out" not in str(exc_info.value)
    assert "time" in str(exc_info.value).lower()


@patch("core.ebay_client.requests.get")
def test_http_error_wrapped_cleanly(mock_get):
    resp = MagicMock()
    resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
    mock_get.return_value = resp
    with pytest.raises(CompDataError) as exc_info:
        get_comps("Nike Air Max 90")
    assert "500 Server Error" not in str(exc_info.value)


@patch("core.ebay_client.requests.get")
def test_zero_results_raises_no_comps_found(mock_get):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"itemSummaries": []}
    mock_get.return_value = resp
    with pytest.raises(NoCompsFoundError) as exc_info:
        get_comps("Extremely Obscure Shoe Model XYZ123")
    assert "No comparable listings" in str(exc_info.value)


@patch("core.ebay_client.requests.get")
def test_successful_response_parses_comps(mock_get):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "itemSummaries": [
            {
                "title": "Nike Air Max 90 White Size 10",
                "price": {"value": "120.00", "currency": "USD"},
                "condition": "PRE_OWNED",
                "itemWebUrl": "https://www.ebay.com/itm/123",
            }
        ]
    }
    mock_get.return_value = resp
    comps = get_comps("Nike Air Max 90")
    assert len(comps) == 1
    assert comps[0].price == 120.00
    assert comps[0].source == "ebay"


def test_mock_mode_zero_results_case():
    """Mock mode always returns fixture data, but the zero-results guard should
    still exist so real eBay result sets of length zero are handled the same way."""
    config.EBAY_ENV = "mock"
    comps = get_comps("Anything")
    assert len(comps) > 0  # mock fixtures always produce data by design
