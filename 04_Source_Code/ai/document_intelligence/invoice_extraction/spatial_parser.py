"""Spatial interpretation of labels and table cells in the existing extraction parser."""

import re
from decimal import Decimal

from .parser import (
    COLUMNS,
    LABELS,
    candidate,
    decimal,
    key,
    label_match,
    layout_box,
    lines,
    text_of,
    value_for,
)


def center(token, axis):
    box = layout_box(token)
    return (box[axis] + box[axis + 2]) / 2


def explicit_label(field, text):
    normalized = key(text).replace("/", " ").strip()
    if label_match(normalized, LABELS[field]):
        return True
    bilingual = {
        "invoice_number": r"(?:invoice\s*فاتورة|فاتورة)" if not text.endswith("/") else r"invoice",
        "invoice_date": r"date\s*التاريخ(?: ا)?",
    }
    return bool(field in bilingual and re.fullmatch(bilingual[field], normalized))


def field_choices(field, tokens):
    if field == "supplier_name":
        return []  # A name may span several native PDF words; keep its full labeled line.
    choices = []
    for label in tokens:
        text = label["text"]
        # A bilingual date and its timestamp can be one detected text region.
        inline_date = re.fullmatch(r"(?i)date\s*[/ :]\s*(.+)", text)
        if field == "invoice_date" and inline_date:
            value = value_for(field, inline_date[1])
            if value:
                entry = candidate(value, [label])
                entry["anchor_id"] = id(label)
                choices.append(entry)
        if not explicit_label(field, text):
            continue
        box = layout_box(label)
        rtl = not re.search("[A-Za-z]", text)
        nearby = []
        for token in tokens:
            if token is label or token["page"] != label["page"]:
                continue
            b = layout_box(token)
            dy = abs(center(token, 1) - center(label, 1))
            if dy > max(b[3] - b[1], box[3] - box[1]) * 0.55:
                continue
            gap = box[0] - b[2] if rtl else b[0] - box[2]
            if gap < -0.005:
                continue
            value = value_for(field, token["text"])
            if value is None or (field == "invoice_number" and not re.search(r"\d", value)):
                continue
            # Do not jump over another label to steal that label's value.
            if any(
                other is not label
                and other is not token
                and other["page"] == label["page"]
                and min(center(label, 0), center(token, 0))
                < center(other, 0)
                < max(center(label, 0), center(token, 0))
                and abs(center(other, 1) - center(label, 1)) < (box[3] - box[1]) * 0.6
                and any(explicit_label(name, other["text"]) for name in LABELS)
                for other in tokens
            ):
                continue
            nearby.append((gap, dy, value, token))
        if nearby:
            nearby.sort(key=lambda item: (item[0], item[1]))
            _, _, value, token = nearby[0]
            entry = candidate(value, [label, token])
            entry["anchor_id"] = id(label)
            choices.append(entry)
    return choices


