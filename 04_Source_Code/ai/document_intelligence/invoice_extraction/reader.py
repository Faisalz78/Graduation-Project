import os
import time
from functools import lru_cache
from pathlib import Path

from .parser import VERSION as PARSER_VERSION
from .parser import layout_box, lines, normalize, parse
from .pdf_text import image_coverage, native_tokens, page_route, render_page
from .structured_sources import (
    MAX_STRUCTURED_SOURCES,
    embedded_xml_sources,
    merge_structured,
    parse_ubl_xml,
    qr_sources,
)

ROOT = Path(__file__).resolve().parents[4]
CACHE = ROOT / ".local/ocr-cache"
MODELS = CACHE / "official_models"
DETECTION = "PP-OCRv5_mobile_det"
RECOGNITION = {"ar": "arabic_PP-OCRv5_mobile_rec", "en": "en_PP-OCRv5_mobile_rec"}
MAX_PAGES = 3
MAX_TOKENS = 2500


@lru_cache(maxsize=2)
def model(language, download=False):
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(CACHE)
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["PADDLE_PDX_MODEL_SOURCE"] = "BOS"
    if language not in RECOGNITION:
        raise ValueError("UNSUPPORTED_LANGUAGE")
    paths = [MODELS / DETECTION, MODELS / RECOGNITION[language]]
    if not download and not all((path / "inference.pdiparams").is_file() for path in paths):
        raise ValueError("OCR_MODELS_NOT_INSTALLED")
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_name=DETECTION,
        text_recognition_model_name=RECOGNITION[language],
        text_detection_model_dir=str(paths[0]) if paths[0].exists() else None,
        text_recognition_model_dir=str(paths[1]) if paths[1].exists() else None,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device="cpu",
        cpu_threads=4,
        enable_mkldnn=False,
        text_det_limit_side_len=2200,
        text_det_limit_type="max",
    )


def ocr_tokens(picture, language, page):
    import numpy as np

    from .geometry import original_box, prepare_image
    from .mixed_script import supplement, supplement_latin

    width, height = picture.size
    # Paddle's numpy inputs follow OpenCV's BGR convention.
    corrected, inverse, angle = prepare_image(np.array(picture.convert("RGB"))[:, :, ::-1].copy())
    corrected_height, corrected_width = corrected.shape[:2]
    options = (
        dict(text_det_limit_side_len=3200, text_det_thresh=0.2, text_det_box_thresh=0.4)
        if abs(angle) >= 0.3
        else {}
    )
    result = model(language).predict(corrected, **options)[0]
    tokens = []
    for text, score, box in zip(result["rec_texts"], result["rec_scores"], result["rec_boxes"]):
        if not text.strip():
            continue
        tokens.append(
            {
                "text": normalize(text),
                "confidence": round(float(score), 4),
                "bbox": original_box(box, inverse, width, height),
                "layout_bbox": [
                    round(float(box[0]) / corrected_width, 5),
                    round(float(box[1]) / corrected_height, 5),
                    round(float(box[2]) / corrected_width, 5),
                    round(float(box[3]) / corrected_height, 5),
                ],
                "deskew_degrees": round(angle, 4),
                "page": page,
                "source": "OCR",
            }
        )
    if language == "ar":
        supplement(tokens, corrected)
        supplement_latin(tokens, corrected)
    return tokens


def reading_order(tokens):
    ordered = []
    text_lines = []
    for line_index, group in enumerate(lines(tokens), 1):
        rtl = any(
            any("\u0600" <= c <= "\u06ff" for c in token["text"]) for token in group["tokens"]
        )
        row = sorted(group["tokens"], key=lambda token: layout_box(token)[0], reverse=rtl)
        for token in row:
            token["reading_order"] = len(ordered) + 1
            token["line_number"] = line_index
            ordered.append(token)
        text_lines.append(" ".join(token["text"] for token in row))
    return ordered, "\n".join(text_lines)


