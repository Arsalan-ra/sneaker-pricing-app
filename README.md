# Sneaker Pricing & Listing Assistant

A portfolio project: upload photos of a pair of sneakers, get an AI-generated condition
assessment, a price range backed by comparable eBay listings, and ready-to-post listing copy.

**Live demo:** _(add your Streamlit Cloud URL here after deploying)_

## What this actually is (read this first)

This project uses **Claude's general-purpose multimodal vision API** to look at photos and
describe what it sees — it is **not** a custom-trained computer vision model, and it has
**no training data of sneakers or wear patterns**. The condition assessment is Claude reasoning
over pixels the same way it would for any image, prompted to behave like an experienced reseller.
That means:

- It can misidentify obscure or discontinued models.
- Condition grading is a judgment call from a general model, not a calibrated defect-detection
  system — treat it as a first-pass estimate, not a certified grade.
- It has no memory of past listings and doesn't improve from feedback in this version.

This is deliberate and disclosed, not a limitation I'm trying to hide. Building and calibrating
a real defect-detection CV model (e.g., a fine-tuned vision model trained on labeled wear-pattern
data) is a meaningfully different and larger project. This one is about building a coherent
end-to-end product pipeline — image understanding, external market data, decision logic, and
generated copy — glued together well, with realistic scope for a portfolio timeline.

### Prior art / related tools

This isn't a novel idea and I'm not presenting it as one:

- **Facebook Marketplace** has shipped native AI features for auto-generating listing titles,
  descriptions, and price suggestions from photos for consumer sellers.
- **Underpriced AI** and similar resale-focused tools already do photo-based item ID + comp-based
  pricing for sneaker/streetwear resellers, some with more specialized/trained models.
- **StockX** and **GOAT** provide authenticated market pricing data for sneakers specifically,
  which is a stronger pricing source than general eBay listings for well-known models — a real
  production version of this tool would likely lean on something closer to that instead of (or
  alongside) eBay.

What I built here is my own implementation of that general pattern, scoped down to one category
and one comp source, using Claude's API directly rather than a pre-built resale tool, as a way to
demonstrate API integration, pipeline design, and honest handling of an LLM's actual capabilities
and limits.

## Known limitations (v1 scope)

- **Sneakers/shoes only.** No support for other categories.
- **eBay Browse API only**, and only **active listings**, not sold/completed ones. eBay's Browse
  API searches current listings; sold-listing search requires the separately-gated Marketplace
  Insights API. Active listing prices are used as a market value proxy here and this is called
  out in the UI. A production version should get sold-comp data (via Marketplace Insights API
  access, or a source like StockX/GOAT for sneakers specifically).
- **No listing publication.** This tool identifies, prices, and writes copy — it does not post
  anything to eBay or anywhere else, and does not track inventory.
- **Condition grading is a single LLM pass**, not a validated/benchmarked classifier. No accuracy
  numbers are claimed because none have been measured against ground truth.
