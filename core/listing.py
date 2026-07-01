"""
Generates marketplace-ready title + description from the item assessment
and price recommendation.
"""

import json
import re

import anthropic

from core import config
from core.errors import AIServiceError
from core.pricing import PriceRecommendation
from core.vision import ItemAssessment

_SYSTEM_PROMPT = """You write concise, honest, high-converting marketplace listings for resold \
sneakers/shoes (eBay/Depop/Grailed style). No hype, no fake urgency, no emoji spam. Be accurate \
to the condition described -- never oversell flaws as "barely noticeable" if they were flagged \
as visible. Buyers trust specific, factual descriptions more than vague superlatives.

Respond with ONLY a JSON object (no markdown fences):
{
  "title": string, max 80 characters, keyword-forward for search (brand, model, colorway, size if known, condition),
  "description": string, 3-5 short paragraphs or a paragraph + bullet list covering: what it is, \
condition detail (mention specific flaws if any), sizing note if relevant, and a brief note on price fairness,
  "suggested_tags": [list of 5-8 short search keywords]
}"""


def generate_listing(
    assessment: ItemAssessment,
    price_rec: PriceRecommendation,
    size: str = "",
    extra_notes: str = "",
) -> dict:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    item_desc = f"{assessment.brand} {assessment.model}"
    if assessment.colorway:
        item_desc += f" in {assessment.colorway}"

    flaws = ", ".join(assessment.visible_flaws) if assessment.visible_flaws else "none noted"

    user_prompt = f"""Item: {item_desc}
Size: {size or "not specified"}
Condition: {assessment.condition} (confidence: {assessment.condition_confidence})
Visible flaws: {flaws}
Assessment notes: {assessment.notes or "none"}
Recommended price range: ${price_rec.low:.2f} - ${price_rec.high:.2f} (target ${price_rec.target:.2f})
Pricing strategy: {price_rec.strategy}
Extra notes from seller: {extra_notes or "none"}

Write the listing."""

    try:
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.AuthenticationError as e:
        raise AIServiceError(
            "The AI service rejected the request due to an authentication problem. "
            "This is a configuration issue on our end -- please try again later."
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
    except anthropic.APIError as e:
        raise AIServiceError(
            "Something went wrong generating the listing copy. Please try again."
        ) from e

    text_out = "".join(block.text for block in response.content if block.type == "text")
    cleaned = re.sub(r"^```(json)?|```$", "", text_out.strip()).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise AIServiceError(
            "The AI service returned a response we couldn't understand. Please try again."
        ) from e
