"""Create clearly synthetic Arabic/English invoice fixtures with independent expected values."""

import argparse
import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import arabic_reshaper
import pypdfium2 as pdfium
from bidi.algorithm import get_display
from PIL import ImageEnhance, ImageFilter
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[3]


def money(value):
    return format(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "05_Data/Sample_Invoices/Synthetic_OCR_v1"
    )
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/arial.ttf"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(TTFont("InvoiceFont", str(args.font)))
    records = []
    for language in ("en", "ar"):
        for variant in range(3):
            sample_id = f"{language}-{variant + 1:02}"
            expected = {
                "supplier_name": "مؤسسة مواد التجربة"
                if language == "ar"
                else "Sample Materials Store",
                "invoice_number": f"{language.upper()}-2026-{110 + variant}",
                "invoice_date": f"2026-09-{10 + variant:02}",
                "currency": "SAR",
                "items": [
                    {
                        "description": "اسمنت ابيض" if language == "ar" else "White cement",
                        "quantity": str(2 + variant),
                        "unit_price": "40.00",
                        "discount_amount": "0.00",
                        "tax_rate": "15",
                    },
                    {
                        "description": "ادوات صيانة" if language == "ar" else "Repair tools",
                        "quantity": "3",
                        "unit_price": "12.50",
                        "discount_amount": "0.00",
                        "tax_rate": "15",
                    },
                ],
            }
            subtotal = sum(
                Decimal(i["quantity"]) * Decimal(i["unit_price"]) for i in expected["items"]
            )
            taxes = sum(
                Decimal(money(Decimal(i["quantity"]) * Decimal(i["unit_price"]) * Decimal("0.15")))
                for i in expected["items"]
            )
            expected.update(
                subtotal=money(subtotal),
                tax_total=money(taxes),
                grand_total=money(subtotal + taxes),
            )
            pdf_path = args.output / f"{sample_id}-digital.pdf"
            canvas = Canvas(str(pdf_path), pagesize=(595, 842), invariant=1)
            canvas.setTitle("Synthetic invoice - not payable")

            def write(x, y, value, size=12, right=False):
                value = (
                    get_display(arabic_reshaper.reshape(str(value)))
                    if language == "ar"
                    else str(value)
                )
                # Direction marks guide bidi ordering but must not become PDF glyphs.
                value = value.replace("\u200e", "").replace("\u200f", "")
                canvas.setFont("InvoiceFont", size)
                (canvas.drawRightString if right else canvas.drawString)(x, y, value)

            canvas.setFillColor(HexColor("#115e59" if variant != 2 else "#343f55"))
            canvas.rect(0, 730, 595, 112, fill=1, stroke=0)
            canvas.setFillColor(HexColor("#ffffff"))
            write(
                550 if language == "ar" else 45,
                795,
                "فاتورة تجريبية" if language == "ar" else "SAMPLE INVOICE",
                23,
                language == "ar",
            )
            write(
                550 if language == "ar" else 45,
                765,
                "مستند مصطنع للاختبار فقط"
                if language == "ar"
                else "Synthetic data for OCR evaluation",
                12,
                language == "ar",
            )
            canvas.setFillColor(HexColor("#202a30"))
            labels = [
                ("المورد" if language == "ar" else "Supplier", expected["supplier_name"]),
                ("رقم الفاتورة" if language == "ar" else "Invoice No", expected["invoice_number"]),
                (
                    "تاريخ الفاتورة" if language == "ar" else "Invoice Date",
                    expected["invoice_date"],
                ),
                ("العملة" if language == "ar" else "Currency", expected["currency"]),
            ]
            # Distinct positions/spacing in the held-out layout; parser receives no layout ID.
            for index, (label, value) in enumerate(labels):
                y = 690 - index * (33 if variant != 2 else 39)
                if variant == 1:
                    display_value = f"\u200e{value}\u200e" if language == "ar" else value
                    write(
                        550 if language == "ar" else 45,
                        y,
                        f"{label}: {display_value}",
                        13,
                        language == "ar",
                    )
                elif language == "ar":
                    write(550, y, label, 13, True)
                    write(365, y, value, 13, True)
                else:
                    write(45, y, label, 13)
                    write(220, y, value, 13)
            columns = [
                (45, "Description"),
                (240, "Qty"),
                (305, "Unit price"),
                (380, "Discount"),
                (450, "Tax %"),
                (515, "Total"),
            ]
            if language == "ar":
                columns = [
                    (45, "الاجمالي"),
                    (130, "الضريبة"),
                    (200, "خصم"),
                    (285, "السعر"),
                    (360, "الكمية"),
                    (500, "الوصف"),
                ]
            canvas.setFillColor(HexColor("#e8eeee"))
            canvas.rect(35, 487, 525, 33, fill=1, stroke=0)
            canvas.setFillColor(HexColor("#202a30"))
            for x, label in columns:
                write(x, 498, label, 11)
            for index, item in enumerate(expected["items"]):
                y = 459 - index * 45
                total = money(
                    Decimal(item["quantity"]) * Decimal(item["unit_price"]) * Decimal("1.15")
                )
                cells = [
                    item["description"],
                    item["quantity"],
                    item["unit_price"],
                    item["discount_amount"],
                    item["tax_rate"] + "%",
                    total,
                ]
                if language == "ar":
                    cells.reverse()
                for (x, _), value in zip(columns, cells):
                    write(
                        550 if language == "ar" and x == 500 else x,
                        y,
                        value,
                        11,
                        language == "ar" and x == 500,
                    )
                canvas.setStrokeColor(HexColor("#d9dfdf"))
                canvas.line(35, y - 17, 560, y - 17)
            for index, (label, key) in enumerate(
                [
                    ("المجموع قبل الضريبة" if language == "ar" else "Subtotal", "subtotal"),
                    ("اجمالي الضريبة" if language == "ar" else "VAT total", "tax_total"),
                    ("الاجمالي المستحق" if language == "ar" else "Grand total", "grand_total"),
                ]
            ):
                y = 332 - index * 34
                write(550 if language == "ar" else 330, y, label, 12, language == "ar")
                write(310 if language == "ar" else 510, y, expected[key], 13, language == "ar")
            canvas.setFillColor(HexColor("#8c3939"))
            write(
                550 if language == "ar" else 45,
                120,
                "ليست مطالبة مالية ولا تصلح للدفع"
                if language == "ar"
                else "NOT A REAL INVOICE - NOT PAYABLE",
                12,
                language == "ar",
            )
            canvas.setFillColor(HexColor("#657171"))
            write(45, 65, f"OCR benchmark v1 / {sample_id} / 1", 9)
            canvas.save()
            with pdfium.PdfDocument(pdf_path) as document:
                picture = document[0].render(scale=2.5).to_pil().convert("RGB")
            image_path = args.output / f"{sample_id}-scan.png"
            if variant == 2:
                picture = (
                    ImageEnhance.Contrast(picture)
                    .enhance(0.70)
                    .filter(ImageFilter.GaussianBlur(0.45))
                )
                picture = picture.rotate(1.2, expand=True, fillcolor="white")
            picture.save(image_path)
            for file, kind in ((pdf_path, "digital_pdf"), (image_path, "image")):
                records.append(
                    {
                        "id": file.stem,
                        "file": file.name,
                        "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                        "language": language,
                        "kind": kind,
                        "split": "evaluation" if variant == 2 else "development",
                        "family": sample_id,
                        "synthetic": True,
                        "expected": expected,
                    }
                )
    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "purpose": "Synthetic smoke benchmark, not real-world accuracy",
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Created {len(records)} labeled synthetic samples in {args.output}")


if __name__ == "__main__":
    main()