def finish_fields(fields, warnings, tokens):
    if "currency" not in fields and "AMBIGUOUS_CURRENCY" not in warnings:
        codes = [
            (code.upper(), t)
            for t in tokens
            for code in re.findall(r"\b(?:SAR|AED|USD|EUR)\b", t["text"], re.I)
        ]
        if len({code for code, _ in codes}) == 1:
            fields["currency"] = candidate(codes[0][0], [codes[0][1]])
        elif codes:
            warnings.append("AMBIGUOUS_CURRENCY")
    if "supplier_name" not in fields and "AMBIGUOUS_SUPPLIER_NAME" not in warnings:
        titles = [
            t
            for t in tokens
            if t["page"] == 1
            and (
                key(t["text"]) in ("tax invoice", "فاتورة ضريبية")
                or explicit_label("invoice_number", t["text"])
            )
        ]
        cutoff = min((layout_box(t)[1] for t in titles), default=0)
        names = [
            t
            for t in tokens
            if t["page"] == 1
            and layout_box(t)[3] < cutoff
            and re.match(r"^(?:مؤسسة|شركة)\s+\S", t["text"])
        ]
        if len(names) == 1:
            fields["supplier_name"] = candidate(names[0]["text"], [names[0]])
            warnings.append("SUPPLIER_FROM_DOCUMENT_HEADER")
    # Bare VAT is a summary label only between explicit subtotal and grand-total
    # anchors, in their column. VAT registration IDs and table rates are excluded.
    if "tax_total" not in fields and "AMBIGUOUS_TAX_TOTAL" not in warnings:
        lower = [t for t in tokens if explicit_label("grand_total", t["text"])]
        upper = [t for t in tokens if explicit_label("subtotal", t["text"])]
        choices = []
        for label in tokens:
            if key(label["text"]) not in ("vat", "tax", "ضريبة القيمة المضافة"):
                continue
            if not any(
                a["page"] == label["page"] == b["page"]
                and center(a, 1) < center(label, 1) < center(b, 1)
                and abs(layout_box(a)[0] - layout_box(label)[0]) < 0.025
                and abs(layout_box(b)[0] - layout_box(label)[0]) < 0.025
                for a in upper
                for b in lower
            ):
                continue
            alias = dict(
                label,
                text="VAT total",
                recognition_reads=label.get("recognition_reads") or [label["text"]],
            )
            for entry in field_choices(
                "tax_total", [alias, *[t for t in tokens if t is not label]]
            ):
                if entry.get("anchor_id") == id(alias):
                    entry["evidence"] = entry["evidence"].replace("VAT total", label["text"])
                    choices.append(entry)
        if len({c["value"] for c in choices}) == 1:
            fields["tax_total"] = choices[0]
        elif choices:
            warnings.append("AMBIGUOUS_TAX_TOTAL")
    if all(name in fields for name in ("subtotal", "tax_total", "grand_total")):
        if abs(
            Decimal(fields["subtotal"]["value"])
            + Decimal(fields["tax_total"]["value"])
            - Decimal(fields["grand_total"]["value"])
        ) > Decimal("0.02"):
            warnings.append("DOCUMENT_TOTALS_DO_NOT_RECONCILE")
    for entry in fields.values():
        entry.pop("anchor_id", None)


TABLE_LABELS = {
    **COLUMNS,
    "description": [*COLUMNS["description"], "itemdescription"],
    "discount_amount": [*COLUMNS["discount_amount"], "disc"],
    "net_amount": ["net", "net amount"],
    "vat_amount": ["vat amt", "vat am", "vat amount", "tax amount"],
}


def header_field(text, *, approximate=False):
    matches = [name for name, labels in TABLE_LABELS.items() if label_match(text, labels)]
    if not matches and approximate:
        matches = [
            name
            for name, labels in TABLE_LABELS.items()
            if label_match(text, labels, approximate=True)
        ]
    return matches[0] if len(matches) == 1 else None


