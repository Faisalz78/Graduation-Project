import base64
import io
import tempfile
import unittest
from pathlib import Path

import cv2
from invoice_extraction.reader import read_document
from invoice_extraction.structured_sources import (
    merge_structured,
    parse_ubl_xml,
    parse_zatca_tlv,
    qr_sources,
)
from PIL import Image
from pypdf import PdfWriter


def tlv_payload(changes=None):
    values = {
        1: "مؤسسة الاختبار",
        2: "310123456700003",
        3: "2026-09-11T12:13:57Z",
        4: "218.50",
        5: "28.50",
        **(changes or {}),
    }
    raw = b"".join(
        bytes([tag, len(value.encode("utf-8"))]) + value.encode("utf-8")
        for tag, value in values.items()
    )
    return base64.b64encode(raw).decode("ascii")


def ubl_xml(invoice_number="XML-001", total="218.50"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>{invoice_number}</cbc:ID>
  <cbc:IssueDate>2026-09-11</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>SAR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>مؤسسة الاختبار</cbc:Name></cac:PartyName>
    <cac:PartyTaxScheme><cbc:CompanyID>310123456700003</cbc:CompanyID></cac:PartyTaxScheme>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="SAR">28.50</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount currencyID="SAR">190.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="SAR">{total}</cbc:TaxInclusiveAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="PCE">2</cbc:InvoicedQuantity>
    <cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator><cbc:Amount>10.00</cbc:Amount></cac:AllowanceCharge>
    <cac:Item><cbc:Description>مواد اختبار</cbc:Description>
      <cac:ClassifiedTaxCategory><cbc:Percent>15</cbc:Percent></cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price><cbc:PriceAmount>100.00</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>""".encode("utf-8")


class StructuredSourceTests(unittest.TestCase):
    def test_zatca_tlv_tags_one_to_five_are_parsed_without_authenticity_claim(self):
        source = parse_zatca_tlv(tlv_payload(), page=1, bbox=[0.1, 0.2, 0.3, 0.4])
        self.assertEqual(source["document_type"], "ZATCA_TLV")
        self.assertEqual(source["present_tags"], [1, 2, 3, 4, 5])
        self.assertEqual(source["fields"]["invoice_date"]["value"], "2026-09-11")
        self.assertEqual(source["fields"]["grand_total"]["value"], "218.50")

    def test_malformed_or_incomplete_tlv_is_rejected(self):
        for payload in ("not-base64", base64.b64encode(b"\x01\x05abc").decode("ascii")):
            with self.assertRaisesRegex(ValueError, "INVALID_QR_PAYLOAD"):
                parse_zatca_tlv(payload, page=1, bbox=[0, 0, 1, 1])

    def test_qr_is_located_and_decoded_from_a_document_image(self):
        small = cv2.QRCodeEncoder_create().encode(tlv_payload())
        large = cv2.resize(small, None, fx=12, fy=12, interpolation=cv2.INTER_NEAREST)
        large = cv2.copyMakeBorder(
            large, 48, 48, 48, 48, cv2.BORDER_CONSTANT, value=255
        )
        sources, warnings = qr_sources(Image.fromarray(large), 1)
        self.assertEqual(warnings, [])
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["fields"]["tax_total"]["value"], "28.50")
        self.assertTrue(all(0 <= value <= 1 for value in sources[0]["bbox"]))

    def test_ubl_header_totals_and_line_are_extracted(self):
        source, items = parse_ubl_xml(ubl_xml())
        self.assertEqual(source["document_type"], "Invoice")
        self.assertEqual(source["fields"]["invoice_number"]["value"], "XML-001")
        self.assertEqual(
            source["fields"]["supplier_tax_number"]["value"], "310123456700003"
        )
        self.assertEqual(items[0]["unit"]["value"], "PCE")
        self.assertEqual(items[0]["discount_amount"]["value"], "10.00")
        qr = parse_zatca_tlv(
            tlv_payload({4: "218.5"}), page=1, bbox=[0.1, 0.2, 0.3, 0.4]
        )
        merged = merge_structured(
            {
                "fields": {},
                "items": [],
                "warnings": [],
                "requires_human_review": True,
            },
            [qr, source],
            [items],
        )
        self.assertEqual(merged["fields"]["grand_total"]["value"], "218.50")
        self.assertNotIn("STRUCTURED_SOURCE_CONFLICT_GRAND_TOTAL", merged["warnings"])

    def test_xml_entities_and_unrelated_roots_are_rejected(self):
        utf16_entity = (
            '<?xml version="1.0" encoding="utf-16"?>'
            '<!DOCTYPE Invoice [<!ENTITY test "unsafe">]>'
            '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">'
            "&test;</Invoice>"
        ).encode("utf-16")
        for data in (
            b'<!DOCTYPE x [<!ENTITY test "unsafe">]><x>&test;</x>',
            utf16_entity,
            b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        ):
            with self.assertRaisesRegex(ValueError, "INVALID_XML"):
                parse_ubl_xml(data)

    def test_direct_and_pdf_embedded_xml_produce_importable_suggestions(self):
        with tempfile.TemporaryDirectory() as directory:
            direct = Path(directory) / "invoice.xml"
            direct.write_bytes(ubl_xml())
            result = read_document(direct, "ar")
            self.assertEqual(result["fields"]["invoice_number"]["source"], "XML")
            self.assertEqual(result["items"][0]["quantity"]["value"], "2")

            pdf = Path(directory) / "invoice.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=400)
            writer.add_attachment("invoice.xml", ubl_xml())
            output = io.BytesIO()
            writer.write(output)
            pdf.write_bytes(output.getvalue())
            embedded = read_document(pdf, "ar")
            self.assertEqual(
                embedded["structured_sources"][0]["location"], "PDF_ATTACHMENT"
            )
            self.assertEqual(embedded["fields"]["grand_total"]["value"], "218.50")


if __name__ == "__main__":
    unittest.main()
