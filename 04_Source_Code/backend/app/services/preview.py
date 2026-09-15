import subprocess
import uuid

from fastapi import HTTPException

from app.core.config import ROOT, get_settings
from app.services.extraction import source_bytes
from app.services.processes import run_bounded


def pdf_preview(attachment, page):
    try:
        data = source_bytes(attachment)
    except (ValueError, OSError):
        raise HTTPException(409, "الملف الأصلي غير متاح أو تغير.") from None
    directory = ROOT / ".local/invoice-previews"
    directory.mkdir(parents=True, exist_ok=True)
    cached = directory / f"{attachment.sha256}-{page}-v1.png"
    if cached.is_file():
        return cached
    if not get_settings().extraction_python.is_file():
        raise HTTPException(503, "معاينة PDF غير مهيأة. يمكنك تحميل الأصل.")
    identifier = uuid.uuid4().hex
    source, output = directory / f"{identifier}.pdf", directory / f"{identifier}.png"
    try:
        source.write_bytes(data)
        returncode = run_bounded(
            [
                str(get_settings().extraction_python),
                str(ROOT / "04_Source_Code/ai/document_intelligence/render_preview.py"),
                "--input",
                str(source),
                "--output",
                str(output),
                "--page",
                str(page),
            ],
            timeout=20,
        )
        if returncode or not output.is_file():
            raise HTTPException(422, "تعذرت معاينة هذه الصفحة. يمكنك تحميل الأصل.")
        output.replace(cached)
        return cached
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "استغرقت المعاينة وقتًا طويلًا. يمكنك تحميل الأصل.") from None
    finally:
        source.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
