"""Reproducible anonymous layout challenge; development evidence, not supplier accuracy."""

import json
from pathlib import Path

import pymupdf as fitz
from invoice_extraction.reader import read_document
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = ROOT / ".local/qa/layout-challenge"
EXPECTED = {
    "supplier_name": "Example Trading Ltd",
    "invoice_number": "DEMO-472",
    "invoice_date": "2026-09-12",
    "currency": "SAR",
    "subtotal": "190.00",
    "tax_total": "28.50",
    "grand_total": "218.50",
}
ITEMS = [
    dict(
        description="Cable roll",
        quantity="2",
        unit_price="80.00",
        tax_rate="15",
        document_total="184.00",
    ),
    dict(
        description="Safety gloves",
        quantity="3",
        unit_price="10.00",
        tax_rate="15",
        document_total="34.50",
    ),
]


def generate():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    pdf = DIRECTORY / "anonymous-layout.pdf"
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        for x, y, text, size in [
            (40, 35, "SYNTHETIC TEST - NOT A REAL INVOICE", 10),
            (40, 80, "Example Trading Ltd", 18),
            (350, 80, "TAX INVOICE", 18),
            (40, 130, "Document ref: DEMO-472", 12),
            (40, 155, "Issued on: 2026-09-12", 12),
            (40, 180, "Currency: SAR", 12),
            (40, 215, "Bill to: Example Buyer Ltd", 12),
            (40, 310, "Product", 12),
            (275, 310, "Units", 12),
            (335, 310, "Each", 12),
            (410, 310, "VAT %", 12),
            (490, 310, "Amount", 12),
            (40, 345, "Cable roll", 12),
            (275, 345, "2", 12),
            (335, 345, "80.00", 12),
            (410, 345, "15%", 12),
            (490, 345, "184.00", 12),
            (40, 380, "Safety gloves", 12),
            (275, 380, "3", 12),
            (335, 380, "10.00", 12),
            (410, 380, "15%", 12),
            (490, 380, "34.50", 12),
            (330, 500, "Net payable", 12),
            (490, 500, "190.00", 12),
            (330, 530, "Value added tax", 12),
            (490, 530, "28.50", 12),
            (330, 565, "Amount to pay", 12),
            (490, 565, "218.50", 12),
        ]:
            page.insert_text((x, y), text, fontsize=size)
        document.save(pdf)
        page.get_pixmap(dpi=180).save(str(DIRECTORY / "anonymous-layout.png"))
    with Image.open(DIRECTORY / "anonymous-layout.png") as image:
        image.thumbnail((1000, 1400))
        image.rotate(3, expand=True, fillcolor="white", resample=Image.Resampling.BICUBIC).save(
            DIRECTORY / "anonymous-camera.jpg", quality=70
        )
    return [pdf, DIRECTORY / "anonymous-layout.png", DIRECTORY / "anonymous-camera.jpg"]


def score(result):
    from evaluate_benchmark import equal

    fields = {
        name: equal(name, result["fields"].get(name, {}).get("value"), value)
        for name, value in EXPECTED.items()
    }
    checks = []
    for index, expected in enumerate(ITEMS):
        row = result["items"][index] if index < len(result["items"]) else {}
        checks.extend(
            equal(
                "grand_total" if name == "document_total" else name,
                row.get(name, {}).get("value"),
                value,
            )
            for name, value in expected.items()
        )
    return {
        "header_correct": sum(fields.values()),
        "header_expected": 7,
        "item_fields_correct": sum(checks),
        "item_fields_expected": 10,
        "predicted_rows": len(result["items"]),
        "invented_discount": any("discount_amount" in row for row in result["items"]),
        "seconds": result["seconds"],
        "local_understanding": result.get("local_understanding"),
    }


def main():
    report = {
        "synthetic_only": True,
        "development_challenge": True,
        "not_real_world_accuracy": True,
        "documents": [],
    }
    for path in generate():
        record = {"file": path.name}
        for mode in ("baseline", "local"):
            result = read_document(path, "en", use_local_vision=mode == "local")
            (DIRECTORY / f"{path.name}.{mode}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            record[mode] = score(result)
            print(path.name, mode, record[mode], flush=True)
        report["documents"].append(record)
    (DIRECTORY / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