- **eBay category ID is hardcoded** to Athletic Shoes (Men's, category 15709) as a starting point;
  a real version would let this vary or auto-detect based on the item.

## Architecture

```
core/           Shared pipeline logic (used by both backend and frontend)
  config.py     Env var / secrets handling, mode switching
  vision.py     Claude vision call -> item ID + condition assessment
  ebay_client.py eBay Browse API client (mock / sandbox / production modes)
  pricing.py    Comp data -> price range (transparent statistics, not a black box)
  listing.py    Claude call -> title/description/tags

backend/main.py FastAPI app exposing the pipeline as an HTTP API
frontend/app.py Streamlit UI

tests/          Unit tests for the pricing engine (the deterministic piece)
```

**Why the Streamlit app imports `core/` directly instead of calling the FastAPI backend over
HTTP:** Streamlit Community Cloud runs a single process, so it can't host a separate FastAPI
server alongside the Streamlit app. The FastAPI layer is included to demonstrate a proper API
boundary (and can be deployed independently — Render, Railway, Fly.io — to actually run as a real
client/server split), but the deployed Streamlit Cloud demo calls the shared `core/` modules
in-process to avoid needing two hosted services for a portfolio project.

## Model tier (cost vs. accuracy tradeoff)

No code changes needed to switch models — set one env var:

- `CLAUDE_MODEL_TIER=quality` (default) → `claude-sonnet-4-6`, best accuracy
- `CLAUDE_MODEL_TIER=economy` → `claude-haiku-4-5-20251001`, ~5x cheaper per token, still capable enough for this task

The active model and tier are shown in the Streamlit UI at all times, so it's never hidden config.
For a demo link shared with recruiters, `economy` is the sensible default — it stretches API credit
much further with minimal practical difference for this use case. Switch to `quality` if you want to
show off reasoning depth specifically. An advanced `CLAUDE_MODEL` env var is also available to set an
exact model string directly, bypassing the tier system entirely.

## Abuse / cost protection

This app calls real, metered APIs (Anthropic + eBay), so the public demo has basic protection
against runaway cost:

- **Per-session cap:** each browser session gets a limited number of analyses (`MAX_REQUESTS_PER_SESSION`
  in `core/rate_limit.py`, default 8) before it's blocked until the page is refreshed.
- **Per-session cooldown:** a minimum wait (`COOLDOWN_SECONDS`, default 20s) is enforced between
  analyses in the same session, so a stuck click or a quick script can't fire requests back-to-back.
- **Global daily cap:** a process-wide counter (`MAX_GLOBAL_REQUESTS_PER_DAY`, default 150) caps total
  analyses across *all* visitors combined, as a hard ceiling on worst-case daily spend.
- Invalid uploads (non-images, corrupted files) are rejected **before** any paid API call is made,
  so they don't count against the cap and can't be used to run up cost even at high volume.

**Honest limitation:** both counters live in the app's process memory. They reset on app restart/
redeploy, and wouldn't hold as a *global* limit across multiple server instances. That's an
appropriate tradeoff for a single-instance Streamlit Cloud demo, not a production-grade rate
limiter — a real production deployment would back this with Redis or a database instead.

## Failure handling

Every external failure point is caught and mapped to a clean, user-facing message — no raw
tracebacks or exception text ever reach the UI. Specifically handled:

| Case | Behavior |
|---|---|
| Non-shoe photo uploaded | Claude's response includes an `is_footwear` flag; if false, the pipeline stops before wasting an eBay lookup or listing-generation call, and shows the user its best guess at what the photo actually shows. |
| Non-image file uploaded | Validated with Pillow (`core/validation.py`) before it's ever sent anywhere — checks file size, that it's a real decodable image, and that the format is JPEG/PNG/WEBP. Rejected with a specific, friendly message; costs nothing. |
| Claude API call fails/times out | Anthropic SDK exceptions (auth, rate limit, timeout, connection, bad response, malformed JSON) are each caught individually in `core/vision.py` and `core/listing.py` and re-raised as `AIServiceError` with a clean message. Raw SDK error text is never shown to the user (logged server-side only). |
| eBay returns zero comps | Explicitly raises `NoCompsFoundError` with a suggestion to broaden the search, instead of silently returning an empty result that would break the pricing step downstream. |
| Network issue mid-request | `requests` exceptions (timeout, connection error, HTTP error) are caught in `core/ebay_client.py` and re-raised as `CompDataError` with a clean message. |
| Rate limit / cooldown hit | Raises `RateLimitExceededError` with the exact wait time or a note to refresh, shown as a warning rather than an error. |

All of this is unit-tested with mocked API clients (no real credentials needed to run the tests):
`tests/test_validation.py`, `tests/test_rate_limit.py`, `tests/test_vision_errors.py`,
`tests/test_ebay_errors.py`. 34 tests total, all passing (`pytest tests/`).



### 1. Get an Anthropic API key
1. Sign up at [console.anthropic.com](https://console.anthropic.com) (redirects to
   platform.claude.com).
2. Add a payment method under Settings → Plans & Billing (there's no meaningful free tier for
   API use; a few dollars of credit covers a lot of testing).
3. Settings → API Keys → Create Key. Copy it immediately, it's shown once.

### 2. Get eBay Browse API access
1. Sign up at [developer.ebay.com](https://developer.ebay.com).
2. My Account → Application Keys gives you both **sandbox** keys (work immediately, synthetic
   data only) and **production** keys (work for basic Browse API scope; higher-tier access can
   take longer to approve).
3. Client credentials grant (no user login needed):
   ```
   POST https://api.ebay.com/identity/v1/oauth2/token          # production
   POST https://api.sandbox.ebay.com/identity/v1/oauth2/token  # sandbox
   ```

### 3. Configure environment
```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY, and either leave EBAY_ENV=mock or add real eBay creds
```

`EBAY_ENV` has three settings:
- `mock` — synthetic fixture comp data, no eBay account needed at all. Good for demoing the full
  pipeline (vision + pricing logic + listing copy) without depending on eBay approval timing.
- `sandbox` — real eBay OAuth flow, synthetic eBay data.
- `production` — real eBay OAuth flow, real listing data.

### 4. Install and run locally
```bash
pip install -r requirements.txt

# Streamlit UI
streamlit run frontend/app.py

# FastAPI backend (optional, separate process, for API testing)
uvicorn backend.main:app --reload --port 8000
```

### 5. Run tests
```bash
pytest tests/
```

## Deploying to Streamlit Community Cloud
1. Push this repo to GitHub (make sure `.env` and `.streamlit/secrets.toml` are gitignored —
   they are, by default, in this repo).
2. On [share.streamlit.io](https://share.streamlit.io), create a new app pointing at
   `frontend/app.py` in this repo.
3. Under App Settings → Secrets, paste the contents of `.streamlit/secrets.toml.example` with
   real values filled in.
4. Deploy. If eBay creds aren't ready yet, set `EBAY_ENV = "mock"` in secrets so the deployed
   demo still works end-to-end.