def read_document(path: Path, language: str, *, use_local_vision=False):
    import pymupdf as fitz
    from PIL import Image, ImageOps

    started = time.perf_counter()
    tokens = []
    reader_sources = []
    structured_sources = []
    xml_item_sets = []
    structured_warnings = []
    pages = 1
    page_routes = []
    vision_pages = []
    image_preparation = []
    coordinate_maps = {}

    def prepare_picture(picture, number):
        if not use_local_vision:
            return picture
        from .page_preparation import prepare_page

        prepared, mapper, preparation, warnings = prepare_page(picture)
        coordinate_maps[number] = mapper
        image_preparation.append({"page": number, "reread_regions": 0, **preparation})
        structured_warnings.extend(warnings)
        return prepared

    region_cache = {}

    def reread_region(number, picture, box, header):
        import math

        if next(route["method"] for route in page_routes if route["page"] == number) != "OCR":
            return []
        found = []
        for bounds in [header, box] if header else [box]:
            if time.perf_counter() - started > 360:
                raise ValueError("REGION_TIME_LIMIT")
            rect = (
                int(bounds[0] * picture.width),
                int(bounds[1] * picture.height),
                min(picture.width, math.ceil(bounds[2] * picture.width)),
                min(picture.height, math.ceil(bounds[3] * picture.height)),
            )
            key = (number, rect)
            if key not in region_cache:
                crop = picture.crop(rect)
                result = ocr_tokens(crop, language, number)
                for token in result:
                    x0, y0, x1, y1 = token["bbox"]
                    token["bbox"] = [
                        (rect[0] + x0 * crop.width) / picture.width,
                        (rect[1] + y0 * crop.height) / picture.height,
                        (rect[0] + x1 * crop.width) / picture.width,
                        (rect[1] + y1 * crop.height) / picture.height,
                    ]
                    token["layout_bbox"] = token["bbox"].copy()
                region_cache[key] = result
            found.extend(region_cache[key])
        return found

    if language not in RECOGNITION:
        raise ValueError("UNSUPPORTED_LANGUAGE")
    if path.suffix.lower() == ".xml":
        source, items = parse_ubl_xml(path.read_bytes())
        structured_sources.append(source)
        xml_item_sets.append(items)
        reader_sources.append("XML")
    elif path.suffix.lower() == ".pdf":
        xml_sources, embedded_items, warnings = embedded_xml_sources(path)
        structured_sources.extend(xml_sources)
        xml_item_sets.extend(embedded_items)
        structured_warnings.extend(warnings)
        if xml_sources:
            reader_sources.append("XML")
        with fitz.open(path) as document:
            if document.needs_pass:
                raise ValueError("PASSWORD_PROTECTED_PDF")
            pages = len(document)
            if not 1 <= pages <= MAX_PAGES:
                raise ValueError("PAGE_LIMIT_EXCEEDED")
            for number, page in enumerate(document, 1):
                native, direct_failed = [], False
                try:
                    native = native_tokens(page, number)
                except (RuntimeError, ValueError) as exc:
                    if str(exc) == "TEXT_LIMIT_EXCEEDED":
                        raise
                    direct_failed = True
                coverage = image_coverage(page)
                method, reason = page_route(native, coverage, direct_failed=direct_failed)
                picture = render_page(page, ocr=method == "OCR")
                qr, warnings = qr_sources(picture, number)
                structured_sources.extend(qr)
                structured_warnings.extend(warnings)
                if qr and "QR" not in reader_sources:
                    reader_sources.append("QR")
                # An actually blank XML wrapper needs no OCR, but attached XML must
                # never suppress reading visible scanned content for comparison.
                if method == "OCR" and not native and not coverage and not page.get_drawings():
                    extrema = picture.convert("L").getextrema()
                    if extrema[0] == extrema[1]:
                        method, reason = "BLANK", "BLANK_PAGE"
                if method == "OCR":
                    picture = prepare_picture(picture, number)
                page_tokens = (
                    native
                    if method == "PDF_TEXT"
                    else ocr_tokens(picture, language, number)
                    if method == "OCR"
                    else []
                )
                tokens.extend(page_tokens)
                if use_local_vision and method != "BLANK":
                    vision_pages.append((number, picture))
                if method != "BLANK" and method not in reader_sources:
                    reader_sources.append(method)
                page_routes.append(
                    {
                        "page": number,
                        "method": method,
                        "reason": reason,
                        "image_coverage": round(coverage, 4),
                    }
                )
                if len(tokens) > MAX_TOKENS:
                    raise ValueError("TEXT_LIMIT_EXCEEDED")
    elif path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        with Image.open(path) as original:
            if original.width * original.height > 20_000_000:
                raise ValueError("IMAGE_LIMIT_EXCEEDED")
            picture = ImageOps.exif_transpose(original).convert("RGB")
            if not use_local_vision:
                picture.thumbnail((2200, 2200))
        qr, warnings = qr_sources(picture, 1)
        structured_sources.extend(qr)
        structured_warnings.extend(warnings)
        if qr:
            reader_sources.append("QR")
        from .camera import document_view, quality, reread_uncertain, restore_tokens

        if use_local_vision:
            prepared = prepare_picture(picture, 1)
        else:
            prepared, inverse, preparation = document_view(picture)
        tokens = ocr_tokens(prepared, language, 1)
        if use_local_vision:
            try:
                image_preparation[-1]["reread_regions"] = reread_uncertain(
                    prepared, tokens, language, model
                )
            except (RuntimeError, ValueError, OSError):
                structured_warnings.append("CAMERA_REREAD_UNAVAILABLE")
        else:
            tokens = restore_tokens(tokens, inverse, prepared.size, picture.size)
            image_preparation.append({"page": 1, "method": preparation, "reread_regions": 0})
        metrics = quality(picture)
        if min(picture.size) < 600:
            structured_warnings.append("CAMERA_LOW_RESOLUTION")
        if metrics["sharpness"] < 25:
            structured_warnings.append("CAMERA_BLUR_POSSIBLE")
        if use_local_vision:
            vision_pages.append((1, prepared))
        reader_sources.append("OCR")
        page_routes.append(
            {"page": 1, "method": "OCR", "reason": "IMAGE_UPLOAD", "image_coverage": 1.0}
        )
    else:
        raise ValueError("UNSUPPORTED_FILE_TYPE")
    if len(tokens) > MAX_TOKENS or sum(len(token["text"]) for token in tokens) > 80_000:
        raise ValueError("TEXT_LIMIT_EXCEEDED")
    if len(structured_sources) > MAX_STRUCTURED_SOURCES:
        structured_sources = structured_sources[:MAX_STRUCTURED_SOURCES]
        structured_warnings.append("STRUCTURED_SOURCE_LIMIT_REACHED")
    if not tokens and not structured_sources and not (use_local_vision and vision_pages):
        raise ValueError("NO_TEXT_FOUND")
    tokens, text = reading_order(tokens)
    suggestions = (
        parse(tokens)
        if tokens
        else {
            "parser_version": PARSER_VERSION,
            "fields": {},
            "items": [],
            "warnings": [],
            "requires_human_review": True,
        }
    )
    if use_local_vision:
        from .local_vision import enhance

        suggestions = enhance(
            suggestions,
            vision_pages,
            tokens,
            budget=max(0, 380 - (time.perf_counter() - started)),
            reread=reread_region,
        )
    if not tokens and not structured_sources:
        raise ValueError("NO_TEXT_FOUND")
    tokens, text = reading_order(tokens)
    # Map all public evidence only after parsing and regional merging in upright coordinates.
    entries = [*tokens, *suggestions["fields"].values()]
    entries.extend(entry for row in suggestions["items"] for entry in row.values())
    entries.extend(
        entry
        for detail in suggestions.get("conflict_details", [])
        for entry in (detail["current"], detail["proposed"])
        if entry
    )
    entries.extend(suggestions.get("guided_reading", {}).get("regions", []))
    seen = set()
    for entry in entries:
        if id(entry) in seen:
            continue
        seen.add(id(entry))
        mapper = coordinate_maps.get(entry.get("page"))
        if mapper and entry.get("bbox"):
            entry["bbox"] = mapper(entry["bbox"])
    suggestions["warnings"] = sorted(set(suggestions["warnings"] + structured_warnings))
    suggestions = merge_structured(suggestions, structured_sources, xml_item_sets)
    return {
        "reader_version": "pymupdf-paddle-guided-v7",
        "language": language,
        "pages": pages,
        "sources": reader_sources,
        "seconds": round(time.perf_counter() - started, 3),
        "tokens": tokens,
        "text": text,
        "page_routes": page_routes,
        "image_preparation": image_preparation,
        **suggestions,
    }
