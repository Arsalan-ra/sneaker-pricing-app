import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PIL import Image

from core.errors import InvalidImageError
from core.validation import MAX_IMAGE_BYTES, validate_image_bytes


def _make_valid_jpeg_bytes() -> bytes:
    img = Image.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_valid_png_bytes() -> bytes:
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_valid_jpeg_passes():
    media_type = validate_image_bytes(_make_valid_jpeg_bytes(), "shoe.jpg")
    assert media_type == "image/jpeg"


def test_valid_png_passes():
    media_type = validate_image_bytes(_make_valid_png_bytes(), "shoe.png")
    assert media_type == "image/png"


def test_empty_file_rejected():
    with pytest.raises(InvalidImageError):
        validate_image_bytes(b"", "empty.jpg")


def test_renamed_text_file_rejected():
    """Simulates a .txt file renamed to .jpg -- extension lies, content doesn't validate."""
    fake_bytes = b"this is definitely not an image, just plain text pretending to be one"
    with pytest.raises(InvalidImageError):
        validate_image_bytes(fake_bytes, "not_really_a_photo.jpg")


def test_pdf_bytes_rejected():
    """Simulates a PDF renamed with an image extension."""
    fake_pdf = b"%PDF-1.4\n%fake pdf content\n"
    with pytest.raises(InvalidImageError):
        validate_image_bytes(fake_pdf, "document.png")


def test_oversized_image_rejected():
    oversized = b"\xff\xd8\xff" + (b"0" * (MAX_IMAGE_BYTES + 1))
    with pytest.raises(InvalidImageError):
        validate_image_bytes(oversized, "huge.jpg")


def test_error_message_mentions_filename():
    try:
        validate_image_bytes(b"garbage", "my_photo.jpg")
    except InvalidImageError as e:
        assert "my_photo.jpg" in str(e)
    else:
        pytest.fail("Expected InvalidImageError")
