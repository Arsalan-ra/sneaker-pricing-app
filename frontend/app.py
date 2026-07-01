"""
Streamlit frontend for the sneaker pricing assistant.

Runs the pipeline by importing core/ directly (see backend/main.py docstring
for why this app doesn't call the FastAPI server over HTTP when deployed on
Streamlit Community Cloud).

Run locally with:
    streamlit run frontend/app.py
"""

import sys
import traceback
from pathlib import Path

# Allow running `streamlit run frontend/app.py` from repo root without install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from core import config, rate_limit
from core.ebay_client import get_comps
from core.errors import AppError
from core.listing import generate_listing
from core.pricing import recommend_price
from core.validation import validate_image_bytes
from core.vision import assess_item

st.set_page_config(page_title="Sneaker Pricing Assistant", page_icon=":athletic_shoe:", layout="centered")

st.title("Sneaker Pricing & Listing Assistant")
st.caption(
    "Upload photos of a pair of shoes, get an AI condition assessment, "
    "a data-backed price range from eBay comps, and ready-to-post listing copy."
)

problems = config.validate(require_ebay=(config.EBAY_ENV != "mock"))
if problems:
    st.error("Configuration issue(s):\n\n" + "\n".join(f"- {p}" for p in problems))
    st.stop()

for warning in config.warnings():
    st.warning(warning)

if config.EBAY_ENV == "mock":
    st.info(
        "Running in **mock comp data mode** — eBay credentials aren't configured, so "
        "comparable prices below are synthetic fixture data, not live listings. "
        "Set EBAY_ENV to 'sandbox' or 'production' with valid credentials to use real data."
    )

remaining = rate_limit.sessions_remaining(st.session_state)
st.caption(
    f"Model: **{config.CLAUDE_MODEL}** ({config.CLAUDE_MODEL_TIER} tier) &nbsp;|&nbsp; "
    f"This demo runs on a live API key, so usage is capped: {remaining} analyses left this session."
)

with st.form("item_form"):
    uploaded_files = st.file_uploader(
        "Upload 1-3 photos", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True
    )
    description = st.text_input(
        "Description / hints (optional)", placeholder="e.g. Nike Air Max 90, size 10.5, White/Grey"
    )
    size = st.text_input("Size (optional, included in listing copy)", placeholder="e.g. US 10.5")
    strategy = st.select_slider(
        "Pricing strategy",
        options=["fast", "balanced", "max"],
        value="balanced",
        format_func=lambda x: {"fast": "Fast sale (undercut)", "balanced": "Balanced", "max": "Max price (patient)"}[x],
    )
    submitted = st.form_submit_button("Analyze")


def _log_unexpected(context: str, e: Exception) -> None:
    """Full detail goes to server logs only -- never to the user."""
    print(f"[unexpected error] {context}: {e}", file=sys.stderr)
    traceback.print_exc()


