"""Bounded parsing for ZATCA TLV QR payloads and UBL invoice XML.

The module extracts review evidence only. It does not validate signatures, clearance,
reporting status, or invoice authenticity.
"""

import base64
import binascii
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

VERSION = "zatca-tlv-ubl-v1"
MAX_QR_TEXT = 700
MAX_XML_BYTES = 2_000_000
MAX_XML_NODES = 20_000
MAX_STRUCTURED_SOURCES = 6
UBL_ROOTS = {
    "Invoice": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "CreditNote": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "DebitNote": "urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2",
}
NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def clean_text(value: str | None, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    value = " ".join(value.replace("\x00", "").split())
    return value[:limit] or None


def decimal_text(value: str | None) -> str | None:
    value = clean_text(value, limit=80)
    if value is None or not re.fullmatch(r"\d{1,18}(?:\.\d{1,4})?", value):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return format(number, "f") if number.is_finite() and number >= 0 else None


def iso_date(value: str | None) -> str | None:
    value = clean_text(value, limit=40)
    if value is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def iso_timestamp(value: str | None) -> tuple[str, str] | None:
    value = clean_text(value, limit=80)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if "T" not in value:
        return None
    return value, parsed.date().isoformat()


def field(value: str | None, evidence: str) -> dict | None:
    value = clean_text(value)
    return {"value": value, "evidence": evidence} if value is not None else None


def parse_zatca_tlv(payload: str, *, page: int, bbox: list[float]) -> dict:
    payload = payload.strip()
    if not payload or len(payload) > MAX_QR_TEXT or not payload.isascii():
        raise ValueError("INVALID_QR_PAYLOAD")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("INVALID_QR_PAYLOAD") from None
    values: dict[int, bytes] = {}
    offset = 0
    previous = 0
    while offset < len(raw):
        if offset + 2 > len(raw):
            raise ValueError("INVALID_QR_PAYLOAD")
        tag, length = raw[offset], raw[offset + 1]
        offset += 2
        if (
            tag < 1
            or tag > 9
            or tag <= previous
            or tag in values
            or offset + length > len(raw)
        ):
            raise ValueError("INVALID_QR_PAYLOAD")
        values[tag] = raw[offset : offset + length]
        offset += length
        previous = tag
    if not all(tag in values for tag in range(1, 6)):
        raise ValueError("INVALID_QR_PAYLOAD")
    try:
        text = {tag: values[tag].decode("utf-8") for tag in range(1, 6)}
    except UnicodeDecodeError:
        raise ValueError("INVALID_QR_PAYLOAD") from None
    timestamp = iso_timestamp(text[3])
    total = decimal_text(text[4])
    tax = decimal_text(text[5])
    seller = field(text[1], "TLV tag 1 — seller name")
    tax_number = field(text[2], "TLV tag 2 — VAT registration number")
    if (
        timestamp is None
        or total is None
        or tax is None
        or seller is None
        or tax_number is None
    ):
        raise ValueError("INVALID_QR_PAYLOAD")
    source_fields = {
        "supplier_name": seller,
        "supplier_tax_number": tax_number,
        "invoice_timestamp": field(timestamp[0], "TLV tag 3 — invoice timestamp"),
        "invoice_date": field(timestamp[1], "TLV tag 3 — invoice timestamp date"),
        "grand_total": field(total, "TLV tag 4 — invoice total with VAT"),
        "tax_total": field(tax, "TLV tag 5 — VAT total"),
    }
    return {
        "type": "QR",
        "location": "DOCUMENT_PAGE",
        "page": page,
        "bbox": bbox,
        "name": None,
        "document_type": "ZATCA_TLV",
        "present_tags": sorted(values),
        "fields": source_fields,
    }


def qr_sources(picture, page: int) -> tuple[list[dict], list[str]]:
    import cv2
    import numpy as np

    pixels = np.array(picture.convert("RGB"))[:, :, ::-1].copy()
    height, width = pixels.shape[:2]
    detector = cv2.QRCodeDetector()
    decoded: list[tuple[str, object]] = []
    try:
        ok, values, points, _ = detector.detectAndDecodeMulti(pixels)
        if ok and points is not None:
            decoded.extend(zip(values, points))
    except (cv2.error, ValueError):
        pass
    if not decoded:
        try:
            value, points, _ = detector.detectAndDecode(pixels)
            if value and points is not None:
                decoded.append((value, points))
        except cv2.error:
            pass
    sources, warnings, seen = [], [], set()
    for value, points in decoded[:MAX_STRUCTURED_SOURCES]:
        if not value or value in seen:
            continue
        seen.add(value)
        coordinates = np.asarray(points).reshape(-1, 2)
        bbox = [
            round(min(1.0, max(0.0, float(coordinates[:, 0].min()) / width)), 5),
            round(min(1.0, max(0.0, float(coordinates[:, 1].min()) / height)), 5),
            round(min(1.0, max(0.0, float(coordinates[:, 0].max()) / width)), 5),
            round(min(1.0, max(0.0, float(coordinates[:, 1].max()) / height)), 5),
        ]
        try:
            sources.append(parse_zatca_tlv(value, page=page, bbox=bbox))
        except ValueError:
            warnings.append("QR_PAYLOAD_NOT_SUPPORTED")
    return sources, warnings


def first_text(root, *paths: str) -> str | None:
    for path in paths:
        node = root.find(path, NS)
        value = clean_text(node.text if node is not None else None)
        if value is not None:
            return value
    return None


def suggestion(value: str | None, evidence: str) -> dict | None:
    value = clean_text(value)
    if value is None:
        return None
    return {
        "value": value,
        "confidence": None,
        "source": "XML",
        "page": None,
        "bbox": None,
        "evidence": evidence,
        "recognition_reads": [value],
        "needs_review": True,
    }


def parse_ubl_xml(
    data: bytes, *, location: str = "UPLOAD", name: str | None = None
) -> tuple[dict, list[dict]]:
    if not data or len(data) > MAX_XML_BYTES:
        raise ValueError("INVALID_XML")
    lowered = data.replace(b"\x00", b"").lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("INVALID_XML")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        raise ValueError("INVALID_XML") from None
    document_type = local_name(root.tag)
    if (
        document_type not in UBL_ROOTS
        or namespace(root.tag) != UBL_ROOTS[document_type]
    ):
        raise ValueError("INVALID_XML")
    if sum(1 for _ in root.iter()) > MAX_XML_NODES:
        raise ValueError("INVALID_XML")

    raw_fields = {
        "supplier_name": (
            first_text(
                root,
                "./cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName",
                "./cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name",
            ),
            "AccountingSupplierParty/Party/RegistrationName",
        ),
        "supplier_tax_number": (
            first_text(
                root,
                "./cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
            ),
            "AccountingSupplierParty/Party/PartyTaxScheme/CompanyID",
        ),
        "invoice_number": (first_text(root, "./cbc:ID"), "ID"),
        "invoice_date": (iso_date(first_text(root, "./cbc:IssueDate")), "IssueDate"),
        "currency": (
            first_text(root, "./cbc:DocumentCurrencyCode"),
            "DocumentCurrencyCode",
        ),
        "subtotal": (
            decimal_text(
                first_text(root, "./cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount")
            ),
            "LegalMonetaryTotal/TaxExclusiveAmount",
        ),
        "tax_total": (
            decimal_text(first_text(root, "./cac:TaxTotal/cbc:TaxAmount")),
            "TaxTotal/TaxAmount",
        ),
        "grand_total": (
            decimal_text(
                first_text(
                    root,
                    "./cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount",
                    "./cac:LegalMonetaryTotal/cbc:PayableAmount",
                )
            ),
            "LegalMonetaryTotal/TaxInclusiveAmount",
        ),
    }
    source_fields = {
        key: entry
        for key, (value, path) in raw_fields.items()
        if (entry := field(value, path)) is not None
    }
    if not source_fields:
        raise ValueError("INVALID_XML")

    line_names = {
        "Invoice": ("InvoiceLine", "InvoicedQuantity"),
        "CreditNote": ("CreditNoteLine", "CreditedQuantity"),
        "DebitNote": ("DebitNoteLine", "DebitedQuantity"),
    }
    line_name, quantity_name = line_names[document_type]
    items = []
    for line in root.findall(f"./cac:{line_name}", NS)[:100]:
        values = {
            "description": suggestion(
                first_text(line, "./cac:Item/cbc:Description", "./cac:Item/cbc:Name"),
                f"{line_name}/Item/Description",
            ),
            "quantity": suggestion(
                decimal_text(first_text(line, f"./cbc:{quantity_name}")),
                f"{line_name}/{quantity_name}",
            ),
            "unit_price": suggestion(
                decimal_text(first_text(line, "./cac:Price/cbc:PriceAmount")),
                f"{line_name}/Price/PriceAmount",
            ),
            "tax_rate": suggestion(
                decimal_text(
                    first_text(line, "./cac:Item/cac:ClassifiedTaxCategory/cbc:Percent")
                ),
                f"{line_name}/Item/ClassifiedTaxCategory/Percent",
            ),
        }
        quantity_node = line.find(f"./cbc:{quantity_name}", NS)
        if quantity_node is not None:
            values["unit"] = suggestion(
                clean_text(quantity_node.attrib.get("unitCode"), limit=40),
                f"{line_name}/{quantity_name}@unitCode",
            )
        allowances = []
        for allowance in line.findall("./cac:AllowanceCharge", NS):
            charge = first_text(allowance, "./cbc:ChargeIndicator")
            amount = decimal_text(first_text(allowance, "./cbc:Amount"))
            if charge == "false" and amount is not None:
                allowances.append(Decimal(amount))
        if allowances:
            values["discount_amount"] = suggestion(
                format(sum(allowances, Decimal("0")), "f"),
                f"{line_name}/AllowanceCharge/Amount",
            )
        item = {key: value for key, value in values.items() if value is not None}
        if all(key in item for key in ("description", "quantity", "unit_price")):
            items.append(item)

    return (
        {
            "type": "XML",
            "location": location,
            "page": None,
            "bbox": None,
            "name": clean_text(Path(name).name, limit=160) if name else None,
            "document_type": document_type,
            "present_tags": [],
            "fields": source_fields,
        },
        items,
    )


def embedded_xml_sources(path: Path) -> tuple[list[dict], list[list[dict]], list[str]]:
    from pypdf import PdfReader

    sources, item_sets, warnings = [], [], []
    try:
        attachments = PdfReader(path, strict=True).attachments
    except Exception:
        return sources, item_sets, ["PDF_ATTACHMENTS_NOT_READABLE"]
    for name, contents in attachments.items():
        if not str(name).lower().endswith(".xml"):
            continue
        for content in contents[:MAX_STRUCTURED_SOURCES]:
            if len(sources) >= MAX_STRUCTURED_SOURCES:
                warnings.append("STRUCTURED_SOURCE_LIMIT_REACHED")
                return sources, item_sets, warnings
            try:
                source, items = parse_ubl_xml(
                    content, location="PDF_ATTACHMENT", name=str(name)
                )
                sources.append(source)
                item_sets.append(items)
            except ValueError:
                warnings.append("EMBEDDED_XML_NOT_SUPPORTED")
    return sources, item_sets, warnings


def source_suggestion(source: dict, value: dict) -> dict:
    return {
        "value": value["value"],
        "confidence": None,
        "source": source["type"],
        "page": source["page"],
        "bbox": source["bbox"],
        "evidence": value["evidence"],
        "recognition_reads": [value["value"]],
        "needs_review": True,
    }


def source_identity(name: str, value: str):
    if name in {"subtotal", "tax_total", "grand_total"}:
        return Decimal(value)
    normalized = unicodedata.normalize("NFKC", value).casefold()
    if name in {"invoice_number", "currency"}:
        return "".join(character for character in normalized if character.isalnum())
    return " ".join(normalized.split())


def merge_structured(
    parsed: dict, sources: list[dict], xml_item_sets: list[list[dict]]
) -> dict:
    fields = dict(parsed["fields"])
    warnings = list(parsed["warnings"])
    importable = {
        "supplier_name",
        "invoice_number",
        "invoice_date",
        "currency",
        "subtotal",
        "tax_total",
        "grand_total",
    }
    for name in importable:
        candidates = [
            (source, source["fields"][name])
            for source in sources
            if name in source["fields"]
        ]
        distinct = {source_identity(name, value["value"]) for _, value in candidates}
        if len(distinct) > 1:
            fields.pop(name, None)
            warnings.append(f"STRUCTURED_SOURCE_CONFLICT_{name.upper()}")
        elif candidates:
            source, value = next(
                (entry for entry in candidates if entry[0]["type"] == "XML"),
                candidates[0],
            )
            if name in fields and fields[name]["value"] != value["value"]:
                warnings.append(f"VISIBLE_TEXT_CONFLICT_{name.upper()}")
            fields[name] = source_suggestion(source, value)

    nonempty_item_sets = [items for items in xml_item_sets if items]
    if len(nonempty_item_sets) == 1:
        if parsed["items"]:
            warnings.append("VISIBLE_ITEMS_REPLACED_BY_XML")
        items = nonempty_item_sets[0]
    elif len(nonempty_item_sets) > 1:
        warnings.append("MULTIPLE_XML_ITEM_SETS")
        items = []
    else:
        items = parsed["items"]
    return {
        **parsed,
        "fields": fields,
        "items": items,
        "warnings": sorted(set(warnings)),
        "structured_sources": sources,
        "structured_version": VERSION,
    }
