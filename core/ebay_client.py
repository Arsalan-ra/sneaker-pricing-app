"""
eBay Browse API client for pulling comparable listings.

Supports three modes via config.EBAY_ENV:
  - "production": real Browse API search (active listings; Browse API does not expose
                   sold/completed items directly -- see note in get_comps() below)
  - "sandbox": eBay sandbox environment, synthetic data only
  - "mock": local fixture data, no network calls -- used as a demo fallback when
            eBay credentials/approval aren't ready yet
"""

import time
from dataclasses import dataclass

import requests

from core import config
from core.errors import CompDataError, NoCompsFoundError

_token_cache = {"token": None, "expires_at": 0}


@dataclass
class Comp:
    title: str
    price: float
    currency: str
    condition: str
    url: str
    source: str  # "ebay" or "mock"


def _get_oauth_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 30:
        return _token_cache["token"]

    try:
        resp = requests.post(
            config.EBAY_OAUTH_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            auth=(config.EBAY_CLIENT_ID, config.EBAY_CLIENT_SECRET),
            timeout=15,
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout as e:
        raise CompDataError(
            "eBay didn't respond in time while authenticating. Please try again."
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise CompDataError(
            "Couldn't connect to eBay (network issue). Please check your connection and try again."
        ) from e
    except requests.exceptions.HTTPError as e:
        raise CompDataError(
            "eBay rejected the authentication request. This is a configuration issue, "
            "not something you can fix -- please try again later."
        ) from e
    except requests.exceptions.RequestException as e:
        raise CompDataError("Couldn't reach eBay right now. Please try again.") from e

    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + int(data.get("expires_in", 7200))
    return _token_cache["token"]


def _mock_comps(query: str) -> list[Comp]:
    """
    Deterministic fixture data so the pipeline is demoable without live eBay access.
    Prices are loosely randomized around a base derived from the query so different
    items don't all return identical numbers.
    """
    import hashlib

    seed = int(hashlib.sha256(query.encode()).hexdigest(), 16) % 1000
    base = 40 + (seed % 160)  # base price between $40-$200

    samples = [
        (1.35, "new", "Deadstock, box included"),
        (1.10, "like-new", "Worn once, no flaws"),
        (0.95, "good", "Light wear, clean"),
        (0.85, "good", "Minor creasing"),
        (0.70, "fair", "Visible wear, sole scuffs"),
        (0.55, "fair", "Well worn, priced to sell"),
        (0.45, "worn", "Heavy wear, functional"),
    ]
    comps = []
    for i, (mult, cond, desc) in enumerate(samples):
        price = round(base * mult, 2)
        comps.append(
            Comp(
                title=f"{query} - {desc}",
                price=price,
                currency="USD",
                condition=cond,
                url="https://www.ebay.com/",
                source="mock",
            )
        )
    return comps


def get_comps(query: str, limit: int = 20) -> list[Comp]:
    """
    Fetch comparable listings for a search query (e.g. "Nike Air Max 90 White").

    NOTE ON SOLD DATA: eBay's Browse API searches active (currently listed) items,
    not completed/sold listings -- sold listing search requires eBay's Marketplace
    Insights API, which is separately gated and not broadly available to new dev
    accounts. For v1, we use active listing prices as a proxy for market value and
    say so explicitly in the UI/README. This is a known, disclosed limitation.
    """
    if config.EBAY_ENV == "mock":
        comps = _mock_comps(query)
        if not comps:
            raise NoCompsFoundError(
                f"No comparable listings found for '{query}'. Try a more general "
                "description (e.g. drop the colorway) or double-check the item identification above."
            )
        return comps

    if not config.EBAY_BROWSE_URL:
        raise RuntimeError(f"Unsupported EBAY_ENV: {config.EBAY_ENV}")

    token = _get_oauth_token()
    try:
        resp = requests.get(
            config.EBAY_BROWSE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            },
            params={
                "q": query,
                "category_ids": "15709",  # Athletic Shoes (Men's) -- see README for category notes
                "limit": min(limit, 50),
                "filter": "buyingOptions:{FIXED_PRICE}",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout as e:
        raise CompDataError(
            "eBay didn't respond in time while searching for comparable listings. Please try again."
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise CompDataError(
            "Couldn't connect to eBay (network issue). Please check your connection and try again."
        ) from e
    except requests.exceptions.HTTPError as e:
        raise CompDataError(
            "eBay returned an error while searching for comparable listings. Please try again."
        ) from e
    except requests.exceptions.RequestException as e:
        raise CompDataError("Couldn't reach eBay right now. Please try again.") from e

    data = resp.json()

    comps = []
    for item in data.get("itemSummaries", []):
        price_info = item.get("price", {})
        comps.append(
            Comp(
                title=item.get("title", ""),
                price=float(price_info.get("value", 0)),
                currency=price_info.get("currency", "USD"),
                condition=item.get("condition", "UNKNOWN"),
                url=item.get("itemWebUrl", ""),
                source="ebay",
            )
        )

    if not comps:
        raise NoCompsFoundError(
            f"No comparable listings found on eBay for '{query}'. Try a more general "
            "description (e.g. drop the colorway) or double-check the item identification above."
        )

    return comps