if submitted:
    # --- Rate limiting: checked before anything that costs money ---
    try:
        rate_limit.check_global_limit()
        rate_limit.check_session_limit(st.session_state)
    except AppError as e:
        st.warning(str(e))
        st.stop()

    if not uploaded_files:
        st.error("Please upload at least one photo.")
        st.stop()
    if len(uploaded_files) > 3:
        st.warning("Only the first 3 photos will be used.")
        uploaded_files = uploaded_files[:3]

    # --- Validate every uploaded file is actually a readable image before doing anything else ---
    image_tuples = []
    validation_failed = False
    for f in uploaded_files:
        try:
            media_type = validate_image_bytes(f.getvalue(), filename=f.name)
            image_tuples.append((f.getvalue(), media_type))
        except AppError as e:
            st.error(str(e))
            validation_failed = True
        except Exception as e:
            _log_unexpected(f"image validation for {f.name}", e)
            st.error(f"'{f.name}' couldn't be processed. Please try a different photo.")
            validation_failed = True
    if validation_failed:
        st.stop()

    cols = st.columns(len(uploaded_files))
    for col, f in zip(cols, uploaded_files):
        col.image(f, use_container_width=True)

    # This request counts against the caps regardless of how far it gets,
    # since the vision call (the expensive step) is about to run.
    rate_limit.record_session_request(st.session_state)

    with st.spinner("Identifying item and assessing condition..."):
        try:
            assessment = assess_item(image_tuples, user_description=description)
        except AppError as e:
            st.error(str(e))
            st.stop()
        except Exception as e:
            _log_unexpected("vision/identification", e)
            st.error("Something went wrong analyzing your photos. Please try again.")
            st.stop()

    st.subheader("Item Identification")
    id_col1, id_col2 = st.columns(2)
    id_col1.metric("Brand", assessment.brand)
    id_col2.metric("Model", assessment.model)
    if assessment.colorway:
        st.write(f"**Colorway:** {assessment.colorway}")
    st.write(f"**Identification confidence:** {assessment.identification_confidence}")

    st.subheader("Condition Assessment")
    cond_col1, cond_col2 = st.columns(2)
    cond_col1.metric("Condition", assessment.condition)
    cond_col2.metric("Confidence", assessment.condition_confidence)
    if assessment.visible_flaws:
        st.write("**Visible flaws noted:**")
        for flaw in assessment.visible_flaws:
            st.write(f"- {flaw}")
    else:
        st.write("No specific flaws noted.")
    if assessment.notes:
        st.caption(assessment.notes)

    query = f"{assessment.brand} {assessment.model}"
    if assessment.colorway:
        query += f" {assessment.colorway}"

    with st.spinner(f"Pulling comparable listings for '{query}'..."):
        try:
            comps = get_comps(query)
        except AppError as e:
            st.error(str(e))
            st.stop()
        except Exception as e:
            _log_unexpected("eBay comp lookup", e)
            st.error("Something went wrong looking up comparable listings. Please try again.")
            st.stop()

    st.subheader("Comparable Listings")
    st.caption(
        f"{len(comps)} comps found ({comps[0].source} data)"
        + (" — active listings, used as a market value proxy (see README)." if comps[0].source == "ebay" else " — synthetic demo data.")
    )
    st.dataframe(
        [{"Title": c.title, "Price": f"${c.price:.2f}", "Condition": c.condition} for c in comps],
        use_container_width=True,
        hide_index=True,
    )

    with st.spinner("Calculating recommended price..."):
        try:
            price_rec = recommend_price(comps, assessment.condition, strategy)
        except AppError as e:
            st.error(str(e))
            st.stop()
        except Exception as e:
            _log_unexpected("pricing calculation", e)
            st.error("Something went wrong calculating a price. Please try again.")
            st.stop()

    st.subheader("Recommended Price")
    p_col1, p_col2, p_col3 = st.columns(3)
    p_col1.metric("Low", f"${price_rec.low:.2f}")
    p_col2.metric("Target", f"${price_rec.target:.2f}")
    p_col3.metric("High", f"${price_rec.high:.2f}")
    st.caption(price_rec.rationale)

    with st.spinner("Writing listing copy..."):
        try:
            listing = generate_listing(assessment, price_rec, size=size)
        except AppError as e:
            st.error(str(e))
            st.stop()
        except Exception as e:
            _log_unexpected("listing generation", e)
            st.error("Something went wrong writing the listing copy. Please try again.")
            st.stop()

    st.subheader("Generated Listing")
    st.text_input("Title", value=listing.get("title", ""))
    st.text_area("Description", value=listing.get("description", ""), height=220)
    if listing.get("suggested_tags"):
        st.write("**Suggested tags:** " + ", ".join(listing["suggested_tags"]))

st.divider()
st.caption(
    "Portfolio project — condition assessment uses Claude's general multimodal vision "
    "capability, not a custom-trained CV model. See README for details and prior art."
)
