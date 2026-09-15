"""PyMuPDF page access for the existing reader; no separate extraction pipeline."""

import unicodedata

import pymupdf as fitz
from PIL import Image

from .parser import normalize

MAX_RENDER_SIDE = 3200


def normalized_box(box, rect):
    return [
        round(max(0, min(1, value)), 5)
        for value in (
            (box.x0 - rect.x0) / rect.width,
            (box.y0 - rect.y0) / rect.height,
            (box.x1 - rect.x0) / rect.width,
            (box.y1 - rect.y0) / rect.height,
        )
    ]


def native_tokens(page, number):
    # Characters preserve MuPDF's Unicode ordering, including Arabic shaping.
    # A spatial jump separates label/value cells even when the PDF omits a space.
    raw = page.get_text("rawdict", flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)
    unrotated = page.rect * page.derotation_matrix
    tokens = []

    def emit(chars):
        if not chars:
            return
        text = normalize("".join(char["c"] for char in chars))
        if not text:
            return
        box = fitz.Rect(chars[0]["bbox"])
        for char in chars[1:]:
            box |= fitz.Rect(char["bbox"])
        tokens.append(
            {
                "text": text,
                "confidence": None,
                "page": number,
                "source": "PDF_TEXT",
                "bbox": normalized_box(box * page.rotation_matrix, page.rect),
                "layout_bbox": normalized_box(box, unrotated),
            }
        )
        if len(tokens) > 2500:
            raise ValueError("TEXT_LIMIT_EXCEEDED")

    for block in raw["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = []
                for char in span["chars"]:
                    if char["c"].isspace():
                        emit(chars)
                        chars = []
                        continue
                    if chars:
                        before, after = fitz.Rect(chars[-1]["bbox"]), fitz.Rect(char["bbox"])
                        gap = max(after.x0 - before.x1, before.x0 - after.x1)
                        if gap > max(2, span["size"] * 0.4):
                            emit(chars)
                            chars = []
                    chars.append(char)
                emit(chars)
    return tokens


def image_coverage(page):
    """Union of displayed raster areas; a small logo must not trigger OCR."""
    viewport = page.rect * page.derotation_matrix
    rectangles = []
    for image in page.get_image_info():
        # Ignore tiny placeholders and masks stretched to cover a page.
        if image["width"] < 32 or image["height"] < 32:
            continue
        box = fitz.Rect(image["bbox"]) & viewport
        if not box.is_empty:
            rectangles.append(box)
        if len(rectangles) > 1000:
            return 1.0
    edges = sorted({x for box in rectangles for x in (box.x0, box.x1)})
    area = 0.0
    for left, right in zip(edges, edges[1:]):
        intervals = sorted(
            (box.y0, box.y1) for box in rectangles if box.x0 < right and box.x1 > left
        )
        covered, end = 0.0, -float("inf")
        for top, bottom in intervals:
            covered += max(0, bottom - max(top, end))
            end = max(end, bottom)
        area += (right - left) * covered
    return min(1.0, area / viewport.get_area())


def page_route(tokens, coverage, *, direct_failed=False):
    if direct_failed:
        return "OCR", "DIRECT_EXTRACTION_FAILED"
    if coverage >= 0.55:
        return "OCR", "MAINLY_SCANNED"
    text = "".join(token["text"] for token in tokens)
    if not text:
        return "OCR", "NO_SEARCHABLE_TEXT"
    invalid = sum(
        char == "\ufffd" or unicodedata.category(char) in {"Co", "Cc", "Cs"} for char in text
    )
    if invalid / len(text) > 0.05 or not any(char.isalnum() for char in text):
        return "OCR", "UNUSABLE_TEXT"
    return "PDF_TEXT", "SEARCHABLE_TEXT"


def render_page(page, *, ocr):
    # 300 DPI for scanned pages, capped at 3200 px to bound memory and latency.
    dpi, side = (300, MAX_RENDER_SIDE) if ocr else (180, 2200)
    scale = min(dpi / 72, side / max(page.rect.width, page.rect.height))
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