def table_items(tokens, warnings):
    items, seen = [], set()
    anchors = [
        t
        for t in tokens
        if header_field(t["text"], approximate=t["source"] == "OCR") == "description"
    ]
    for anchor in anchors:
        box = layout_box(anchor)
        height = box[3] - box[1]
        band = [
            t
            for t in tokens
            if t["page"] == anchor["page"]
            and box[1] - height * 0.6 <= layout_box(t)[1] <= box[3] + height * 1.6
        ]
        phrases = []
        for row in lines(band):
            ordered_tokens = sorted(row["tokens"], key=lambda t: layout_box(t)[0])
            for start in range(len(ordered_tokens)):
                for length in (3, 2):
                    parts = ordered_tokens[start : start + length]
                    if len(parts) != length or any(
                        layout_box(b)[0] - layout_box(a)[2] > 0.025
                        for a, b in zip(parts, parts[1:])
                    ):
                        continue
                    phrase = text_of(parts)
                    if header_field(phrase, approximate=all(t["source"] == "OCR" for t in parts)):
                        combined = dict(parts[0], text=phrase)
                        combined["layout_bbox"] = [
                            min(layout_box(t)[0] for t in parts),
                            min(layout_box(t)[1] for t in parts),
                            max(layout_box(t)[2] for t in parts),
                            max(layout_box(t)[3] for t in parts),
                        ]
                        phrases.append(combined)
        columns, evidence = {}, {}
        for t in [*phrases, *band]:
            field = header_field(t["text"], approximate=t["source"] == "OCR")
            if field:
                if header_field(t["text"]) is None:
                    warnings.append(f"APPROXIMATE_COLUMN_{field.upper()}")
                # 'Amount' below 'Net' belongs to that column, not the final total.
                if (
                    field == "document_total"
                    and key(t["text"]) == "amount"
                    and any(
                        key(o["text"]) == "net" and abs(center(o, 0) - center(t, 0)) < 0.04
                        for o in band
                    )
                ):
                    field = "net_amount"
                columns.setdefault(field, center(t, 0))
                evidence.setdefault(field, t)
        if not all(name in columns for name in ("description", "quantity", "unit_price")):
            continue
        # Some narrow VAT headers are detected as one region spanning two columns.
        for t in band:
            if key(t["text"]) in ("vat vat amt", "vat vat am", "vat vat amount"):
                b = layout_box(t)
                columns["tax_rate"] = b[0] + (b[2] - b[0]) * 0.22
                columns["vat_amount"] = b[0] + (b[2] - b[0]) * 0.78
                evidence["tax_rate"] = t
            elif key(t["text"]) == "vat" and "vat_amount" in columns:
                columns["tax_rate"] = center(t, 0)
                evidence["tax_rate"] = t
        ordered = sorted(columns, key=columns.get)
        boundaries = [(columns[a] + columns[b]) / 2 for a, b in zip(ordered, ordered[1:])]
        header_bottom = max(layout_box(t)[3] for t in evidence.values())
        stop = min(
            (
                layout_box(t)[1]
                for t in tokens
                if t["page"] == anchor["page"]
                and layout_box(t)[1] > header_bottom
                and any(
                    explicit_label(name, t["text"])
                    or any(key(t["text"]).startswith(key(v) + " ") for v in LABELS[name])
                    for name in ("subtotal", "tax_total", "grand_total")
                )
            ),
            default=1,
        )
        body = [
            t for t in tokens if t["page"] == anchor["page"] and header_bottom < center(t, 1) < stop
        ]
        for row in lines(body):
            cells = {name: [] for name in ordered}
            for t in row["tokens"]:
                # A row ordinal to the left of the description is not item text.
                if ordered[0] == "description" and center(t, 0) < box[0] - 0.015:
                    continue
                cells[ordered[sum(center(t, 0) > boundary for boundary in boundaries)]].append(t)
            parsed = {}
            for name, cell in cells.items():
                if not cell or name in ("net_amount", "vat_amount"):
                    continue
                text = text_of(cell)
                if name == "description":
                    value = text if re.search(r"[A-Za-z\u0621-\u064a]", text) else None
                else:
                    # An explicit VAT rate header can express percent without a
                    # repeated percent symbol in each cell. VAT amount is separate.
                    if (
                        name == "tax_rate"
                        and not re.search(r"[%٪]", text)
                        and "vat_amount" not in columns
                    ):
                        continue
                    value = decimal(text, percentage=name == "tax_rate")
                if value is not None:
                    parsed[name] = candidate(value, cell)
            signature = tuple(sorted(id(t) for t in row["tokens"]))
            if (
                all(name in parsed for name in ("description", "quantity", "unit_price"))
                and Decimal(parsed["quantity"]["value"]) > 0
                and signature not in seen
            ):
                items.append(parsed)
                seen.add(signature)
            if len(items) == 100:
                warnings.append("ITEM_LIMIT_REACHED")
                return items
    return items
