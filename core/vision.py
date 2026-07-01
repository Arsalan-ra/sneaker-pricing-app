"""
Vision + reasoning calls to Claude for item identification and condition assessment.
"""

import base64
import json
import re
from dataclasses import dataclass, field

import anthropic

from core import config
from core.errors import AIServiceError, NotFootwearError

CONDITION_LEVELS = ["new", "like-new", "good", "fair", "worn"]

_SYSTEM_PROMPT = """You are an expert sneaker/shoe reseller with years of experience grading \
footwear condition for resale marketplaces (eBay, StockX, GOAT, Grailed).

First, determine whether the photo(s) actually show a shoe/sneaker at all. If the photos clearly \
show something else (not footwear), set "is_footwear" to false, fill identification/condition \
fields with your best-effort guess anyway (do not leave them blank), and briefly say in "notes" \
what the photos actually appear to show instead.

If the photos do show footwear, given 1-3 photos of a pair of shoes and an optional user \
description, you will:
1. Identify the item: brand, model, colorway (if identifiable), and approximate release era if relevant.
2. Assess condition based ONLY on visible evidence in the photos, using this exact scale:
   - "new": deadstock, unworn, tags/box condition
   - "like-new": worn a handful of times, no visible flaws
   - "good": light wear consistent with normal use — minor sole wear, slight creasing, no major flaws
   - "fair": noticeable wear — visible creasing, scuffs, sole wear, dirty midsole/outsole, but structurally sound
   - "worn": heavy wear — significant sole wear, discoloration, damage, stains, or structural issues

Be honest and specific. If the photos don't clearly show certain areas (e.g. outsole), say so \
in your notes rather than guessing. If you cannot confidently identify the exact model, say so \
and give your best general category guess (e.g. "running shoe, brand unclear") instead of inventing \
a specific model name.

Respond with ONLY a JSON object (no markdown fences, no preamble) matching this schema:
{
  "is_footwear": boolean,
  "brand": string,
  "model": string,
  "colorway": string or null,
  "identification_confidence": "high" | "medium" | "low",
  "condition": one of ["new", "like-new", "good", "fair", "worn"],
  "condition_confidence": "high" | "medium" | "low",
  "visible_flaws": [list of short strings describing specific visible wear/damage, empty list if none],
  "notes": short string, e.g. caveats about photo angles/lighting limiting the assessment, or what the photo actually shows if not footwear
}"""


@dataclass
class ItemAssessment:
    brand: str
    model: str
    colorway: str | None
    identification_confidence: str
    condition: str
    condition_confidence: str
    is_footwear: bool = True
    visible_flaws: list[str] = field(default_factory=list)
    notes: str = ""
    raw: dict = field(default_factory=dict)


def _image_block(image_bytes: bytes, media_type: str) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.b64encode(image_bytes).decode("utf-8"),
        },
    }


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def assess_item(
    images: list[tuple[bytes, str]],
    user_description: str = "",
    allow_non_footwear: bool = False,
) -> ItemAssessment:
    """
    images: list of (image_bytes, media_type) tuples, media_type like "image/jpeg"
    user_description: free-text hint from the user, e.g. "Nike Air Max 90, size 10"
    allow_non_footwear: if False (default), raises NotFootwearError when the model
        determines the photos aren't footwear, instead of silently continuing the
        pipeline (which would waste an eBay lookup + a listing-generation call on
        nonsense comps).
    """
    if not images:
        raise ValueError("At least one image is required.")
    if len(images) > 3:
        images = images[:3]

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    content = [_image_block(b, mt) for b, mt in images]
    user_text = "Identify this item and assess its condition."
    if user_description.strip():
        user_text += f"\n\nUser-provided description/hints: {user_description.strip()}"
    content.append({"type": "text", "text": user_text})

    try:
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError as e:
        raise AIServiceError(
            "The AI service rejected the request due to an authentication problem. "
            "This is a configuration issue on our end, not something you can fix -- "
            "please try again later."
        ) from e
    except anthropic.RateLimitError as e:
        raise AIServiceError(
            "The AI service is temporarily rate-limited. Please wait a minute and try again."
        ) from e
    except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
        raise AIServiceError(
            "Couldn't reach the AI service in time (connection or timeout issue). "
            "Please check your connection and try again."
        ) from e
    except anthropic.APIStatusError as e:
        raise AIServiceError(
            "The AI service returned an error while analyzing your photos. Please try again."
        ) from e
    except anthropic.APIError as e:
        raise AIServiceError(
            "Something went wrong talking to the AI service. Please try again."
        ) from e

    text_out = "".join(block.text for block in response.content if block.type == "text")
    cleaned = _strip_json_fences(text_out)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise AIServiceError(
            "The AI service returned a response we couldn't understand. Please try again "
            "-- if it keeps happening, try a different photo."
        ) from e

    assessment = ItemAssessment(
        brand=parsed.get("brand", "Unknown"),
        model=parsed.get("model", "Unknown"),
        colorway=parsed.get("colorway"),
        identification_confidence=parsed.get("identification_confidence", "low"),
        condition=parsed.get("condition", "good"),
        condition_confidence=parsed.get("condition_confidence", "low"),
        is_footwear=bool(parsed.get("is_footwear", True)),
        visible_flaws=parsed.get("visible_flaws", []),
        notes=parsed.get("notes", ""),
        raw=parsed,
    )

    if not assessment.is_footwear and not allow_non_footwear:
        detail = f" Our best guess at what's in the photo: {assessment.notes}" if assessment.notes else ""
        raise NotFootwearError(
            "These photos don't look like they show a shoe or sneaker, so we stopped here "
            "instead of generating a price/listing for the wrong item." + detail
        )

    return assessment
