"""Evidence-based label/column parsing. Missing or ambiguous values remain unknown."""

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

VERSION = "labels-and-columns-v4"
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")
LABELS = {
    "supplier_name": ["supplier", "seller", "vendor", "المورد", "البائع"],
    "invoice_number": ["invoice number", "invoice no", "invoice #", "رقم الفاتورة", "رقم فاتورة"],
    "invoice_date": [
        "invoice date",
        "issue date",
        "date",
        "تاريخ الفاتورة",
        "تاريخ الاصدار",
        "التاريخ",
    ],
    "currency": ["currency", "العملة"],
    "subtotal": [
        "subtotal",
        "sub total",
        "total excl vat",
        "total excluding vat",
        "المجموع قبل الضريبة",
        "الاجمالي قبل الضريبة",
    ],
    "tax_total": [
        "vat total",
        "total vat",
        "tax total",
        "total tax",
        "اجمالي الضريبة",
        "مجموع الضريبة",
    ],
    "grand_total": [
        "grand total",
        "amount due",
        "total due",
        "الاجمالي المستحق",
        "اجمالي الفاتورة",
        "المبلغ المستحق",
        "المجموع الكلي",
    ],
}
COLUMNS = {
    "description": ["description", "item description", "product", "الوصف", "البيان", "الصنف"],
    "quantity": ["qty", "quantity", "الكمية"],
    "unit_price": ["unit price", "price", "rate", "سعر الوحدة", "السعر"],
    "discount_amount": ["discount", "خصم", "الخصم"],
    "tax_rate": ["tax %", "vat %", "الضريبة", "نسبة الضريبة"],
    "document_total": ["total", "amount", "الاجمالي"],
}


def normalize(value):
    value = unicodedata.normalize("NFKC", value).translate(DIGITS)
    value = re.sub(r"[\u064b-\u065f\u0670\u0640\u200e\u200f\u202a-\u202e]", "", value)
    return " ".join(value.split())


def key(value):
    return (
        normalize(value).lower().replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").strip(" :.#")
    )


def one_edit_apart(left, right):
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    shorter, longer = sorted((left, right), key=len)
    return any(longer[:i] + longer[i + 1 :] == shorter for i in range(len(longer)))


def label_match(text, labels, *, approximate=False):
    normalized = key(text)
    if normalized in [key(label) for label in labels]:
        return "exact"
    # A single OCR error in a long Arabic label can be suggested, never in its value.
    if approximate and len(normalized) >= 6 and re.fullmatch(r"[\u0621-\u064a ]+", normalized):
        if any(one_edit_apart(normalized, key(label)) for label in labels):
            return "approximate"
    return None


def layout_box(token):
    return token.get("layout_bbox", token["bbox"])


def decimal(value, *, percentage=False):
    if not percentage and re.search(r"[%٪]", value):
        return None
    value = normalize(value).replace("%", "").replace("٪", "").strip()
    value = re.sub(r"\b(SAR|AED|USD|EUR)\b", "", value, flags=re.I).strip()
    # Commas are accepted only as valid thousands groups, never guessed as decimal separators.
    if "," in value:
        if not re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d{1,4})?", value):
            return None
        value = value.replace(",", "")
    if not re.fullmatch(r"\d{1,18}(\.\d{1,4})?", value):
        return None
    try:
        number = Decimal(value)
        if number < 0 or (percentage and number > 100):
            return None
        return format(number, "f")
    except InvalidOperation:
        return None


def lines(tokens):
    grouped = []
    for token in sorted(
        tokens,
        key=lambda t: (t["page"], (layout_box(t)[1] + layout_box(t)[3]) / 2, layout_box(t)[0]),
    ):
        box = layout_box(token)
        center = (box[1] + box[3]) / 2
        group = next(
            (
                g
                for g in reversed(grouped[-8:])
                if g["page"] == token["page"]
                and abs(g["y"] - center) < max(0.007, (box[3] - box[1]) * 0.5)
            ),
            None,
        )
        if group is None:
            group = {"page": token["page"], "y": center, "tokens": []}
            grouped.append(group)
        group["tokens"].append(token)
    return grouped


