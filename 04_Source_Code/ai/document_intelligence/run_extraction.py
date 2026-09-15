"""Isolated OCR process. Runtime reads local files and writes suggestions, never invoice records."""

import argparse
import json
from pathlib import Path

from invoice_extraction.reader import model, read_document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-models", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--language", choices=["ar", "en"], default="ar")
    parser.add_argument(
        "--no-local-vision",
        action="store_true",
        help="Baseline evaluation without local visual interpretation",
    )
    args = parser.parse_args()
    if args.prepare_models:
        from invoice_extraction.page_preparation import orientation_model

        orientation_model(download=True)
        for language in ("ar", "en"):
            model(language, download=True)
            print(f"Model ready: {language}", flush=True)
        return
    if not args.input or not args.output:
        parser.error("--input and --output are required")
    result = read_document(args.input, args.language, use_local_vision=not args.no_local_vision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    print("Extraction complete", flush=True)


if __name__ == "__main__":
    main()
