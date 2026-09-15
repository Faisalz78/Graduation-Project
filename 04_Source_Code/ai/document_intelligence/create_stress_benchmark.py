"""Image perturbations of known synthetic layouts, explicitly not a held-out dataset."""

import hashlib
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]


def main():
    source = ROOT / "05_Data/Sample_Invoices/Synthetic_OCR_v1"
    output = ROOT / "05_Data/Sample_Invoices/Synthetic_OCR_stress_v2"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    records = []
    output.mkdir(parents=True, exist_ok=True)
    for language in ("ar", "en"):
        record = next(row for row in manifest["records"] if row["id"] == f"{language}-02-scan")
        path = source / record["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("SOURCE_HASH_CHANGED")
        with Image.open(path) as opened:
            original = opened.convert("RGB")
        for name, angle, scale, quality in (
            ("rotated-jpeg", -3.5, 1, 80),
            ("small-jpeg", 0, 0.45, 60),
        ):
            picture = original.resize(
                (round(original.width * scale), round(original.height * scale)),
                Image.Resampling.LANCZOS,
            )
            if angle:
                picture = picture.rotate(
                    angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white"
                )
            sample_id = f"{language}-{name}"
            filename = output / f"{sample_id}.jpg"
            picture.save(filename, quality=quality)
            records.append(
                {
                    **record,
                    "id": sample_id,
                    "file": filename.name,
                    "sha256": hashlib.sha256(filename.read_bytes()).hexdigest(),
                    "split": "stress",
                    "source_sha256": record["sha256"],
                    "transformation": {"angle": angle, "scale": scale, "jpeg_quality": quality},
                }
            )
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "split_note": "Four image perturbations of known synthetic family 02. Fresh image conditions, not independent invoices or an unseen layout; no real-world accuracy claim.",
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Created {len(records)} synthetic stress images")


if __name__ == "__main__":
    main()