def text_of(tokens):
    arabic = sum(bool(re.search(r"[\u0600-\u06ff]", t["text"])) for t in tokens)
    return " ".join(
        t["text"] for t in sorted(tokens, key=lambda t: layout_box(t)[0], reverse=arabic > 0)
    )


def candidate(value, tokens):
    scores = [t["confidence"] for t in tokens if t["confidence"] is not None]
    return {
        "value": value,
        "confidence": min(scores) if scores else None,
        "source": tokens[0]["source"],
        "page": tokens[0]["page"],
        "evidence": text_of(tokens),
        "recognition_reads": [
            read for token in tokens for read in (token.get("recognition_reads") or [token["text"]])
        ],
        "bbox": [
            min(t["bbox"][0] for t in tokens),
            min(t["bbox"][1] for t in tokens),
            max(t["bbox"][2] for t in tokens),
            max(t["bbox"][3] for t in tokens),
        ],
        "needs_review": True,
    }


def value_for(field, value):
    value = normalize(value).strip(" :.#")
    if field in ("subtotal", "tax_total", "grand_total"):
        return decimal(value)
    if field == "currency":
        return value.upper() if value.upper() in ("SAR", "AED", "USD", "EUR") else None
    if field == "invoice_date":
        try:
            value = re.sub(r"[ T]\d{2}:\d{2}(?::\d{2})?$", "", value)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return date.fromisoformat(value).isoformat()
            match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", value)
            if match:
                first, second, year = map(int, match.groups())
                # Only unambiguous dates; never choose a locale from appearance alone.
                if first > 12 or first == second:
                    return date(year, second, first).isoformat()
                if second > 12:
                    return date(year, first, second).isoformat()
            return None
        except ValueError:
            return None
    if field == "invoice_number":
        return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_-]{0,99}", value) else None
    return value if 2 <= len(value) <= 200 else None


def parse(tokens):
    from .spatial_parser import field_choices, finish_fields, table_items

    groups = lines(tokens)
    fields = {}
    warnings = sorted(
        {
            "SECOND_READING_" + token["supplemented_field"].upper()
            for token in tokens
            if "supplemented_field" in token
        }
    )
    for field, labels in LABELS.items():
        choices = field_choices(field, tokens)
        for group in groups:
            # A spatially resolved label takes precedence over concatenating a whole
            # row, which can contain unrelated values from an adjacent summary table.
            if any(entry.get("anchor_id") in {id(t) for t in group["tokens"]} for entry in choices):
                continue
            content = normalize(re.sub(r"[:#]", " ", text_of(group["tokens"])))
            for label in sorted(labels, key=len, reverse=True):
                label = key(label)
                words = content.split()
                count = len(label.split())
                prefix = " ".join(words[:count])
                match = label_match(
                    prefix, [label], approximate=all(t["source"] == "OCR" for t in group["tokens"])
                )
                # Do not accept an approximate prefix which also names a different field.
                other = any(
                    label_match(prefix, variants)
                    for name, variants in LABELS.items()
                    if name != field
                )
                if match and not other:
                    value = value_for(field, " ".join(words[count:]))
                    if value is not None:
                        entry = candidate(value, group["tokens"])
                        entry["label_match"] = match
                        choices.append(entry)
                        if match == "approximate":
                            warnings.append(f"APPROXIMATE_LABEL_{field.upper()}")
                    break
        distinct = {entry["value"] for entry in choices}
        if len(distinct) == 1:
            fields[field] = choices[0]
        elif len(distinct) > 1:
            warnings.append(f"AMBIGUOUS_{field.upper()}")
    finish_fields(fields, warnings, tokens)
    items = table_items(tokens, warnings)
    if not items:
        warnings.append("ITEMS_NOT_RELIABLY_IDENTIFIED")
    return {
        "parser_version": VERSION,
        "fields": fields,
        "items": items,
        "warnings": sorted(set(warnings)),
        "requires_human_review": True,
    }
