"""
App-specific exceptions. Each one carries a friendly, user-safe message
separate from any underlying technical detail, so the UI layer never has
to decide on the fly how much of a raw exception is safe to show someone.

Pattern: raise these with the friendly message as the exception text, and
optionally attach the original exception via `from e` for server-side logs.
The UI should show str(exc) directly for any of these -- never the caught
generic Exception's raw text.
"""


class AppError(Exception):
    """Base class for all handled, user-facing errors in this app."""


class InvalidImageError(AppError):
    """Raised when an uploaded file isn't a valid, readable image."""


class NotFootwearError(AppError):
    """Raised when the vision model confidently determines the image isn't footwear."""


class AIServiceError(AppError):
    """Raised when the Claude API call fails (auth, timeout, rate limit, connection, bad response)."""


class CompDataError(AppError):
    """Raised when the eBay comp lookup fails or is misconfigured."""


class NoCompsFoundError(AppError):
    """Raised when a comp lookup succeeds but returns zero results."""


class RateLimitExceededError(AppError):
    """Raised when a user hits the local session request cap or cooldown window."""
