"""Measure actual outputs; keep failed/missing predictions in the denominators."""

import argparse
import hashlib
import json
import platform
import time
from collections import defaultdict
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

import psutil
from invoice_extraction.parser import VERSION, normalize
from invoice_extraction.reader import read_document

ROOT = Path(__file__).resolve().parents[3]
HEADERS = (
    "supplier_name",
    "invoice_number",
    "invoice_date",
    "currency",
    "subtotal",
    "tax_total",
    "grand_total",
)
ITEM_FIELDS = ("description", "quantity", "unit_price", "discount_amount", "tax_rate")


def equal(field, prediction, expected):
    if prediction is None:
        return False
    if field in (
        "subtotal",
        "tax_total",
        "grand_total",
        "quantity",
        "unit_price",
        "discount_amount",
        "tax_rate",
    ):
        return Decimal(prediction) == Decimal(expected)
    return normalize(prediction) == normalize(expected)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-vision", action="store_true")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "05_Data/Sample_Invoices/Synthetic_OCR_v1/manifest.json",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "06_Testing_Evaluation/Results/OCR_BENCHMARK_V2.json"
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    details = []
    groups = defaultdict(
        lambda: {
            "documents": 0,
            "header_correct": 0,
            "header_expected": 0,
            "item_fields_correct": 0,
            "item_fields_expected": 0,
            "rows_expected": 0,
            "rows_predicted": 0,
            "rows_exact": 0,
            "failures": 0,
            "seconds": 0,
        }
    )
    output_dir = ROOT / "05_Data/Processed_Data" / args.output.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    process = psutil.Process()
    for record in manifest["records"]:
        path = args.manifest.parent / record["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise RuntimeError("Sample hash changed: " + record["id"])
        started = time.perf_counter()
        failure = None
        try:
            result = read_document(path, record["language"], use_local_vision=args.local_vision)
        except Exception as exc:
            result = {"fields": {}, "items": []}
            failure = type(exc).__name__ + ": " + str(exc)
        elapsed = time.perf_counter() - started
        (output_dir / f"{record['id']}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        header_checks = {
            field: equal(
                field, result["fields"].get(field, {}).get("value"), record["expected"][field]
            )
            for field in HEADERS
        }
        item_checks = []
        for index, expected in enumerate(record["expected"]["items"]):
            predicted = result["items"][index] if index < len(result["items"]) else {}
            item_checks.append(
                {
                    field: equal(field, predicted.get(field, {}).get("value"), expected[field])
                    for field in ITEM_FIELDS
                }
            )
        measurements = {
            "documents": 1,
            "header_correct": sum(header_checks.values()),
            "header_expected": len(HEADERS),
            "item_fields_correct": sum(sum(check.values()) for check in item_checks),
            "item_fields_expected": len(item_checks) * len(ITEM_FIELDS),
            "rows_expected": len(item_checks),
            "rows_predicted": len(result["items"]),
            "rows_exact": sum(all(check.values()) for check in item_checks),
            "failures": int(failure is not None),
            "seconds": round(elapsed, 3),
        }
        for group_name in (
            "all",
            record["language"],
            record["kind"],
            record["split"],
            f"{record['language']}/{record['kind']}",
        ):
            for key, value in measurements.items():
                groups[group_name][key] += value
        memory = process.memory_info()
        details.append(
            {
                "id": record["id"],
                "sha256": record["sha256"],
                "split": record["split"],
                "reader_version": result.get("reader_version", "failed"),
                "header_checks": header_checks,
                "item_checks": item_checks,
                **measurements,
                "process_peak_rss_mb": round(getattr(memory, "peak_wset", memory.rss) / 1024**2, 1),
                "error": failure,
                "local_understanding": result.get("local_understanding"),
            }
        )
        print(
            f"{record['id']}: header {measurements['header_correct']}/7; item fields {measurements['item_fields_correct']}/10; {elapsed:.2f}s",
            flush=True,
        )
    report = {
        "benchmark_version": 1,
        "local_vision_enabled": args.local_vision,
        "parser_version": VERSION,
        "reader_versions": sorted({detail["reader_version"] for detail in details}),
        "synthetic_only": True,
        "not_real_world_accuracy": True,
        "split_note": manifest.get(
            "split_note",
            "Families 01/02 for development, 03 initially reserved but subsequently inspected; now a regression set. All are synthetic layouts from one generator, not independent supplier invoices.",
        ),
        "comparison": "Strict field equality after Unicode/space/digit normalization; exact Decimal comparison for amounts. Items compared in printed order. Missing predictions and failures count as incorrect. OCR confidence is not calibrated field accuracy.",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            **{
                package: version(package)
                for package in ("paddleocr", "paddlepaddle", "paddlex", "PyMuPDF", "pypdfium2")
            },
        },
        "groups": dict(groups),
        "documents": details,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Report:", args.output)


if __name__ == "__main__":
    main()
