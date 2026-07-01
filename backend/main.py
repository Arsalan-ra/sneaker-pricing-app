"""
FastAPI backend for the pricing assistant.

Run locally with:
    uvicorn backend.main:app --reload --port 8000

This exposes the pipeline as an HTTP API, useful for testing the core logic
independently of the Streamlit UI, or for a future non-Streamlit frontend.

NOTE ON DEPLOYMENT: Streamlit Community Cloud only runs a single process
(the Streamlit app), so it cannot host this FastAPI server alongside it.
For the deployed portfolio demo, the Streamlit app imports the `core/`
modules directly instead of calling this API over HTTP. This file exists
to demonstrate a proper API layer and can be deployed separately (Render,
Railway, Fly.io, etc.) if you want a real client-server split running live.
"""

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core import config, rate_limit
from core.ebay_client import get_comps
from core.errors import AppError, RateLimitExceededError
from core.listing import generate_listing
from core.pricing import recommend_price
from core.validation import validate_image_bytes
from core.vision import assess_item

app = FastAPI(title="Sneaker Pricing Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Per-client-IP session state substitute for the API (Streamlit uses browser
# session_state for this; a bare HTTP API has no equivalent, so we key on
# client IP as a simple stand-in). Same disclosed limitation as core/rate_limit.py:
# in-memory, resets on restart, not multi-instance safe.
_ip_state: dict[str, dict] = {}


class AnalyzeResponse(BaseModel):
    assessment: dict
    comps: list[dict]
    price_recommendation: dict
    listing: dict


@app.get("/health")
def health():
    problems = config.validate(require_ebay=(config.EBAY_ENV != "mock"))
    return {"ok": not problems, "problems": problems, "ebay_env": config.EBAY_ENV}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: Request,
    images: list[UploadFile] = File(...),
    description: str = Form(""),
    size: str = Form(""),
    strategy: str = Form("balanced"),
):
    client_ip = request.client.host if request.client else "unknown"
    client_state = _ip_state.setdefault(client_ip, {})

    try:
        rate_limit.check_global_limit()
        rate_limit.check_session_limit(client_state)
    except RateLimitExceededError as e:
        raise HTTPException(429, str(e)) from e

    if not images or len(images) == 0:
        raise HTTPException(400, "At least one image is required.")
    if len(images) > 3:
        raise HTTPException(400, "Maximum 3 images allowed.")
    if strategy not in ("fast", "balanced", "max"):
        raise HTTPException(400, "strategy must be one of: fast, balanced, max")

    image_tuples = []
    for img in images:
        data = await img.read()
        try:
            media_type = validate_image_bytes(data, filename=img.filename or "upload")
        except AppError as e:
            raise HTTPException(400, str(e)) from e
        image_tuples.append((data, media_type))

    rate_limit.record_session_request(client_state)

    try:
        assessment = assess_item(image_tuples, user_description=description)
    except AppError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:
        raise HTTPException(502, "Something went wrong analyzing the photos. Please try again.") from e

    query = f"{assessment.brand} {assessment.model}"
    if assessment.colorway:
        query += f" {assessment.colorway}"

    try:
        comps = get_comps(query)
    except AppError as e:
        raise HTTPException(502, str(e)) from e
    except Exception as e:
        raise HTTPException(502, "Something went wrong looking up comparable listings.") from e

    try:
        price_rec = recommend_price(comps, assessment.condition, strategy)
    except AppError as e:
        raise HTTPException(500, str(e)) from e
    except Exception as e:
        raise HTTPException(500, "Something went wrong calculating a price.") from e

    try:
        listing = generate_listing(assessment, price_rec, size=size)
    except AppError as e:
        raise HTTPException(502, str(e)) from e
    except Exception as e:
        raise HTTPException(502, "Something went wrong writing the listing copy.") from e

    return AnalyzeResponse(
        assessment=assessment.raw,
        comps=[c.__dict__ for c in comps],
        price_recommendation=price_rec.__dict__,
        listing=listing,
    )
