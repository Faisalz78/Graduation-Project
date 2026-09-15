"""Conservative small-angle deskew; evidence coordinates stay on the original image."""

import math
from statistics import median

import cv2
import numpy as np


def deskew(picture):
    cv2.setNumThreads(2)
    height, width = picture.shape[:2]
    edges = cv2.Canny(cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY), 15, 45)
    detected = cv2.HoughLinesP(
        edges, 1, np.pi / 1800, 80, minLineLength=width * 0.25, maxLineGap=30
    )
    angles = []
    if detected is not None:
        for x1, y1, x2, y2 in detected[:, 0, :]:
            angle = math.degrees(math.atan2(float(y2 - y1), float(x2 - x1)))
            if abs(angle) <= 7:
                angles.append(angle)
    angle = median(angles) if len(angles) >= 3 else 0.0
    # A photographed page has slightly different baselines across its perspective.
    # Accept a dominant narrow cluster, but reject competing page/background directions.
    if angles and sum(abs(value - angle) <= 1.8 for value in angles) / len(angles) < 0.8:
        angle = 0.0
    if abs(angle) < 0.3:
        return picture, np.array([[1.0, 0, 0], [0, 1.0, 0]]), 0.0
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
    radians = math.radians(angle)
    new_width = math.ceil(width * abs(math.cos(radians)) + height * abs(math.sin(radians)))
    new_height = math.ceil(height * abs(math.cos(radians)) + width * abs(math.sin(radians)))
    matrix[:, 2] += [(new_width - width) / 2, (new_height - height) / 2]
    corrected = cv2.warpAffine(
        picture, matrix, (new_width, new_height), borderValue=(255, 255, 255)
    )
    return corrected, cv2.invertAffineTransform(matrix), float(angle)


def prepare_image(picture):
    corrected, inverse, angle = deskew(picture)
    # Small photographed table cells benefit from interpolation before detection.
    # Keep the transform so evidence still points to the untouched uploaded file.
    scale = min(1.5, 3200 / max(corrected.shape[:2])) if abs(angle) >= 0.3 else 1.0
    if scale > 1:
        corrected = cv2.resize(corrected, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        inverse[:, :2] /= scale
    return corrected, inverse, angle


def original_box(box, inverse, width, height):
    x0, y0, x1, y1 = box
    corners = np.array([[x0, y0, 1], [x1, y0, 1], [x1, y1, 1], [x0, y1, 1]])
    mapped = corners @ inverse.T
    return [
        round(float(np.clip(mapped[:, 0].min() / width, 0, 1)), 5),
        round(float(np.clip(mapped[:, 1].min() / height, 0, 1)), 5),
        round(float(np.clip(mapped[:, 0].max() / width, 0, 1)), 5),
        round(float(np.clip(mapped[:, 1].max() / height, 0, 1)), 5),
    ]
