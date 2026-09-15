"""Anonymized layout regressions; no uploaded customer documents are test fixtures."""

import unittest
from unittest.mock import patch

import cv2
import numpy as np
from invoice_extraction.geometry import original_box, prepare_image
from invoice_extraction.mixed_script import supplement_latin
from invoice_extraction.parser import parse, value_for
from test_parser import token


class PhotographedLayoutTests(unittest.TestCase):
    def test_revalidated_tokens_with_empty_reads_keep_original_tax_evidence(self):
        tokens = [
            token("Total Excl VAT", 0.52, 0.6, 0.14),
            token("200.00", 0.84, 0.6, 0.09),
            token("VAT", 0.52, 0.64, 0.06),
            token("30.00", 0.84, 0.64, 0.09),
            token("Grand Total", 0.52, 0.68, 0.14),
            token("230.00", 0.84, 0.68, 0.09),
        ]
        for t in tokens:
            t["recognition_reads"] = []
        field = parse(tokens)["fields"]["tax_total"]
        self.assertEqual(field["value"], "30.00")
        self.assertEqual(field["recognition_reads"], ["VAT", "30.00"])
        self.assertEqual(field["evidence"], "VAT 30.00")

    def test_existing_arabic_column_approximation_remains_ocr_only(self):
        tokens = [
            token("الوصف", 0.8, 0.1, 0.12),
            token("الكميه", 0.5, 0.1, 0.1),
            token("سعر الوحدة", 0.2, 0.1, 0.15),
            token("صنف تجريبي", 0.8, 0.2, 0.15),
            token("2", 0.5, 0.2, 0.03),
            token("25.00", 0.2, 0.2, 0.08),
        ]
        result = parse(tokens)
        self.assertEqual(result["items"][0]["quantity"]["value"], "2")
        self.assertIn("APPROXIMATE_COLUMN_QUANTITY", result["warnings"])
        for t in tokens:
            t["source"] = "PDF_TEXT"
            t["confidence"] = None
        self.assertEqual(parse(tokens)["items"], [])

    def test_adjacent_tax_breakdown_cannot_supply_grand_total(self):
        result = parse(
            [
                token("Total Excl VAT", 0.52, 0.6, 0.14),
                token("200.00", 0.84, 0.6, 0.09),
                token("VAT", 0.52, 0.64, 0.06),
                token("30.00", 0.84, 0.64, 0.09),
                token("30.00", 0.40, 0.68, 0.08),
                token("Grand Total", 0.52, 0.68, 0.14),
                token("230.00", 0.84, 0.68, 0.09),
            ]
        )
        fields = result["fields"]
        self.assertEqual(fields["subtotal"]["value"], "200.00")
        self.assertEqual(fields["tax_total"]["value"], "30.00")
        self.assertEqual(fields["grand_total"]["value"], "230.00")
        self.assertEqual(fields["grand_total"]["recognition_reads"], ["Grand Total", "230.00"])
        self.assertNotIn("DOCUMENT_TOTALS_DO_NOT_RECONCILE", result["warnings"])

    def test_conflicting_printed_totals_warn_without_rewriting_numbers(self):
        result = parse(
            [
                token("Subtotal 100.00"),
                token("VAT total 15.00", y=0.2),
                token("Grand total 130.00", y=0.3),
            ]
        )
        self.assertEqual(result["fields"]["grand_total"]["value"], "130.00")
        self.assertIn("DOCUMENT_TOTALS_DO_NOT_RECONCILE", result["warnings"])

    def test_bilingual_metadata_and_supplier_header_exclude_customer(self):
        result = parse(
            [
                token("مؤسسة المورد التجريبي", 0.4, 0.04, 0.3),
                token("TAX INVOICE", 0.4, 0.12, 0.2),
                token("Invoice/فاتورة", 0.1, 0.20, 0.17),
                token("TEST-42", 0.32, 0.20, 0.13),
                token("Date/التاريخ", 0.56, 0.20, 0.15),
                token("23/07/2026 06:32:24", 0.74, 0.20, 0.24),
                token("Customer", 0.1, 0.25, 0.15),
                token("شركة العميل التجريبي", 0.32, 0.25, 0.3),
                token("Amount in words: SAR Two Hundred Only", 0.1, 0.8, 0.7),
            ]
        )
        values = {name: item["value"] for name, item in result["fields"].items()}
        self.assertEqual(values["supplier_name"], "مؤسسة المورد التجريبي")
        self.assertEqual(values["invoice_number"], "TEST-42")
        self.assertEqual(values["invoice_date"], "2026-07-23")
        self.assertEqual(values["currency"], "SAR")
        self.assertNotIn("tax_total", values)

    def test_native_pdf_supplier_is_not_truncated_at_first_word(self):
        result = parse(
            [
                token("Supplier", 0.1, 0.1, 0.12),
                token("Sample", 0.3, 0.1, 0.1),
                token("Trading", 0.42, 0.1, 0.12),
            ]
        )
        self.assertEqual(result["fields"]["supplier_name"]["value"], "Sample Trading")

    def test_dates_never_choose_an_ambiguous_month(self):
        self.assertEqual(value_for("invoice_date", "23/07/2026 12:04:20"), "2026-07-23")
        self.assertEqual(value_for("invoice_date", "07/23/2026"), "2026-07-23")
        for value in ("07/08/2026", "31/02/2026", "2026-02-30"):
            self.assertIsNone(value_for("invoice_date", value))

    def test_multiline_table_separates_net_vat_amount_and_final_total(self):
        tokens = [
            token("ItemDescription", 0.06, 0.3, 0.18),
            token("Qty", 0.33, 0.3, 0.04),
            token("Unit", 0.43, 0.3, 0.06),
            token("Price", 0.43, 0.325, 0.06),
            token("Disc", 0.53, 0.3, 0.05),
            token("Net", 0.61, 0.3, 0.05),
            token("Amount", 0.6, 0.325, 0.07),
            token("VAT VAT Amt", 0.70, 0.3, 0.15),
            token("Total", 0.90, 0.3, 0.06),
            token("1", 0.02, 0.4, 0.02),
            token("Test cable", 0.06, 0.4, 0.18),
            token("2", 0.34, 0.4, 0.02),
            token("50.00", 0.43, 0.4, 0.06),
            token("0.00", 0.53, 0.4, 0.05),
            token("100.00", 0.60, 0.4, 0.07),
            token("15", 0.72, 0.4, 0.025),
            token("15.00", 0.79, 0.4, 0.06),
            token("115.00", 0.90, 0.4, 0.07),
        ]
        result = parse(tokens)
        self.assertEqual(len(result["items"]), 1)
        values = {k: v["value"] for k, v in result["items"][0].items()}
        self.assertEqual(
            values,
            dict(
                description="Test cable",
                quantity="2",
                unit_price="50.00",
                discount_amount="0.00",
                tax_rate="15",
                document_total="115.00",
            ),
        )
        without_quantity = [t for t in tokens if t["text"] != "2"]
        self.assertEqual(parse(without_quantity)["items"], [])

    def test_latin_digit_recovery_requires_quantity_column_and_preserves_reads(self):
        tokens = [
            token("aty", 0.4, 0.1, 0.05),
            token("T", 0.42, 0.2, 0.02),
            token("T", 0.1, 0.2, 0.02),
            token("19", 0.42, 0.3, 0.03),
        ]
        for t in tokens:
            t["layout_bbox"] = t["bbox"].copy()
        with patch("invoice_extraction.mixed_script.recognizer") as factory:
            factory.return_value.predict.return_value = [
                dict(rec_text="Qty", rec_score=0.99),
                dict(rec_text="1", rec_score=0.99),
                dict(rec_text="1", rec_score=0.99),
            ]
            supplement_latin(tokens, np.full((500, 500, 3), 255, np.uint8))
        self.assertEqual(tokens[1]["text"], "1")
        self.assertEqual(tokens[1]["recognition_reads"], ["T", "1"])
        self.assertEqual(tokens[2]["text"], "T")
        self.assertEqual(tokens[3]["text"], "19")

    def test_photo_scaling_preserves_original_evidence_coordinates(self):
        picture = np.full((900, 700, 3), 255, np.uint8)
        for y, slope in [(200, 0.065), (300, 0.070), (400, 0.075), (500, 0.068)]:
            cv2.line(picture, (80, y), (620, y + int(540 * slope)), (80, 80, 80), 2)
        corrected, inverse, angle = prepare_image(picture)
        self.assertGreater(angle, 3)
        self.assertGreater(corrected.shape[0], picture.shape[0])
        forward = cv2.invertAffineTransform(inverse)
        original = np.array([[200, 300, 1], [400, 300, 1], [400, 350, 1], [200, 350, 1]])
        mapped = original @ forward.T
        box = [mapped[:, 0].min(), mapped[:, 1].min(), mapped[:, 0].max(), mapped[:, 1].max()]
        restored = original_box(box, inverse, 700, 900)
        self.assertLessEqual(restored[0], 200 / 700)
        self.assertGreaterEqual(restored[2], 400 / 700)


if __name__ == "__main__":
    unittest.main()
