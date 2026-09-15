import unittest
from unittest.mock import patch

import cv2
import numpy as np
from invoice_extraction.geometry import deskew, original_box
from invoice_extraction.mixed_script import latin_value, supplement
from invoice_extraction.parser import decimal, label_match, parse
from test_parser import token


class GeometryTests(unittest.TestCase):
    def test_blank_image_and_upright_lines_remain_unchanged(self):
        for ruled in (False, True):
            picture = np.full((700, 900, 3), 255, np.uint8)
            if ruled:
                for y in (100, 200, 300, 400):
                    cv2.line(picture, (80, y), (800, y), (170, 170, 170), 2)
            corrected, inverse, angle = deskew(picture)
            self.assertEqual(angle, 0)
            np.testing.assert_array_equal(corrected, picture)
            self.assertEqual(
                original_box([90, 70, 180, 140], inverse, 900, 700), [0.1, 0.1, 0.2, 0.2]
            )

    def test_positive_and_negative_skew_and_original_coordinates(self):
        for rotation in (-3.5, 1.7, 5):
            picture = np.full((900, 900, 3), 255, np.uint8)
            for y in (200, 300, 400, 500, 600):
                cv2.line(picture, (140, y), (760, y), (120, 120, 120), 2)
            rotated = cv2.warpAffine(
                picture,
                cv2.getRotationMatrix2D((450, 450), rotation, 1),
                (900, 900),
                borderValue=(255, 255, 255),
            )
            corrected, inverse, angle = deskew(rotated)
            self.assertAlmostEqual(angle, -rotation, delta=0.2)
            self.assertGreaterEqual(corrected.shape[0], 900)
            # Transform a known original region to the corrected page and map it back.
            forward = cv2.invertAffineTransform(inverse)
            corners = (
                np.array([[350, 350, 1], [550, 350, 1], [550, 450, 1], [350, 450, 1]]) @ forward.T
            )
            box = [
                corners[:, 0].min(),
                corners[:, 1].min(),
                corners[:, 0].max(),
                corners[:, 1].max(),
            ]
            restored = original_box(box, inverse, 900, 900)
            self.assertLessEqual(restored[0], 350 / 900 + 0.00001)
            self.assertLessEqual(restored[1], 350 / 900 + 0.00001)
            self.assertGreaterEqual(restored[2], 550 / 900 - 0.00001)
            self.assertGreaterEqual(restored[3], 450 / 900 - 0.00001)


class QualityTests(unittest.TestCase):
    def test_approximate_label_keeps_ocr_evidence_and_warns(self):
        result = parse([token("المجموع قبل الضريية 125.50")])
        field = result["fields"]["subtotal"]
        self.assertEqual(field["value"], "125.50")
        self.assertIn("الضريية", field["evidence"])
        self.assertEqual(field["label_match"], "approximate")
        self.assertIn("APPROXIMATE_LABEL_SUBTOTAL", result["warnings"])

    def test_approximation_never_repairs_values_or_pdf_labels(self):
        self.assertNotIn("grand_total", parse([token("الاجمالي المستحق I25.50")])["fields"])
        pdf = token("المجموع قبل الضريية 125.50")
        pdf["source"] = "PDF_TEXT"
        self.assertNotIn("subtotal", parse([pdf])["fields"])
        self.assertIsNone(label_match("الصرية", ["الضريبة"], approximate=True))
        self.assertIsNone(decimal("15%"))
        self.assertEqual(decimal("15%", percentage=True), "15")

    def test_corrected_layout_groups_rows_but_evidence_uses_original(self):
        label = token("Grand total", x=0.1, y=0.1, width=0.2)
        value = token("125.50", x=0.6, y=0.15, width=0.1)
        label["layout_bbox"] = [0.1, 0.2, 0.3, 0.22]
        value["layout_bbox"] = [0.6, 0.2, 0.7, 0.22]
        field = parse([label, value])["fields"]["grand_total"]
        self.assertEqual(field["value"], "125.50")
        for actual, expected in zip(field["bbox"], [0.1, 0.1, 0.7, 0.17]):
            self.assertAlmostEqual(actual, expected)

    def test_latin_reading_rejects_conflicts_invalid_dates_and_partial_codes(self):
        self.assertEqual(latin_value("invoice_number", "AB-9381: label"), "AB-9381")
        self.assertEqual(latin_value("currency", "SAR:"), "SAR")
        for field, text in (
            ("currency", "SAR USD"),
            ("invoice_date", "2026-02-30"),
            ("invoice_date", "11/09/2026"),
            ("invoice_number", "ABC"),
            ("invoice_number", "2026-09-11"),
            ("invoice_number", "AB-123 CD-456"),
        ):
            self.assertIsNone(latin_value(field, text))

    def test_second_reading_preserves_evidence_confidence_and_never_overwrites_value(self):
        missing = token("تاريخ الفاتورة")
        missing["layout_bbox"] = missing["bbox"].copy()
        existing = token("تاريخ الفاتورة 2026-05-02")
        existing["layout_bbox"] = existing["bbox"].copy()
        with patch("invoice_extraction.mixed_script.recognizer") as factory:
            factory.return_value.predict.return_value = [
                {"rec_text": "2026-09-11:", "rec_score": 0.8}
            ]
            supplement([missing, existing], np.full((200, 300, 3), 255, np.uint8))
            factory.return_value.predict.assert_called_once()
        self.assertEqual(existing["text"], "تاريخ الفاتورة 2026-05-02")
        result = parse([missing])
        field = result["fields"]["invoice_date"]
        self.assertEqual(field["value"], "2026-09-11")
        self.assertEqual(field["confidence"], 0.8)
        self.assertEqual(field["recognition_reads"], ["تاريخ الفاتورة", "2026-09-11:"])
        self.assertIn("SECOND_READING_INVOICE_DATE", result["warnings"])

    def test_low_confidence_second_reading_remains_empty(self):
        missing = token("العملة")
        missing["layout_bbox"] = missing["bbox"].copy()
        with patch("invoice_extraction.mixed_script.recognizer") as factory:
            factory.return_value.predict.return_value = [{"rec_text": "SAR", "rec_score": 0.6}]
            supplement([missing], np.full((200, 300, 3), 255, np.uint8))
        self.assertNotIn("currency", parse([missing])["fields"])


if __name__ == "__main__":
    unittest.main()
