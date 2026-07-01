"""
Central configuration for the pricing assistant.

Reads from environment variables. In local dev, values come from a .env file
(see .env.example) -- python-dotenv loads that file into the environment below.
On Streamlit Cloud, set these under App Settings -> Secrets instead; this module
also checks st.secrets as a fallback so the same code works in both places.
"""

import os

from dotenv import load_dotenv

# Loads variables from a .env file in the current working directory (or any
# parent directory) into os.environ, if one exists. Does nothing if there's
# no .env file -- e.g. on Streamlit Cloud, where secrets come from st.secrets
# instead and there's no .env file at all.
load_dotenv()


def _get(key: str, default: str = "") -> str:
    """Look up a config value from env vars first, then Streamlit secrets if available."""
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st  # only import if actually running under Streamlit
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default


# --- Anthropic ---
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")

# Model selection: two ways to control this, in priority order.
#
# 1. CLAUDE_MODEL_TIER — the easy way, no model strings to remember:
#      "quality" -> claude-sonnet-4-6  (best accuracy, ~5x the cost)
#      "economy" -> claude-haiku-4-5-20251001  (cheaper, still solid for this task)
#    This is the one to flip for a public/recruiter-facing demo where cost matters
#    more than squeezing out the last bit of accuracy.
#
# 2. CLAUDE_MODEL — set this directly to override the tier entirely with any
#    specific model string (e.g. to test a new model). Takes precedence over
#    CLAUDE_MODEL_TIER if both are set.
_MODEL_TIERS = {
    "quality": "claude-sonnet-4-6",
    "economy": "claude-haiku-4-5-20251001",
}
CLAUDE_MODEL_TIER = _get("CLAUDE_MODEL_TIER", "quality").lower()
CLAUDE_MODEL = _get("CLAUDE_MODEL") or _MODEL_TIERS.get(CLAUDE_MODEL_TIER, _MODEL_TIERS["quality"])

# --- eBay ---
EBAY_CLIENT_ID = _get("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = _get("EBAY_CLIENT_SECRET")

# EBAY_ENV controls which eBay backend is used:
#   "production" -> real Browse API, real sold/active listings
#   "sandbox"    -> eBay sandbox, synthetic data (good for testing plumbing only)
#   "mock"       -> local fixture data, no network call at all (demo fallback)
EBAY_ENV = _get("EBAY_ENV", "mock").lower()

EBAY_OAUTH_URL = {
    "production": "https://api.ebay.com/identity/v1/oauth2/token",
    "sandbox": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
}.get(EBAY_ENV, "")

EBAY_BROWSE_URL = {
    "production": "https://api.ebay.com/buy/browse/v1/item_summary/search",
    "sandbox": "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search",
}.get(EBAY_ENV, "")


def validate(require_ebay: bool = True) -> list[str]:
    """Returns a list of human-readable BLOCKING problems. Empty list = OK to run."""
    problems = []
    if not ANTHROPIC_API_KEY:
        problems.append("ANTHROPIC_API_KEY is not set.")
    if require_ebay and EBAY_ENV in ("production", "sandbox"):
        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            problems.append(
                f"EBAY_ENV is '{EBAY_ENV}' but EBAY_CLIENT_ID/EBAY_CLIENT_SECRET are missing."
            )
    return problems


def warnings() -> list[str]:
    """Returns non-blocking configuration warnings -- shown to the user but the app still runs."""
    warns = []
    if not _get("CLAUDE_MODEL") and CLAUDE_MODEL_TIER not in _MODEL_TIERS:
        warns.append(
            f"CLAUDE_MODEL_TIER is '{CLAUDE_MODEL_TIER}', which isn't recognized "
            f"(expected 'quality' or 'economy') -- falling back to 'quality' (Sonnet)."
        )
    return warns
