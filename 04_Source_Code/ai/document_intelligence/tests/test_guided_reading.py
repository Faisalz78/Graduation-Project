import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np
import pymupdf
from invoice_extraction.local_vision import enhance, merge_page
from invoice_extraction.page_preparation import prepare_page, straighten_curves
from invoice_extraction.reader import read_document
from invoice_extraction.regions import locate, recover, region_view, sections
from PIL import Image
from test_local_vision import claim, empty
from test_parser import token


def report():
    return dict(added_fields=0, confirmed_fields=0, added_rows=0, conflicts=0, rejected_values=0)


def row_tokens(name, y):
    return [
        token(name, y=y, width=0.2),
        token("2", x=0.5, y=y, width=0.06),
        token("80.00", x=0.7, y=y, width=0.1),
    ]


def proposed_row(offset=0):
    return {
        "description": claim("Cable", offset + 1),
        "quantity": claim("2", offset + 2),
        "unit_price": claim("80.00", offset + 3),
    }


class GuidedReadingTests(unittest.TestCase):
    def test_dense_adjacent_rows_remain_separate(self):
        tokens = row_tokens("Cable", 0.3) + row_tokens("Cable", 0.31)
        for item in tokens:
            item["bbox"][3] = item["bbox"][1] + 0.004
        result = empty()
        merge_page(
            result, {"fields": {}, "items": [proposed_row(), proposed_row(3)]}, tokens, report()
        )
        self.assertEqual(len(result["items"]), 2)

    def test_location_validates_boxes_and_always_keeps_table(self):
        picture = Image.new("RGB", (100, 100))
        for invalid in (
            [-1, 0, 900, 900],
            [10, 900, 900, 100],
            [0, 0, 10, 10],
            [False, 0, 900, 900],
            [0, 0, float("nan"), 900],
        ):
            with patch(
                "invoice_extraction.local_vision.local_request",
                return_value={
                    "message": {
                        "content": json.dumps(
                            {"table": invalid, "header": [0, 0, 900, 200], "totals": None}
                        )
                    }
                },
            ):
                self.assertEqual(locate(picture, [], 5), [])
        with patch(
            "invoice_extraction.local_vision.local_request",
            return_value={
                "message": {
                    "content": json.dumps(
                        {"table": [0, 300, 900, 700], "header": [0, 0, 900, 200], "totals": None}
                    )
                }
            },
        ):
            regions = locate(picture, [], 5)
        self.assertEqual([r["kind"] for r in regions], ["TABLE"])

    def test_table_bands_cover_body_with_overlap_and_repeated_header(self):
        bands = sections({"kind": "TABLE", "bbox": [0.1, 0.1, 0.9, 0.9]})
        self.assertLessEqual(len(bands), 4)
        self.assertEqual(bands[0][0][1], bands[0][1][3])
        self.assertEqual(bands[-1][0][3], 0.9)
        for left, right in zip(bands, bands[1:]):
            self.assertGreater(left[0][3], right[0][1])
            self.assertEqual(left[1], right[1])

    def test_region_composition_keeps_original_evidence_and_localizes_model_boxes(self):
        tokens = [
            token("Heading", x=0.2, y=0.1, width=0.2),
            token("Cable", x=0.2, y=0.5, width=0.2),
            token("Outside", y=0.9),
        ]
        snapshot = copy.deepcopy(tokens)
        image, originals, local = region_view(
            Image.new("RGB", (1000, 1000)), [0.1, 0.45, 0.9, 0.7], [0.1, 0.08, 0.9, 0.15], tokens
        )
        self.assertEqual(len(originals), 2)
        self.assertEqual(tokens, snapshot)
        self.assertEqual(originals[1]["bbox"], tokens[1]["bbox"])
        self.assertLess(local[0]["bbox"][1], local[1]["bbox"][1])
        self.assertEqual(image.width, 800)

    def test_partial_tables_merge_by_location_and_do_not_duplicate_overlapping_bands(self):
        tokens = row_tokens("Cable", 0.3) + row_tokens("Cable", 0.6)
        result = empty()
        stats = report()
        merge_page(result, {"fields": {}, "items": [proposed_row(3)]}, tokens, stats)
        merge_page(
            result, {"fields": {}, "items": [proposed_row(), proposed_row(3)]}, tokens, stats
        )
        self.assertEqual(len(result["items"]), 2)
        self.assertLess(
            result["items"][0]["description"]["bbox"][1],
            result["items"][1]["description"]["bbox"][1],
        )

    def test_conflict_records_both_original_evidence_values_without_overwrite(self):
        tokens = row_tokens("Cable", 0.3) + [token("85.00", x=0.7, y=0.3, width=0.1)]
        result = empty()
        stats = report()
        merge_page(result, {"fields": {}, "items": [proposed_row()]}, tokens, stats)
        different = {**proposed_row(), "unit_price": claim("85.00", 4)}
        merge_page(result, {"fields": {}, "items": [different]}, tokens, stats)
        detail = result["conflict_details"][0]
        self.assertEqual(result["items"][0]["unit_price"]["value"], "80.00")
        self.assertEqual(detail["current"]["value"], "80.00")
        self.assertEqual(detail["proposed"]["value"], "85.00")
        self.assertIsNot(detail["current"], result["items"][0]["unit_price"])

    def test_no_ocr_is_called_for_searchable_pdf_regions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.pdf"
            with pymupdf.open() as document:
                document.new_page().insert_text((50, 60), "Invoice number GUIDE-123")
                document.save(path)
            with (
                patch(
                    "invoice_extraction.reader.ocr_tokens",
                    side_effect=AssertionError("Searchable PDF must not run OCR"),
                ),
                patch(
                    "invoice_extraction.regions.locate",
                    return_value=[{"kind": "HEADER", "bbox": [0, 0, 1, 0.3]}],
                ),
                patch(
                    "invoice_extraction.local_vision.interpret",
                    return_value=({"fields": {}, "items": []}, {}),
                ),
            ):
                result = read_document(path, "en", use_local_vision=True)
            self.assertEqual(result["fields"]["invoice_number"]["value"], "GUIDE-123")
            self.assertEqual(result["guided_reading"]["completed"], 1)
            self.assertTrue(all(t["source"] == "PDF_TEXT" for t in result["tokens"]))

    def test_region_can_recover_when_first_ocr_found_no_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scan.png"
            Image.new("RGB", (800, 1200), "white").save(path)

            def prepared(picture):
                return (
                    picture,
                    lambda b: b,
                    {"method": "ORIGINAL", "rotation": 0, "curvature_corrected": False},
                    [],
                )

            with (
                patch("invoice_extraction.page_preparation.prepare_page", side_effect=prepared),
                patch("invoice_extraction.reader.ocr_tokens", side_effect=[[], [token("115.00")]]),
                patch(
                    "invoice_extraction.regions.locate",
                    return_value=[{"kind": "TOTALS", "bbox": [0, 0.5, 1, 0.9]}],
                ),
                patch(
                    "invoice_extraction.local_vision.interpret",
                    return_value=({"fields": {"grand_total": claim("115.00", 1)}, "items": []}, {}),
                ),
            ):
                result = read_document(path, "en", use_local_vision=True)
            self.assertEqual(result["fields"]["grand_total"]["value"], "115.00")
            self.assertGreaterEqual(result["fields"]["grand_total"]["bbox"][1], 0.5)
            self.assertEqual(result["tokens"][0]["reading_order"], 1)

    def test_limited_budget_skips_region_model_and_retains_primary_results(self):
        result = empty()
        with patch("invoice_extraction.regions.locate") as locator:
            recover(result, 1, None, [], Mock(), report(), time.perf_counter() + 1)
        locator.assert_not_called()
        self.assertEqual(result["guided_reading"]["status"], "PARTIAL")

    def test_failure_in_region_pass_keeps_primary_and_marks_partial_activity(self):
        primary = {"fields": {"grand_total": claim("115", 1)}, "items": []}
        with (
            patch("invoice_extraction.local_vision.interpret", return_value=(primary, {})),
            patch("invoice_extraction.regions.locate", side_effect=OSError("offline")),
        ):
            result = enhance(empty(), [(1, None)], [token("115")], reread=Mock())
        self.assertEqual(result["fields"]["grand_total"]["value"], "115")
        self.assertEqual(result["guided_reading"]["status"], "UNAVAILABLE")

    def test_rotated_evidence_maps_back_to_original_for_each_right_angle(self):
        for angle, expected in [
            (0, [0.1, 0.2, 0.3, 0.4]),
            (90, [0.6, 0.1, 0.8, 0.3]),
            (180, [0.7, 0.6, 0.9, 0.8]),
            (270, [0.2, 0.7, 0.4, 0.9]),
        ]:
            model = Mock()
            model.predict.return_value = [{"label_names": [str(angle)], "scores": [0.99]}]
            with (
                patch("invoice_extraction.page_preparation.orientation_model", return_value=model),
                patch(
                    "invoice_extraction.page_preparation.document_view",
                    side_effect=lambda p: (p, np.eye(3), "ORIGINAL"),
                ),
                patch(
                    "invoice_extraction.page_preparation.straighten_curves",
                    side_effect=lambda p: (p, np.zeros(p.width), False),
                ),
            ):
                _, mapper, info, _ = prepare_page(Image.new("RGB", (800, 1200)))
            self.assertEqual(mapper([0.1, 0.2, 0.3, 0.4]), expected)
            self.assertEqual(info["rotation"], angle)

    def test_low_confidence_orientation_does_not_rotate(self):
        model = Mock()
        model.predict.return_value = [{"label_names": ["180"], "scores": [0.6]}]
        with patch("invoice_extraction.page_preparation.orientation_model", return_value=model):
            _, _, info, warnings = prepare_page(Image.new("RGB", (800, 1200), "white"))
        self.assertEqual(info["rotation"], 0)
        self.assertIn("PAGE_ORIENTATION_UNCERTAIN", warnings)

    def test_curvature_requires_three_agreeing_rules_and_preserves_plain_pages(self):
        image = np.full((600, 800, 3), 255, np.uint8)
        xs = np.arange(15, 785)
        offsets = 48 * (xs / 799) * (1 - xs / 799)
        for y in (170, 280, 390):
            points = np.column_stack((xs, (y + offsets).astype(int))).astype(np.int32)
            cv2.polylines(image, [points], False, (0, 0, 0), 2)
        _, delta, changed = straighten_curves(Image.fromarray(image))
        self.assertTrue(changed)
        self.assertGreater(float(delta[400]), 5)
        self.assertFalse(straighten_curves(Image.new("RGB", (800, 600), "white"))[2])
