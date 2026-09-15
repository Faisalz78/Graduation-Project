"""Conservative document perspective correction with original-coordinate evidence."""

import cv2
import numpy as np
from PIL import Image


def document_view(picture):
    original = np.asarray(picture.convert("RGB"))
    height, width = original.shape[:2]
    scale = min(1, 1200 / max(width, height))
    small = cv2.resize(original, None, fx=scale, fy=scale) if scale < 1 else original
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        polygon = cv2.approxPolyDP(contour, 0.025 * cv2.arcLength(contour, True), True)
        coverage = cv2.contourArea(polygon) / (small.shape[0] * small.shape[1])
        if len(polygon) != 4 or not cv2.isContourConvex(polygon) or not 0.55 < coverage < 0.95:
            continue
        mask = np.zeros(gray.shape, dtype=np.uint8)
        cv2.fillConvexPoly(mask, polygon, 255)
        inside, outside = gray[mask > 0], gray[mask == 0]
        # A table border on white paper is not a document edge.
        if float(inside.mean()) - float(outside.mean()) < 18 or (inside > 175).mean() < 0.65:
            continue
        points = polygon[:, 0, :].astype(np.float32) / scale
        sums, differences = points.sum(axis=1), np.diff(points, axis=1).ravel()
        source = np.array(
            [
                points[sums.argmin()],
                points[differences.argmin()],
                points[sums.argmax()],
                points[differences.argmax()],
            ],
            dtype=np.float32,
        )
        if len(np.unique(source, axis=0)) != 4:
            continue
        target_width = round(
            max(np.linalg.norm(source[1] - source[0]), np.linalg.norm(source[2] - source[3]))
        )
        target_height = round(
            max(np.linalg.norm(source[3] - source[0]), np.linalg.norm(source[2] - source[1]))
        )
        if min(target_width, target_height) < 300:
            continue
        destination = np.float32(
            [
                [0, 0],
                [target_width - 1, 0],
                [target_width - 1, target_height - 1],
                [0, target_height - 1],
            ]
        )
        matrix = cv2.getPerspectiveTransform(source, destination)
        transformed = cv2.warpPerspective(
            original, matrix, (target_width, target_height), borderValue=(255, 255, 255)
        )
        return Image.fromarray(transformed), np.linalg.inv(matrix), "PERSPECTIVE_CORRECTED"
    return picture.copy(), np.eye(3), "ORIGINAL"


def restore_tokens(tokens, inverse, processed_size, original_size):
    pw, ph = processed_size
    ow, oh = original_size
    for token in tokens:
        x0, y0, x1, y1 = token["bbox"]
        corners = np.float32(
            [[[x0 * pw, y0 * ph], [x1 * pw, y0 * ph], [x1 * pw, y1 * ph], [x0 * pw, y1 * ph]]]
        )
        mapped = cv2.perspectiveTransform(corners, inverse)[0]
        token["bbox"] = [
            round(float(np.clip(mapped[:, 0].min() / ow, 0, 1)), 5),
            round(float(np.clip(mapped[:, 1].min() / oh, 0, 1)), 5),
            round(float(np.clip(mapped[:, 0].max() / ow, 0, 1)), 5),
            round(float(np.clip(mapped[:, 1].max() / oh, 0, 1)), 5),
        ]
    return tokens


def quality(picture):
    gray = cv2.cvtColor(np.asarray(picture.convert("RGB")), cv2.COLOR_RGB2GRAY)
    return {
        "width": picture.width,
        "height": picture.height,
        "sharpness": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
        "dark_fraction": round(float((gray < 35).mean()), 4),
    }


def reread_uncertain(picture, tokens, language, recognizer):
    """One bounded crop pass; keep alternative OCR reads for evidence, never overwrite."""
    attempted = 0
    for token in sorted(tokens, key=lambda t: t.get("confidence") or 0):
        if attempted >= 6:
            break
        if token.get("confidence") is None or token["confidence"] >= 0.82 or len(token["text"]) < 2:
            continue
        x0, y0, x1, y1 = token["bbox"]
        width, height = picture.size
        crop = picture.crop(
            (
                max(0, int(x0 * width) - 5),
                max(0, int(y0 * height) - 4),
                min(width, int(x1 * width) + 5),
                min(height, int(y1 * height) + 4),
            )
        )
        if min(crop.size) < 3:
            continue
        scale = min(3, 1200 / max(crop.size))
        crop = crop.resize(
            (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
            Image.Resampling.LANCZOS,
        )
        attempted += 1
        from .parser import normalize

        predictions = recognizer(language).predict(np.asarray(crop)[:, :, ::-1].copy())[0]
        if len(predictions["rec_texts"]) != 1 or float(predictions["rec_scores"][0]) < 0.9:
            continue
        alternative = normalize(predictions["rec_texts"][0])
        if alternative and len(alternative) <= 500:
            token["recognition_reads"] = list(
                dict.fromkeys([token["text"], *token.get("recognition_reads", []), alternative])
            )[:30]
    return attempted
