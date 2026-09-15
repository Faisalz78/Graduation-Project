"""Exercise real PaddleOCR on scanned and mixed PDF wrappers of known synthetic samples."""

import hashlib
import json
from pathlib import Path

import pymupdf as fitz
from evaluate_benchmark import HEADERS, ITEM_FIELDS, equal
from invoice_extraction.reader import read_document

ROOT = Path(__file__).resolve().parents[3]


def main():
    samples = ROOT / "05_Data/Sample_Invoices/Synthetic_OCR_v1"
    output = ROOT / "05_Data/Processed_Data/OCR_HYBRID_ROUTES"
    output.mkdir(parents=True, exist_ok=True)
    records = json.loads((samples / "manifest.json").read_text(encoding="utf-8"))["records"]
    by_name = {record["file"]: record for record in records}
    results = []
    for name in ("ar-01-scan.png", "en-01-scan.png", "ar-01-digital.pdf"):
        assert hashlib.sha256((samples / name).read_bytes()).hexdigest() == by_name[name]["sha256"]
    for language in ("ar", "en"):
        image = samples / f"{language}-01-scan.png"
        scanned = output / f"{language}-scanned.pdf"
        with fitz.open() as document:
            page = document.new_page(width=595.28, height=841.89)
            page.insert_image(page.rect, filename=str(image))
            document.save(scanned)
        extracted = read_document(scanned, language)
        expected = by_name[image.name]["expected"]
        assert extracted["page_routes"][0]["method"] == "OCR"
        assert extracted["tokens"] and all(
            token["source"] == "OCR" for token in extracted["tokens"]
        )
        checks = {
            field: equal(field, extracted["fields"].get(field, {}).get("value"), expected[field])
            for field in HEADERS
        }
        item_checks = [
            {
                field: equal(
                    field,
                    (extracted["items"][index] if index < len(extracted["items"]) else {})
                    .get(field, {})
                    .get("value"),
                    row[field],
                )
                for field in ITEM_FIELDS
            }
            for index, row in enumerate(expected["items"])
        ]
        (output / f"{language}-scanned.json").write_text(
            json.dumps(extracted, ensure_ascii=False), encoding="utf-8"
        )
        results.append(
            {
                "document": scanned.name,
                "routes": extracted["page_routes"],
                "header_checks": checks,
                "item_checks": item_checks,
                "seconds": extracted["seconds"],
            }
        )
    mixed = output / "mixed.pdf"
    with (
        fitz.open(samples / "ar-01-digital.pdf") as document,
        fitz.open(output / "en-scanned.pdf") as scan,
    ):
        document.insert_pdf(scan)
        document.save(mixed)
    extracted = read_document(mixed, "en")
    assert [route["method"] for route in extracted["page_routes"]] == ["PDF_TEXT", "OCR"]
    assert {token["page"] for token in extracted["tokens"]} == {1, 2}
    assert len(extracted["items"]) == 4
    assert "AMBIGUOUS_INVOICE_NUMBER" in extracted["warnings"]
    (output / "mixed.json").write_text(json.dumps(extracted, ensure_ascii=False), encoding="utf-8")
    results.append(
        {
            "document": "mixed.pdf",
            "routes": extracted["page_routes"],
            "rows": len(extracted["items"]),
            "conflicting_headers_left_unknown": "invoice_number" not in extracted["fields"],
            "seconds": extracted["seconds"],
        }
    )
    report = {
        "synthetic_only": True,
        "independent_evaluation": False,
        "note": "PDF wrappers of the existing regression samples; mixed.pdf intentionally combines two sample invoices to test conflicting headers and page routing.",
        "reader_version": extracted["reader_version"],
        "results": results,
    }
    destination = ROOT / "06_Testing_Evaluation/Results/OCR_HYBRID_ROUTES.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
