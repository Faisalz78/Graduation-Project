import copy
import json
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from invoice_extraction.camera import document_view, reread_uncertain, restore_tokens
from invoice_extraction.local_vision import NoRedirect, enhance, grounded, interpret
from PIL import Image
from test_parser import token


def claim(value, *ids):
    return {"value": value, "token_ids": list(ids)}


def empty():
    return {"fields": {}, "items": [], "warnings": [], "requires_human_review": True}


class LocalVisionTests(unittest.TestCase):
    def test_rejects_invented_values_and_invalid_or_cross_page_references(self):
        tokens = [token("115.00"), {**token("10.00"), "page": 2}]
        for proposed in (
            claim("116.00", 1),
            claim("115.00", 0),
            claim("115.00", True),
            claim("115.00", 1, 1),
            claim("115.00", 1, 2),
            claim("115.00", 3),
            claim("115.00"),
        ):
            self.assertIsNone(grounded("grand_total", proposed, tokens))

    def test_arabic_numbers_and_minimal_evidence_without_model_confidence(self):
        tokens = [token("الإجمالي ١١٥٫٠٠", y=0.7), token("ضريبة 15.00", y=0.6)]
        result = grounded("grand_total", claim("115.00", 1, 2), tokens)
        self.assertEqual(result["value"], "115.00")
        self.assertEqual(result["bbox"], tokens[0]["bbox"])
        self.assertEqual(result["confidence"], 0.9)
        self.assertTrue(result["needs_review"])

    def test_does_not_match_digits_inside_invoice_numbers_dates_or_percentages(self):
        for text in ("REF-115", "2026-09-14", "115%", "115/200", "1,115.50"):
            self.assertIsNone(grounded("grand_total", claim("115", 1), [token(text)]))

    def test_ambiguous_duplicate_locations_are_rejected(self):
        self.assertIsNone(
            grounded("grand_total", claim("115", 1, 2), [token("115", y=0.2), token("115", y=0.8)])
        )

    def test_dates_require_document_evidence(self):
        result = grounded("invoice_date", claim("2026-09-14", 1), [token("Issued 14/09/2026")])
        self.assertEqual(result["value"], "2026-09-14")
        self.assertIsNone(
            grounded("invoice_date", claim("2026-09-14", 1), [token("Issued 14/08/2026")])
        )

    def test_model_may_select_an_existing_crop_read_but_not_create_one(self):
        item = token("51S.00")
        item["recognition_reads"] = ["51S.00", "515.00"]
        result = grounded("grand_total", claim("515.00", 1), [item])
        self.assertEqual(result["value"], "515.00")
        self.assertIn("51S.00", result["recognition_reads"])
        self.assertIsNone(grounded("grand_total", claim("519.00", 1), [item]))

    def test_conflicting_total_never_replaces_existing_read(self):
        tokens = [token("100.00"), token("115.00", y=0.8)]
        current = empty()
        current["fields"]["grand_total"] = grounded("grand_total", claim("100.00", 1), tokens)
        proposal = {"fields": {"grand_total": claim("115.00", 2)}, "items": []}
        with patch("invoice_extraction.local_vision.interpret", return_value=(proposal, {})):
            output = enhance(current, [(1, Image.new("RGB", (50, 50)))], tokens)
        self.assertEqual(output["fields"]["grand_total"]["value"], "100.00")
        self.assertIn("LOCAL_VISION_DISAGREEMENT", output["warnings"])

    def test_new_layout_adds_evidenced_rows_without_inventing_discount(self):
        tokens = [
            token("Cable", y=0.4),
            token("2", x=0.65, y=0.4, width=0.05),
            token("80.00", x=0.75, y=0.4, width=0.1),
        ]
        row = {
            "description": claim("Cable", 1),
            "quantity": claim("2", 2),
            "unit_price": claim("80.00", 3),
        }
        with patch(
            "invoice_extraction.local_vision.interpret",
            return_value=({"fields": {}, "items": [row, row]}, {}),
        ):
            output = enhance(empty(), [(1, Image.new("RGB", (50, 50)))], tokens)
        self.assertEqual(len(output["items"]), 1)
        self.assertNotIn("discount_amount", output["items"][0])

    def test_rejects_row_using_amount_from_summary(self):
        tokens = [token("Cable", y=0.4), token("2", y=0.4), token("80.00", y=0.8)]
        row = {
            "description": claim("Cable", 1),
            "quantity": claim("2", 2),
            "unit_price": claim("80.00", 3),
        }
        with patch(
            "invoice_extraction.local_vision.interpret",
            return_value=({"fields": {}, "items": [row]}, {}),
        ):
            output = enhance(empty(), [(1, Image.new("RGB", (50, 50)))], tokens)
        self.assertEqual(output["items"], [])

    def test_unavailable_model_preserves_extraction_and_budget_stops_more_calls(self):
        current = empty()
        current["fields"]["grand_total"] = grounded("grand_total", claim("115", 1), [token("115")])
        before = copy.deepcopy(current["fields"])
        with patch(
            "invoice_extraction.local_vision.interpret", side_effect=OSError("offline")
        ) as model:
            output = enhance(
                current, [(1, None), (2, None)], [token("115"), {**token("115"), "page": 2}]
            )
        self.assertEqual(output["fields"], before)
        self.assertEqual(output["local_understanding"]["status"], "UNAVAILABLE")
        self.assertEqual(model.call_count, 1)
        with patch("invoice_extraction.local_vision.interpret") as model:
            enhance(empty(), [(1, None)], [token("1")], budget=0)
        model.assert_not_called()

    def test_partial_document_keeps_completed_pages_and_empty_xml_skips_model(self):
        proposal = {"fields": {"grand_total": claim("115", 1)}, "items": []}
        with patch(
            "invoice_extraction.local_vision.interpret", side_effect=[(proposal, {}), OSError()]
        ):
            output = enhance(
                empty(), [(1, None), (2, None)], [token("115"), {**token("115"), "page": 2}]
            )
        self.assertEqual(output["local_understanding"]["status"], "PARTIAL")
        with patch("invoice_extraction.local_vision.interpret") as model:
            output = enhance(empty(), [], [])
        model.assert_not_called()
        self.assertEqual(output["local_understanding"]["status"], "NOT_APPLICABLE")

    def test_truncated_model_output_is_not_accepted_and_transport_refuses_redirect(self):
        with patch(
            "invoice_extraction.local_vision.local_request",
            return_value={
                "done_reason": "length",
                "message": {"content": json.dumps({"fields": {}, "items": []})},
            },
        ):
            with self.assertRaisesRegex(ValueError, "TRUNCATED"):
                interpret(Image.new("RGB", (50, 50)), [token("text")])
        with self.assertRaisesRegex(ValueError, "REDIRECT_REFUSED"):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")

    def test_perspective_rectification_maps_evidence_to_original_and_ignores_table(self):
        canvas = np.full((1000, 800, 3), 50, dtype=np.uint8)
        quad = np.int32([[80, 70], [750, 100], [710, 940], [45, 900]])
        cv2.fillConvexPoly(canvas, quad, (255, 255, 255))
        picture = Image.fromarray(canvas)
        view, inverse, method = document_view(picture)
        self.assertEqual(method, "PERSPECTIVE_CORRECTED")
        tokens = [{**token("x"), "bbox": [0, 0, 1, 1]}]
        restore_tokens(tokens, inverse, view.size, picture.size)
        self.assertAlmostEqual(tokens[0]["bbox"][0], 45 / 800, delta=0.015)
        table = np.full((1000, 800, 3), 255, dtype=np.uint8)
        cv2.polylines(table, [quad], True, (0, 0, 0), 3)
        self.assertEqual(document_view(Image.fromarray(table))[2], "ORIGINAL")

    def test_crop_retry_is_bounded_and_preserves_original_text(self):
        from unittest.mock import Mock

        tokens = [{**token("51S.00", y=0.1 + i * 0.06), "confidence": 0.6} for i in range(9)]
        recognizer = Mock()
        recognizer.return_value.predict.return_value = [
            {"rec_texts": ["515.00"], "rec_scores": [0.98]}
        ]
        count = reread_uncertain(Image.new("RGB", (1000, 1000)), tokens, "ar", recognizer)
        self.assertEqual(count, 6)
        self.assertTrue(all(item["text"] == "51S.00" for item in tokens))
        self.assertEqual(tokens[0]["recognition_reads"], ["51S.00", "515.00"])
