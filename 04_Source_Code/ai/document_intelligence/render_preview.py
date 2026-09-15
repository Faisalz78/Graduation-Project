"""Render one private PDF page; called in a timeout-bounded process by the API."""

import argparse
from pathlib import Path

import pypdfium2 as pdfium


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--page", type=int, required=True)
    args = parser.parse_args()
    with pdfium.PdfDocument(args.input) as document:
        if not 1 <= args.page <= min(len(document), 3):
            raise ValueError("PAGE_UNAVAILABLE")
        page = document[args.page - 1]
        scale = min(2.5, 1600 / max(page.get_size()))
        picture = page.render(scale=scale).to_pil().convert("RGB")
        picture.save(args.output, format="PNG")


if __name__ == "__main__":
    main()
