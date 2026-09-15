import hashlib
import io
import re
import warnings
from pathlib import Path
from xml.etree import ElementTree

from fastapi import HTTPException
from PIL import Image
from pypdf import PdfReader

UBL_ROOTS = {
    "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice",
    "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote",
    "{urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2}DebitNote",
}
MAX_XML_NODES = 20_000


def validate_xml(data: bytes):
    lowered = data.replace(b"\x00", b"").lower()
    if not data or b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("Unsupported XML")
    root = ElementTree.fromstring(data)
    if root.tag not in UBL_ROOTS or sum(1 for _ in root.iter()) > MAX_XML_NODES:
        raise ValueError("Unsupported XML")


def validate_document(data: bytes, filename: str) -> tuple[str, str, str]:
    name = re.sub(r"[\x00-\x1f\x7f]", "", filename.replace("\\", "/").split("/")[-1])[:160]
    extension = Path(name).suffix.lower()
    try:
        if extension == ".pdf" and data.startswith(b"%PDF-"):
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
                raise ValueError("Unsupported PDF")
            media = "application/pdf"
        elif extension in {".jpg", ".jpeg", ".png"}:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    expected = "PNG" if extension == ".png" else "JPEG"
                    if image.format != expected or image.width * image.height > 20_000_000:
                        raise ValueError("Unsupported image")
                    image.verify()
            media = "image/png" if extension == ".png" else "image/jpeg"
        elif extension == ".xml" and len(data) <= 2_000_000:
            validate_xml(data)
            media = "application/xml"
        else:
            raise ValueError("Unsupported document")
    except Exception as exc:
        raise HTTPException(
            422, "الملف غير صالح. ارفع PDF غير مشفر أو صورة JPEG أو PNG أو ملف UBL XML صالحًا."
        ) from exc
    return name or f"invoice{extension}", media, hashlib.sha256(data).hexdigest()
