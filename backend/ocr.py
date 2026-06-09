"""Best-effort OCR for uploaded screenshots, so the chat can read an image
question (an error dialog, a doculoket row, a log excerpt). Extracted text is
fed back into the normal chat pipeline — including document-id detection — so a
screenshot containing a UUID is traced automatically.

Provider-agnostic and offline (Tesseract): no vision model required.
"""
import base64
import binascii
import io
import logging

import pytesseract
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# Guard against decompression-bomb images.
Image.MAX_IMAGE_PIXELS = 40_000_000

_MAX_BYTES = 12 * 1024 * 1024  # reject anything over ~12 MB of decoded image data
_LANGS = "eng+nld"             # KOOP documents are Dutch; errors/logs are English


def _decode(data_url_or_b64: str) -> bytes:
    """Accept a raw base64 string or a `data:image/...;base64,XXXX` data URL."""
    payload = data_url_or_b64
    if "," in payload and payload.strip().lower().startswith("data:"):
        payload = payload.split(",", 1)[1]
    return base64.b64decode(payload, validate=False)


def _preprocess(img: "Image.Image") -> "Image.Image":
    """Improve OCR accuracy on UI screenshots: flatten transparency, convert to
    grayscale, and upscale small images (Tesseract reads ~300 DPI text best, but
    UI screenshots are ~96 DPI — upscaling sharpens IDs and small fonts)."""
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    img = img.convert("L")  # grayscale
    if img.width < 1600:
        scale = max(2, round(1600 / max(img.width, 1)))
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    return img


def image_to_text(data_url_or_b64: str) -> str:
    """Return the text Tesseract reads from the image, or "" on any failure.
    Never raises — a bad image must not break a chat request."""
    if not data_url_or_b64:
        return ""
    try:
        raw = _decode(data_url_or_b64)
    except (binascii.Error, ValueError) as e:
        logger.warning(f"OCR: could not base64-decode image: {e}")
        return ""
    if len(raw) > _MAX_BYTES:
        logger.warning(f"OCR: image too large ({len(raw)} bytes), skipping")
        return ""
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            text = pytesseract.image_to_string(_preprocess(img), lang=_LANGS)
    except (UnidentifiedImageError, OSError) as e:
        logger.warning(f"OCR: not a readable image: {e}")
        return ""
    except pytesseract.TesseractError as e:
        logger.error(f"OCR: tesseract failed: {e}")
        return ""
    # Normalise whitespace; drop empty lines for a tidy prompt.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines).strip()
