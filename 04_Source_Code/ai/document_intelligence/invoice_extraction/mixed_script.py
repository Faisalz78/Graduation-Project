"""Recover explicit Latin values from a second reading of an Arabic label crop."""

import re
from functools import lru_cache

from .parser import LABELS, key, label_match, normalize, value_for


def latin_value(field, text):
    patterns = {
        "invoice_date": r"(?<![\w-])\d{4}-\d{2}-\d{2}(?![\w-])",
        "currency": r"\b(?:SAR|AED|USD|EUR)\b",
        "invoice_number": r"(?<![\w/-])(?:[A-Z]{1,10}[-_/][A-Z0-9/_-]*\d[A-Z0-9/_-]*|\d{2,30})(?![\w/-])",
    }
    values = {
        value_for(field, value) for value in re.findall(patterns[field], normalize(text), re.I)
    }
    values.discard(None)
    return next(iter(values)) if len(values) == 1 else None


@lru_cache(maxsize=1)
def recognizer():
    from .reader import MODELS, RECOGNITION

    path = MODELS / RECOGNITION["en"]
    if not (path / "inference.pdiparams").is_file():
        raise ValueError("OCR_MODELS_NOT_INSTALLED")
    from paddleocr import TextRecognition

    return TextRecognition(
        model_name=RECOGNITION["en"],
        model_dir=str(path),
        device="cpu",
        cpu_threads=4,
        enable_mkldnn=False,
    )


def supplement(tokens, picture):
    height, width = picture.shape[:2]
    count = 0
    for token in tokens:
        for field in ("invoice_number", "invoice_date", "currency"):
            if not label_match(key(token["text"]), LABELS[field], approximate=True):
                continue
            if count >= 20:
                return
            count += 1
            box = token["layout_bbox"]
            x0, y0 = max(0, int(box[0] * width) - 2), max(0, int(box[1] * height) - 2)
            x1, y1 = min(width, int(box[2] * width) + 2), min(height, int(box[3] * height) + 2)
            if x1 <= x0 or y1 <= y0:
                continue
            result = recognizer().predict(picture[y0:y1, x0:x1])[0]
            value = latin_value(field, result["rec_text"])
            if value is None or float(result["rec_score"]) < 0.75:
                continue
            token["recognition_reads"] = [token["text"], normalize(result["rec_text"])]
            # Keep the recognized label; only separate a missing space between its words.
            canonical = next(
                label
                for label in LABELS[field]
                if label_match(token["text"], [label], approximate=True)
            )
            token["text"] = canonical + " " + value
            token["confidence"] = min(token["confidence"], round(float(result["rec_score"]), 4))
            token["supplemented_field"] = field
            break


def supplement_latin(tokens, picture):
    """Re-read small Latin headers and glyphs with the same PaddleOCR engine.

    Never replace an already valid number or invoice identifier with another guess.
    A numeric recovery requires a visible quantity column and retains both readings.
    """
    height, width = picture.shape[:2]
    selected, crops = [], []
    for token in tokens:
        text = token["text"]
        eligible = (
            bool(re.fullmatch(r"[A-Za-z –-]{1,24}", text))
            or bool(re.search(r"(?i)\bdate\W*\d", text))
            or bool(re.search(r"(?i)(?:[A-Za-z]+/فاتورة|^vat\s.{1,20}$)", text))
        )
        if not eligible or len(selected) >= 100:
            continue
        box = token["layout_bbox"]
        x0, y0 = max(0, int(box[0] * width) - 2), max(0, int(box[1] * height) - 2)
        x1, y1 = min(width, int(box[2] * width) + 2), min(height, int(box[3] * height) + 2)
        if x1 > x0 and y1 > y0:
            selected.append(token)
            crops.append(picture[y0:y1, x0:x1])
    if not crops:
        return
    # Small headers must not be padded to the aspect ratio of long neighboring text.
    readings = list(recognizer().predict(crops, batch_size=1))
    accepted_headers = {
        "qty",
        "quantity",
        "item description",
        "description",
        "unit",
        "price",
        "unit price",
        "disc",
        "discount",
        "net",
        "amount",
        "vat",
        "vat amt",
        "vat amount",
        "vat vat amt",
        "vat vat am",
        "total",
        "invoice/",
    }
    pending_digits = []
    for token, result in zip(selected, readings):
        text, score = normalize(result["rec_text"]), float(result["rec_score"])
        if score < 0.85 or text == token["text"]:
            continue
        if re.fullmatch(r"\d{1,4}(?:\.\d{1,4})?", text) and score >= 0.95:
            pending_digits.append((token, text, score))
            continue
        is_date = re.fullmatch(r"(?i)date\s*[/ :]\s*(.+)", text)
        if key(text) not in accepted_headers and not (
            is_date and value_for("invoice_date", is_date[1])
        ):
            continue
        retain_reading(token, text, score)
    quantity_headers = [t for t in tokens if key(t["text"]) in ("qty", "quantity", "الكمية")]
    for token, text, score in pending_digits:
        b = token["layout_bbox"]
        if any(
            t["page"] == token["page"]
            and 0 < b[1] - t["layout_bbox"][3] < 0.5
            and t["layout_bbox"][0] - 0.015 <= (b[0] + b[2]) / 2 <= t["layout_bbox"][2] + 0.015
            for t in quantity_headers
        ):
            retain_reading(token, text, score)


def retain_reading(token, text, score):
    token["recognition_reads"] = [token["text"], text]
    token["text"] = text
    token["confidence"] = min(token["confidence"], round(score, 4))
    token["supplemented_field"] = "mixed_text"
