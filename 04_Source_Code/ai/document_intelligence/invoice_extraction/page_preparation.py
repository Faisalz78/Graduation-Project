"""Camera orientation and conservative ruled-page dewarping, with reversible geometry."""

import os
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

from .camera import document_view

ORIENTATION = "PP-LCNet_x1_0_doc_ori"


@lru_cache(maxsize=1)
def orientation_model(download=False):
    from .reader import CACHE, MODELS

    os.environ["PADDLE_PDX_CACHE_HOME"] = str(CACHE)
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["PADDLE_PDX_MODEL_SOURCE"] = "BOS"
    location = MODELS / ORIENTATION
    if not download and not (location / "inference.pdiparams").is_file():
        raise ValueError("ORIENTATION_MODEL_NOT_INSTALLED")
    from paddlex import create_model

    return create_model(
        model_name=ORIENTATION,
        model_dir=str(location) if location.exists() else None,
        device="cpu",
        cpu_threads=4,
        enable_mkldnn=False,
    )


def straighten_curves(picture):
    """Flatten only repeated agreeing curved rules; never infer geometry from isolated text."""
    width, height = picture.size
    scale = min(1, 1400 / max(width, height))
    gray = cv2.cvtColor(np.asarray(picture), cv2.COLOR_RGB2GRAY)
    small = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
    ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    rules = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, 21), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(rules)
    curves = []
    sw, sh = small.shape[1], small.shape[0]
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if w < sw * 0.65 or h > sh * 0.1 or area / w > 8:
            continue
        ys, xs = np.where(labels == label)
        columns = np.unique(xs)
        if len(columns) < w * 0.85:
            continue
        centers = np.array([np.median(ys[xs == col]) for col in columns])
        fit = np.polyfit(columns / (sw - 1), centers, 2)
        if np.median(np.abs(np.polyval(fit, columns / (sw - 1)) - centers)) > 1.5:
            continue
        # Strip offset and linear skew; these are handled by orientation/deskew.
        curve = fit[0] * (np.linspace(0, 1, sw) ** 2 - np.linspace(0, 1, sw))
        if 0.003 * sh < np.ptp(curve) < 0.04 * sh:
            curves.append(curve)
    if len(curves) < 3:
        return picture, np.zeros(width, np.float32), False
    curves = np.asarray(curves)
    median = np.median(curves, axis=0)
    agreeing = curves[np.max(np.abs(curves - median), axis=1) < 0.003 * sh]
    if len(agreeing) < 3:
        return picture, np.zeros(width, np.float32), False
    offsets = (
        np.interp(np.linspace(0, sw - 1, width), np.arange(sw), np.median(agreeing, axis=0)) / scale
    )
    # Keep both ends inside the original; don't crop away text at page boundaries.
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    fade = np.minimum(1, np.minimum(yy, height - 1 - yy) / max(1, 0.08 * height))
    map_y = yy + offsets.astype(np.float32)[None, :] * fade
    result = cv2.remap(
        np.asarray(picture), xx, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return Image.fromarray(result), offsets.astype(np.float32), True


def prepare_page(picture):
    angle, warnings = 0, []
    try:
        preview = picture.copy()
        preview.thumbnail((1400, 1400))
        result = next(iter(orientation_model().predict(np.asarray(preview)[:, :, ::-1].copy())))
        predicted = int(result["label_names"][0])
        if float(result["scores"][0]) >= 0.95 and predicted in (0, 90, 180, 270):
            angle = predicted
        else:
            warnings.append("PAGE_ORIENTATION_UNCERTAIN")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, StopIteration):
        warnings.append("PAGE_ORIENTATION_UNAVAILABLE")
    rotated = picture.rotate(angle, expand=True)
    prepared, inverse, method = document_view(rotated)
    prepared, offsets, curved = straighten_curves(prepared)

    def map_box(box):
        x0, y0, x1, y1 = box
        # Sample curved edges, not just corners; evidence encloses the full original region.
        xx, yy = np.meshgrid(np.linspace(x0, x1, 25), np.linspace(y0, y1, 5))
        points = np.stack([xx.ravel() * prepared.width, yy.ravel() * prepared.height], axis=1)
        delta = np.interp(points[:, 0], np.arange(len(offsets)), offsets)
        fade = np.clip(
            np.minimum(points[:, 1], prepared.height - 1 - points[:, 1])
            / max(1, 0.08 * prepared.height),
            0,
            1,
        )
        points[:, 1] += delta * fade
        points = cv2.perspectiveTransform(points.astype(np.float32)[None], inverse)[0]
        x, y = points[:, 0] / rotated.width, points[:, 1] / rotated.height
        if angle == 90:
            x, y = 1 - y, x
        elif angle == 180:
            x, y = 1 - x, 1 - y
        elif angle == 270:
            x, y = y, 1 - x
        return [round(float(np.clip(v, 0, 1)), 5) for v in (x.min(), y.min(), x.max(), y.max())]

    return (
        prepared,
        map_box,
        {"method": method, "rotation": angle, "curvature_corrected": curved},
        warnings,
    )
