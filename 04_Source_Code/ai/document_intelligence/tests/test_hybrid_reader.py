import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from invoice_extraction.parser import parse
from invoice_extraction.pdf_text import native_tokens, page_route, render_page
from invoice_extraction.reader import read_document, reading_order
from PIL import Image
from test_parser import token
from test_structured_sources import ubl_xml


class HybridReaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "invoice.pdf"

    def save_pdf(self, *, scan=False, logo=False, rotation=0, pages=1, attached_xml=False):
        with fitz.open() as document:
            for index in range(pages):
                page = document.new_page(width=600, height=800)
                page.insert_text((50, 55), "Invoice number SHORT-123", fontsize=12)
                if scan and index == pages - 1 or logo:
                    data = io.BytesIO()
                    Image.new("RGB", (600, 800), "#eeeeee").save(data, format="PNG")
                    area = page.rect if scan and index == pages - 1 else fitz.Rect(500, 30, 550, 90)
                    page.insert_image(area, stream=data.getvalue())
                page.set_rotation(rotation)
            if attached_xml:
                document.embfile_add("invoice.xml", ubl_xml())
            document.save(self.path)

    def test_short_searchable_pdf_and_logo_never_invoke_ocr(self):
        for logo in (False, True):
            self.save_pdf(logo=logo)
            with patch(
                "invoice_extraction.reader.ocr_tokens", side_effect=AssertionError("Unexpected OCR")
            ):
                result = read_document(self.path, "en")
            self.assertEqual(result["fields"]["invoice_number"]["value"], "SHORT-123")
            self.assertEqual(result["page_routes"][0]["method"], "PDF_TEXT")
            self.assertIn("SHORT-123", result["text"])
            self.assertTrue(all(t["confidence"] is None for t in result["tokens"]))

    def test_mixed_pdf_routes_pages_independently_and_preserves_page_numbers(self):
        self.save_pdf(scan=True, pages=2)
        scanned = token("Grand total 115.00")
        scanned["page"] = 2
        with patch("invoice_extraction.reader.ocr_tokens", return_value=[scanned]) as ocr:
            result = read_document(self.path, "en")
        ocr.assert_called_once()
        self.assertEqual(ocr.call_args.args[2], 2)
        self.assertGreaterEqual(max(ocr.call_args.args[0].size), 3000)
        self.assertEqual([r["method"] for r in result["page_routes"]], ["PDF_TEXT", "OCR"])
        self.assertEqual(result["fields"]["grand_total"]["page"], 2)
        self.assertEqual(result["fields"]["grand_total"]["confidence"], 0.9)
        self.assertEqual(
            [t["reading_order"] for t in result["tokens"]],
            list(range(1, len(result["tokens"]) + 1)),
        )

    def test_direct_failure_falls_back_to_paddle(self):
        self.save_pdf()
        with (
            patch(
                "invoice_extraction.reader.native_tokens", side_effect=RuntimeError("broken text")
            ),
            patch(
                "invoice_extraction.reader.ocr_tokens", return_value=[token("Grand total 115.00")]
            ) as ocr,
        ):
            result = read_document(self.path, "en")
        ocr.assert_called_once()
        self.assertEqual(result["page_routes"][0]["reason"], "DIRECT_EXTRACTION_FAILED")

    def test_direct_and_ocr_failure_does_not_return_a_success(self):
        self.save_pdf()
        with (
            patch("invoice_extraction.reader.native_tokens", side_effect=RuntimeError()),
            patch("invoice_extraction.reader.ocr_tokens", side_effect=RuntimeError("OCR failed")),
            self.assertRaisesRegex(RuntimeError, "OCR failed"),
        ):
            read_document(self.path, "en")

    def test_scanned_page_is_read_even_when_xml_is_attached(self):
        self.save_pdf(scan=True, attached_xml=True)
        with patch(
            "invoice_extraction.reader.ocr_tokens", return_value=[token("Grand total 999.00")]
        ) as ocr:
            result = read_document(self.path, "en")
        ocr.assert_called_once()
        self.assertIn("VISIBLE_TEXT_CONFLICT_GRAND_TOTAL", result["warnings"])
        self.assertEqual(result["fields"]["grand_total"]["value"], "218.50")

    def test_png_jpg_and_jpeg_use_the_existing_paddle_function(self):
        for extension in ("png", "jpg", "jpeg"):
            path = self.path.with_suffix("." + extension)
            Image.new("RGB", (200, 300), "white").save(path)
            with patch(
                "invoice_extraction.reader.ocr_tokens", return_value=[token("Grand total 12.50")]
            ) as ocr:
                result = read_document(path, "ar")
            ocr.assert_called_once()
            self.assertEqual(result["page_routes"][0]["reason"], "IMAGE_UPLOAD")

    def test_normal_arabic_unicode_and_mixed_identifiers_are_not_reversed(self):
        # Place basic Unicode in visual RTL order, without presentation-form glyphs.
        font_paths = [
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]
        font = next((path for path in font_paths if path.is_file()), None)
        if font is None:
            self.skipTest("An Arabic font is required for this generated PDF")
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text(
                (50, 50), "المورد شركة الاختبار"[::-1], fontname="arabic", fontfile=str(font)
            )
            page.insert_text((50, 90), "Invoice number AB-2026-91")
            page.insert_text((50, 120), "Invoice date 2026-09-14")
            page.insert_text((50, 150), "VAT total 15.25")
            document.save(self.path)
        with patch(
            "invoice_extraction.reader.ocr_tokens", side_effect=AssertionError("Unexpected OCR")
        ):
            result = read_document(self.path, "ar")
        self.assertIn("المورد", result["text"])
        self.assertNotIn("دروملا", result["text"])
        self.assertEqual(result["fields"]["invoice_number"]["value"], "AB-2026-91")
        self.assertEqual(result["fields"]["tax_total"]["value"], "15.25")

    def test_rotated_pdf_evidence_aligns_with_display_and_layout_remains_readable(self):
        self.save_pdf(rotation=90)
        with fitz.open(self.path) as document:
            page = document[0]
            extracted = native_tokens(page, 1)
            self.assertEqual(
                render_page(page, ocr=False).size[0] > render_page(page, ocr=False).size[1], True
            )
            self.assertGreater(extracted[0]["bbox"][0], 0.8)
            self.assertLess(extracted[0]["layout_bbox"][0], 0.2)
            result = parse(extracted)
            self.assertEqual(result["fields"]["invoice_number"]["value"], "SHORT-123")

    def test_replacement_characters_and_private_glyphs_trigger_ocr(self):
        for text in ("\ufffd\ufffd12", "\ue001\ue002123", "...   ..."):
            self.assertEqual(page_route([token(text)], 0)[0], "OCR")
        self.assertEqual(page_route([token("12345")], 0)[0], "PDF_TEXT")

    def test_blank_pdf_and_excessive_pages_do_not_load_ocr(self):
        with fitz.open() as document:
            document.new_page()
            document.save(self.path)
        with (
            patch(
                "invoice_extraction.reader.ocr_tokens", side_effect=AssertionError("Unexpected OCR")
            ),
            self.assertRaisesRegex(ValueError, "NO_TEXT_FOUND"),
        ):
            read_document(self.path, "en")
        self.save_pdf(pages=4)
        with self.assertRaisesRegex(ValueError, "PAGE_LIMIT_EXCEEDED"):
            read_document(self.path, "en")

    def test_multipage_tables_are_preserved_without_repeating_rows(self):
        tokens = []
        for page in (1, 2):
            for text, x, y in (
                ("Description", 0.1, 0.1),
                ("Qty", 0.5, 0.1),
                ("Price", 0.7, 0.1),
                (f"Item {page}", 0.1, 0.7),
                ("2", 0.5, 0.7),
                ("125.50", 0.7, 0.7),
            ):
                item = token(text, x=x, y=y, width=0.1)
                item["page"] = page
                tokens.append(item)
        result = parse(tokens)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual([row["description"]["page"] for row in result["items"]], [1, 2])
        ordered, text = reading_order(list(reversed(tokens)))
        self.assertEqual(ordered[0]["page"], 1)
        self.assertLess(text.index("Item 1"), text.index("Item 2"))


if __name__ == "__main__":
    unittest.main()
