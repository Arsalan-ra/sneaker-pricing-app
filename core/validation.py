"""
Validates that uploaded bytes are actually a readable image before they're
sent anywhere (Claude API, etc). Streamlit's file_uploader `type=[...]` filter
only checks file extension, not content, so a renamed non-image file would
otherwise pass the picker and fail deep inside the pipeline.
"""

import io

from PIL import Image, UnidentifiedImageError

from core.errors import InvalidImageError

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB, comfortably above typical phone photos
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_image_bytes(data: bytes, filename: str = "upload") -> str:
    """
    Validates image bytes and returns a normalized media_type string
    (e.g. "image/jpeg") on success. Raises InvalidImageError on failure.
    """
    if not data:
        raise InvalidImageError(f"'{filename}' is empty and can't be used.")

    if len(data) > MAX_IMAGE_BYTES:
        size_mb = len(data) / (1024 * 1024)
        raise InvalidImageError(
            f"'{filename}' is {size_mb:.1f} MB, which is over the 10 MB limit. "
            "Try a smaller photo or compress it first."
        )

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()  # checks the file is a valid, uncorrupted image
        # verify() closes the file handle, so reopen to read format after verifying
        img2 = Image.open(io.BytesIO(data))
        fmt = (img2.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise InvalidImageError(
            f"'{filename}' doesn't look like a valid image file. "
            "Please upload a JPEG, PNG, or WEBP photo."
        ) from e

    if fmt not in ALLOWED_FORMATS:
        raise InvalidImageError(
            f"'{filename}' is a {fmt or 'unrecognized'} file. "
            "Please upload a JPEG, PNG, or WEBP photo."
        )

    media_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[fmt]
    return media_type
