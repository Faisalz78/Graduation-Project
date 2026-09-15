import re
import unicodedata
from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher
from statistics import median

from sqlalchemy import select

from app.models import ExtractionJob, Invoice, InvoiceItem
from app.regions import SAUDI_REGIONS

PRICE_LOOKBACK_DAYS = 365
PRICE_MIN_INVOICES = 3
PRICE_MIN_INCREASE = Decimal("0.20")
DUPLICATE_THRESHOLD = Decimal("0.85")
DUPLICATE_CANDIDATE_LIMIT = 500
ELIGIBLE_PRICE_STATUSES = ("PROJECT_REVIEW", "FINANCE_REVIEW", "APPROVED")
REGIONAL_MIN_INVOICES = 3
REGIONAL_MIN_SUPPLIERS = 2
REGIONAL_MIN_REGIONS = 2
REGIONAL_MIN_CURRENT_REGION_INVOICES = 2
REGIONAL_MIN_INCREASE = Decimal("0.20")

ARABIC_TRANSLATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "ة": "ه",
        "ـ": "",
        **dict(zip("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")),
    }
)
TOKEN_PATTERN = re.compile(r"[a-z0-9\u0621-\u064a]+")
UNIT_ALIASES = {
    "قطعه": "piece",
    "قطع": "piece",
    "حبه": "piece",
    "piece": "piece",
    "pieces": "piece",
    "pc": "piece",
    "pcs": "piece",
    "كجم": "kg",
    "كيلوجرام": "kg",
    "كيلو": "kg",
    "kg": "kg",
    "جرام": "g",
    "جم": "g",
    "g": "g",
    "لتر": "l",
    "liter": "l",
    "litre": "l",
    "l": "l",
    "متر": "m",
    "meter": "m",
    "metre": "m",
    "m": "m",
    "صندوق": "box",
    "كرتون": "box",
    "box": "box",
}


def normalized_tokens(value):
    if value is None:
        return []
    normalized = unicodedata.normalize("NFKC", str(value)).translate(ARABIC_TRANSLATION).casefold()
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    normalized = re.sub(r"(?<=[a-z])[-_/](?=\d)", "", normalized)
    return TOKEN_PATTERN.findall(normalized)


def normalized_phrase(value):
    return " ".join(normalized_tokens(value))


def normalized_unit(value):
    phrase = normalized_phrase(value)
    return UNIT_ALIASES.get(phrase, phrase) or None


def text_similarity(left, right):
    left_tokens, right_tokens = normalized_tokens(left), normalized_tokens(right)
    if not left_tokens or not right_tokens:
        return None
    left_phrase, right_phrase = " ".join(left_tokens), " ".join(right_tokens)
    sequence = Decimal(str(SequenceMatcher(None, left_phrase, right_phrase).ratio()))
    union = set(left_tokens) | set(right_tokens)
    token_score = Decimal(len(set(left_tokens) & set(right_tokens))) / Decimal(len(union))
    return max(sequence, token_score)


def descriptions_are_comparable(left, right):
    left_phrase, right_phrase = normalized_phrase(left), normalized_phrase(right)
    if len(left_phrase) < 6 or len(right_phrase) < 6:
        return False
    left_numbers = [token for token in normalized_tokens(left) if token.isdigit()]
    right_numbers = [token for token in normalized_tokens(right) if token.isdigit()]
    if left_numbers != right_numbers:
        return False
    score = text_similarity(left, right)
    return score is not None and score >= Decimal("0.88")


def effective_unit_price(item):
    if not item.quantity or item.quantity <= 0:
        return None
    return ((item.gross_amount - item.discount_amount) / item.quantity).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def percentile(values, fraction):
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = Decimal(len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    remainder = index - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * remainder


def money4(value):
    return format(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), ".4f")


def percent(value):
    return format(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), ".1f")


def analysis_result(code, label, status, message, **details):
    return {
        "code": code,
        "label": label,
        "status": status,
        "message": message,
        "document_value": None,
        "calculated_value": None,
        "difference": None,
        "match_count": None,
        "source_count": None,
        "comparisons": [],
        **details,
    }


def price_history_check(db, invoice):
    current_items = list(
        db.scalars(
            select(InvoiceItem)
            .where(InvoiceItem.invoice_id == invoice.id)
            .order_by(InvoiceItem.position)
        )
    )
    if invoice.document_type != "INVOICE":
        return analysis_result(
            "HISTORICAL_PRICE_ANOMALY",
            "تحليل الأسعار التاريخية",
            "NOT_CHECKED",
            "تحليل سعر الوحدة مخصص للفواتير الأصلية حتى لا تشوه إشعارات التسوية خط الأساس.",
            price_findings=[],
            policy={
                "lookback_days": PRICE_LOOKBACK_DAYS,
                "minimum_invoices": PRICE_MIN_INVOICES,
                "minimum_increase_percent": "20.0",
            },
        )
    if not all((invoice.supplier_id, invoice.currency, invoice.invoice_date)) or not current_items:
        return analysis_result(
            "HISTORICAL_PRICE_ANOMALY",
            "تحليل الأسعار التاريخية",
            "NOT_CHECKED",
            "يلزم المورد والعملة والتاريخ وبند واحد على الأقل لتحليل الأسعار.",
            price_findings=[],
            policy={
                "lookback_days": PRICE_LOOKBACK_DAYS,
                "minimum_invoices": PRICE_MIN_INVOICES,
                "minimum_increase_percent": "20.0",
            },
        )

    start_date = invoice.invoice_date - timedelta(days=PRICE_LOOKBACK_DAYS)
    rows = db.execute(
        select(Invoice, InvoiceItem)
        .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
        .where(
            Invoice.company_id == invoice.company_id,
            Invoice.id != invoice.id,
            Invoice.supplier_id == invoice.supplier_id,
            Invoice.currency == invoice.currency,
            Invoice.document_type == "INVOICE",
            Invoice.status.in_(ELIGIBLE_PRICE_STATUSES),
            Invoice.invoice_date >= start_date,
            Invoice.invoice_date <= invoice.invoice_date,
            Invoice.created_at < invoice.created_at,
        )
        .order_by(Invoice.created_at.desc(), InvoiceItem.position)
    ).all()
    history = defaultdict(list)
    for candidate, item in rows:
        history[candidate.id].append(item)

    findings = []
    for item in current_items:
        current_price = effective_unit_price(item)
        samples = []
        for candidate_id, candidate_items in history.items():
            matches = [
                candidate
                for candidate in candidate_items
                if normalized_unit(candidate.unit) == normalized_unit(item.unit)
                and descriptions_are_comparable(item.description, candidate.description)
            ]
            if not matches:
                continue
            best = max(
                matches,
                key=lambda candidate: text_similarity(item.description, candidate.description),
            )
            candidate_price = effective_unit_price(best)
            if candidate_price is not None:
                samples.append((candidate_id, candidate_price))

        base = {
            "position": item.position,
            "description": item.description,
            "unit": item.unit,
            "current_unit_price": money4(current_price) if current_price is not None else None,
            "sample_count": len(samples),
            "source_invoice_count": len({candidate_id for candidate_id, _ in samples}),
            "lookback_days": PRICE_LOOKBACK_DAYS,
        }
        values = [value for _, value in samples]
        if current_price is None:
            findings.append(
                {
                    **base,
                    "status": "NOT_CHECKED",
                    "message": "تعذر حساب سعر الوحدة الفعلي لهذا البند.",
                    "median_unit_price": None,
                    "lower_quartile": None,
                    "upper_quartile": None,
                    "alert_threshold": None,
                    "difference_percent": None,
                    "confidence": None,
                }
            )
            continue
        if len(values) < PRICE_MIN_INVOICES:
            findings.append(
                {
                    **base,
                    "status": "NOT_CHECKED",
                    "message": (
                        f"العينة المتاحة {len(values)} من {PRICE_MIN_INVOICES} فواتير مطلوبة؛ "
                        "لا يصدر النظام حكمًا سعريًا بعينة أصغر."
                    ),
                    "median_unit_price": None,
                    "lower_quartile": None,
                    "upper_quartile": None,
                    "alert_threshold": None,
                    "difference_percent": None,
                    "confidence": None,
                }
            )
            continue
        baseline = median(values)
        q1 = percentile(values, Decimal("0.25"))
        q3 = percentile(values, Decimal("0.75"))
        if baseline <= 0:
            findings.append(
                {
                    **base,
                    "status": "NOT_CHECKED",
                    "message": "وسيط الأسعار التاريخية صفر؛ لا يمكن حساب نسبة ارتفاع موثوقة.",
                    "median_unit_price": money4(baseline),
                    "lower_quartile": money4(q1),
                    "upper_quartile": money4(q3),
                    "alert_threshold": None,
                    "difference_percent": None,
                    "confidence": None,
                }
            )
            continue
        iqr_limit = q3 + Decimal("1.5") * (q3 - q1)
        percentage_limit = baseline * (Decimal("1") + PRICE_MIN_INCREASE)
        alert_threshold = max(iqr_limit, percentage_limit)
        difference = ((current_price - baseline) / baseline) * Decimal("100")
        warning = current_price > alert_threshold
        confidence = "HIGH" if len(values) >= 6 else "MEDIUM"
        findings.append(
            {
                **base,
                "status": "WARNING" if warning else "PASS",
                "message": (
                    "سعر الوحدة الفعلي أعلى من الحد الإحصائي ويحتاج مراجعة."
                    if warning
                    else "سعر الوحدة الفعلي ضمن النطاق التاريخي المحسوب."
                ),
                "median_unit_price": money4(baseline),
                "lower_quartile": money4(q1),
                "upper_quartile": money4(q3),
                "alert_threshold": money4(alert_threshold),
                "difference_percent": percent(difference),
                "confidence": confidence,
            }
        )

    checked = [finding for finding in findings if finding["status"] != "NOT_CHECKED"]
    warnings = [finding for finding in findings if finding["status"] == "WARNING"]
    status = "WARNING" if warnings else "PASS" if checked else "NOT_CHECKED"
    message = (
        f"ظهر ارتفاع غير معتاد في {len(warnings)} بند وفق التاريخ القابل للمقارنة."
        if warnings
        else f"فُحص {len(checked)} بند ولم يظهر ارتفاع يتجاوز السياسة."
        if checked
        else "لا توجد ثلاثة فواتير سابقة قابلة للمقارنة لأي بند حتى الآن."
    )
    return analysis_result(
        "HISTORICAL_PRICE_ANOMALY",
        "تحليل الأسعار التاريخية",
        status,
        message,
        price_findings=findings,
        policy={
            "lookback_days": PRICE_LOOKBACK_DAYS,
            "minimum_invoices": PRICE_MIN_INVOICES,
            "minimum_increase_percent": "20.0",
            "baseline": "MEDIAN_AND_IQR",
            "price_basis": "AFTER_LINE_DISCOUNT_BEFORE_TAX",
        },
    )


def regional_price_check(db, invoice):
    current_items = list(
        db.scalars(
            select(InvoiceItem)
            .where(InvoiceItem.invoice_id == invoice.id)
            .order_by(InvoiceItem.position)
        )
    )
    policy = {
        "lookback_days": PRICE_LOOKBACK_DAYS,
        "minimum_invoices": REGIONAL_MIN_INVOICES,
        "minimum_suppliers": REGIONAL_MIN_SUPPLIERS,
        "minimum_regions": REGIONAL_MIN_REGIONS,
        "minimum_current_region_invoices": REGIONAL_MIN_CURRENT_REGION_INVOICES,
        "minimum_increase_percent": "20.0",
        "price_basis": "AFTER_LINE_DISCOUNT_BEFORE_TAX",
        "benchmark_scope": "INTERNAL_SUBMITTED_INVOICES",
    }
    if invoice.document_type != "INVOICE":
        return analysis_result(
            "REGIONAL_SUPPLIER_PRICE",
            "المقارنة الإقليمية لأسعار الموردين",
            "NOT_CHECKED",
            "المقارنة الإقليمية مخصصة للفواتير الأصلية حتى لا تدخل التسويات في خط الأسعار.",
            regional_findings=[],
            policy=policy,
        )
    current_region = (invoice.supplier_snapshot or {}).get("region_code")
    if not all((invoice.supplier_id, current_region, invoice.currency, invoice.invoice_date)):
        return analysis_result(
            "REGIONAL_SUPPLIER_PRICE",
            "المقارنة الإقليمية لأسعار الموردين",
            "NOT_CHECKED",
            "يلزم المورد ومنطقته والعملة والتاريخ لإجراء مقارنة إقليمية.",
            regional_findings=[],
            policy=policy,
        )
    if not current_items:
        return analysis_result(
            "REGIONAL_SUPPLIER_PRICE",
            "المقارنة الإقليمية لأسعار الموردين",
            "NOT_CHECKED",
            "أضف بندًا واحدًا على الأقل لإجراء المقارنة الإقليمية.",
            regional_findings=[],
            policy=policy,
        )

    start_date = invoice.invoice_date - timedelta(days=PRICE_LOOKBACK_DAYS)
    rows = db.execute(
        select(Invoice, InvoiceItem)
        .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
        .where(
            Invoice.company_id == invoice.company_id,
            Invoice.id != invoice.id,
            Invoice.currency == invoice.currency,
            Invoice.document_type == "INVOICE",
            Invoice.status.in_(ELIGIBLE_PRICE_STATUSES),
            Invoice.invoice_date >= start_date,
            Invoice.invoice_date <= invoice.invoice_date,
            Invoice.created_at < invoice.created_at,
        )
        .order_by(Invoice.created_at.desc(), InvoiceItem.position)
    ).all()
    history = defaultdict(list)
    invoices = {}
    for candidate, item in rows:
        region_code = (candidate.supplier_snapshot or {}).get("region_code")
        if not region_code:
            continue
        history[candidate.id].append(item)
        invoices[candidate.id] = candidate

    findings = []
    for item in current_items:
        current_price = effective_unit_price(item)
        samples = []
        for candidate_id, candidate_items in history.items():
            matches = [
                candidate
                for candidate in candidate_items
                if normalized_unit(candidate.unit) == normalized_unit(item.unit)
                and descriptions_are_comparable(item.description, candidate.description)
            ]
            if not matches:
                continue
            best = max(
                matches,
                key=lambda candidate: text_similarity(item.description, candidate.description),
            )
            candidate_price = effective_unit_price(best)
            if candidate_price is None:
                continue
            candidate_invoice = invoices[candidate_id]
            samples.append(
                {
                    "invoice_id": candidate_id,
                    "supplier_id": candidate_invoice.supplier_id,
                    "region_code": candidate_invoice.supplier_snapshot["region_code"],
                    "invoice_date": candidate_invoice.invoice_date,
                    "unit_price": candidate_price,
                }
            )

        grouped = defaultdict(list)
        for sample in samples:
            grouped[sample["region_code"]].append(sample)
        regional_rows = []
        for region_code, region_samples in grouped.items():
            regional_rows.append(
                {
                    "region_code": region_code,
                    "region_name": SAUDI_REGIONS.get(region_code, region_code),
                    "median_unit_price": money4(
                        median(sample["unit_price"] for sample in region_samples)
                    ),
                    "invoice_count": len(region_samples),
                    "supplier_count": len({sample["supplier_id"] for sample in region_samples}),
                    "date_from": min(
                        sample["invoice_date"] for sample in region_samples
                    ).isoformat(),
                    "date_to": max(sample["invoice_date"] for sample in region_samples).isoformat(),
                }
            )
        regional_rows.sort(
            key=lambda row: (
                row["region_code"] != current_region,
                Decimal(row["median_unit_price"]),
                row["region_code"],
            )
        )
        supplier_count = len({sample["supplier_id"] for sample in samples})
        base = {
            "position": item.position,
            "description": item.description,
            "unit": item.unit,
            "current_region_code": current_region,
            "current_region_name": SAUDI_REGIONS[current_region],
            "current_unit_price": money4(current_price) if current_price is not None else None,
            "sample_count": len(samples),
            "supplier_count": supplier_count,
            "region_count": len(grouped),
            "lookback_days": PRICE_LOOKBACK_DAYS,
            "region_comparisons": regional_rows,
        }
        if current_price is None:
            findings.append(
                {
                    **base,
                    "status": "NOT_CHECKED",
                    "message": "تعذر حساب سعر الوحدة الفعلي لهذا البند.",
                    "current_region_median": None,
                    "difference_percent": None,
                    "potential_saving": None,
                    "confidence": None,
                }
            )
            continue
        missing = []
        if len(samples) < REGIONAL_MIN_INVOICES:
            missing.append(f"{REGIONAL_MIN_INVOICES} فواتير")
        if supplier_count < REGIONAL_MIN_SUPPLIERS:
            missing.append(f"{REGIONAL_MIN_SUPPLIERS} موردين")
        if len(grouped) < REGIONAL_MIN_REGIONS:
            missing.append(f"{REGIONAL_MIN_REGIONS} منطقتين")
        current_region_samples = grouped.get(current_region, [])
        if len(current_region_samples) < REGIONAL_MIN_CURRENT_REGION_INVOICES:
            missing.append(f"فاتورتين من {SAUDI_REGIONS[current_region]}")
        if missing:
            findings.append(
                {
                    **base,
                    "status": "NOT_CHECKED",
                    "message": "العينة غير كافية؛ يلزم " + "، و".join(missing) + ".",
                    "current_region_median": None,
                    "difference_percent": None,
                    "potential_saving": None,
                    "confidence": None,
                }
            )
            continue

        baseline = median(sample["unit_price"] for sample in current_region_samples)
        if baseline <= 0:
            findings.append(
                {
                    **base,
                    "status": "NOT_CHECKED",
                    "message": "وسيط المنطقة الحالية صفر؛ لا يمكن حساب نسبة مقارنة موثوقة.",
                    "current_region_median": money4(baseline),
                    "difference_percent": None,
                    "potential_saving": None,
                    "confidence": None,
                }
            )
            continue
        difference = ((current_price - baseline) / baseline) * Decimal("100")
        warning = difference >= REGIONAL_MIN_INCREASE * Decimal("100")
        saving = max(current_price - baseline, Decimal("0")) * item.quantity
        confidence = (
            "HIGH" if len(samples) >= 6 and supplier_count >= 3 and len(grouped) >= 3 else "MEDIUM"
        )
        findings.append(
            {
                **base,
                "status": "WARNING" if warning else "PASS",
                "message": (
                    f"سعر الوحدة أعلى من وسيط {SAUDI_REGIONS[current_region]} بنسبة "
                    f"{percent(difference)}% ويحتاج مراجعة."
                    if warning
                    else f"سعر الوحدة ضمن هامش 20% من وسيط {SAUDI_REGIONS[current_region]}."
                ),
                "current_region_median": money4(baseline),
                "difference_percent": percent(difference),
                "potential_saving": money4(saving),
                "confidence": confidence,
            }
        )

    checked = [finding for finding in findings if finding["status"] != "NOT_CHECKED"]
    warnings = [finding for finding in findings if finding["status"] == "WARNING"]
    status = "WARNING" if warnings else "PASS" if checked else "NOT_CHECKED"
    message = (
        f"ظهر فرق إقليمي يحتاج مراجعة في {len(warnings)} بند."
        if warnings
        else f"اكتملت المقارنة الإقليمية لعدد {len(checked)} بند دون تجاوز السياسة."
        if checked
        else "لا تتوفر عينة داخلية كافية ومتنوعة إقليميًا لإصدار مقارنة الآن."
    )
    return analysis_result(
        "REGIONAL_SUPPLIER_PRICE",
        "المقارنة الإقليمية لأسعار الموردين",
        status,
        message,
        regional_findings=findings,
        policy=policy,
        privacy_note=(
            "تعرض النتيجة وسائط مجمعة حسب المنطقة دون أرقام الفواتير أو أسماء الموردين الآخرين."
        ),
    )


def decimal_similarity(left, right, tolerance):
    if left is None or right is None:
        return None
    left, right = Decimal(left), Decimal(right)
    scale = max(abs(left), abs(right), Decimal("0.01"))
    relative = abs(left - right) / scale
    return max(Decimal("0"), Decimal("1") - relative / tolerance)


def date_similarity(left, right):
    if left is None or right is None:
        return None
    days = abs((left - right).days)
    return max(Decimal("0"), Decimal("1") - Decimal(days) / Decimal("30"))


def line_similarity(left_items, right_items):
    if not left_items or not right_items:
        return None

    def combined_signature(items):
        signatures = sorted(
            f"{normalized_phrase(item.description)} {normalized_unit(item.unit) or ''} "
            f"{item.quantity} {effective_unit_price(item)}"
            for item in items
        )
        return " | ".join(signatures)[:10_000]

    content_score = Decimal(
        str(
            SequenceMatcher(
                None, combined_signature(left_items), combined_signature(right_items)
            ).ratio()
        )
    )
    size_penalty = Decimal(min(len(left_items), len(right_items))) / Decimal(
        max(len(left_items), len(right_items))
    )
    return content_score * size_penalty


def extraction_text(result):
    if not isinstance(result, dict):
        return None
    values = []

    def collect(value):
        if isinstance(value, dict):
            if "value" in value and isinstance(value["value"], (str, int, float)):
                values.append(str(value["value"]))
            else:
                for child in value.values():
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for key in ("fields", "items", "structured_sources"):
        collect(result.get(key))
    phrase = normalized_phrase(" ".join(values))
    return phrase[:10_000] or None


def signal(code, label, score, weight, summary):
    return {
        "code": code,
        "label": label,
        "available": score is not None,
        "score_percent": (
            int((score * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if score is not None
            else None
        ),
        "weight_percent": weight,
        "summary": summary,
    }


def score_summary(label, score):
    if score is None:
        return "لا تتوفر بيانات كافية لهذه الإشارة."
    strength = (
        "قوي" if score >= Decimal("0.90") else "متوسط" if score >= Decimal("0.70") else "ضعيف"
    )
    return f"تقارب {label} {strength}."


def approximate_duplicate_check(db, invoice):
    candidates = list(
        db.scalars(
            select(Invoice)
            .where(
                Invoice.company_id == invoice.company_id,
                Invoice.id != invoice.id,
                Invoice.document_type == invoice.document_type,
            )
            .order_by(Invoice.created_at.desc(), Invoice.id)
            .limit(DUPLICATE_CANDIDATE_LIMIT)
        )
    )
    invoice_ids = [invoice.id, *(candidate.id for candidate in candidates)]
    items_by_invoice = defaultdict(list)
    for item in db.scalars(
        select(InvoiceItem)
        .where(InvoiceItem.invoice_id.in_(invoice_ids))
        .order_by(InvoiceItem.invoice_id, InvoiceItem.position)
    ):
        items_by_invoice[item.invoice_id].append(item)

    extraction_by_invoice = {}
    for job in db.scalars(
        select(ExtractionJob)
        .where(
            ExtractionJob.invoice_id.in_(invoice_ids),
            ExtractionJob.status == "SUCCEEDED",
            ExtractionJob.result.is_not(None),
        )
        .order_by(ExtractionJob.finished_at.desc().nullslast(), ExtractionJob.id.desc())
    ):
        extraction_by_invoice.setdefault(job.invoice_id, extraction_text(job.result))

    current_supplier = (invoice.supplier_snapshot or {}).get("name")
    current_number = normalized_phrase(invoice.invoice_number)
    current_extraction = extraction_by_invoice.get(invoice.id)
    current_ready = (
        sum(
            (
                bool(invoice.supplier_id or current_supplier),
                bool(current_number),
                bool(invoice.invoice_date),
                bool(invoice.currency and invoice.grand_total is not None),
                bool(items_by_invoice[invoice.id]),
                bool(current_extraction),
            )
        )
        >= 3
        and bool(invoice.supplier_id or current_supplier)
        and bool(current_number or items_by_invoice[invoice.id] or current_extraction)
    )
    scored = []
    weights = {
        "SUPPLIER": 20,
        "INVOICE_NUMBER": 20,
        "DATE": 10,
        "TOTAL": 20,
        "LINE_CONTENT": 20,
        "DOCUMENT_CONTENT": 10,
    }
    for candidate in candidates:
        candidate_supplier = (candidate.supplier_snapshot or {}).get("name")
        supplier_score = (
            Decimal("1")
            if invoice.supplier_id is not None and invoice.supplier_id == candidate.supplier_id
            else text_similarity(current_supplier, candidate_supplier)
        )
        number_score = text_similarity(current_number, normalized_phrase(candidate.invoice_number))
        total_score = (
            decimal_similarity(invoice.grand_total, candidate.grand_total, Decimal("0.10"))
            if invoice.currency is not None and invoice.currency == candidate.currency
            else None
        )
        lines_score = line_similarity(items_by_invoice[invoice.id], items_by_invoice[candidate.id])
        document_score = text_similarity(
            current_extraction, extraction_by_invoice.get(candidate.id)
        )
        values = {
            "SUPPLIER": supplier_score,
            "INVOICE_NUMBER": number_score,
            "DATE": date_similarity(invoice.invoice_date, candidate.invoice_date),
            "TOTAL": total_score,
            "LINE_CONTENT": lines_score,
            "DOCUMENT_CONTENT": document_score,
        }
        available = {code: score for code, score in values.items() if score is not None}
        available_weight = sum(weights[code] for code in available)
        if len(available) < 3 or available_weight < 50:
            continue
        weighted_score = sum(available[code] * weights[code] for code in available) / Decimal(
            available_weight
        )
        anchored = (
            supplier_score is not None
            and supplier_score >= Decimal("0.80")
            and any(
                values[code] is not None and values[code] >= Decimal("0.80")
                for code in ("INVOICE_NUMBER", "LINE_CONTENT", "DOCUMENT_CONTENT")
            )
        )
        factors = [
            signal(
                "SUPPLIER",
                "المورد",
                supplier_score,
                weights["SUPPLIER"],
                score_summary("المورد", supplier_score),
            ),
            signal(
                "INVOICE_NUMBER",
                "رقم الفاتورة",
                number_score,
                weights["INVOICE_NUMBER"],
                score_summary("رقم الفاتورة", number_score),
            ),
            signal(
                "DATE",
                "التاريخ",
                values["DATE"],
                weights["DATE"],
                score_summary("التاريخ", values["DATE"]),
            ),
            signal(
                "TOTAL",
                "الإجمالي والعملة",
                total_score,
                weights["TOTAL"],
                score_summary("الإجمالي", total_score),
            ),
            signal(
                "LINE_CONTENT",
                "محتوى البنود",
                lines_score,
                weights["LINE_CONTENT"],
                score_summary("البنود", lines_score),
            ),
            signal(
                "DOCUMENT_CONTENT",
                "المحتوى المستخرج",
                document_score,
                weights["DOCUMENT_CONTENT"],
                score_summary("المحتوى المستخرج", document_score),
            ),
        ]
        scored.append(
            {
                "score": weighted_score,
                "is_match": anchored and weighted_score >= DUPLICATE_THRESHOLD,
                "factors": factors,
            }
        )

    matches = [candidate for candidate in scored if candidate["is_match"]]
    best = max(scored, key=lambda candidate: candidate["score"], default=None)
    best_match = max(matches, key=lambda candidate: candidate["score"], default=None)
    evidence = best_match or best
    maximum = (
        int((evidence["score"] * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if evidence
        else None
    )
    status = "WARNING" if matches else "PASS" if current_ready else "NOT_CHECKED"
    message = (
        f"ظهرت {len(matches)} فاتورة تتجاوز حد التشابه؛ أعلى درجة {maximum}%."
        if matches
        else f"لم تتجاوز أي فاتورة حد التشابه 85%؛ أعلى درجة {maximum}%."
        if scored
        else "لم تظهر فاتورة أخرى قابلة للمقارنة داخل الشركة."
        if current_ready
        else "يلزم المورد وثلاث إشارات على الأقل مثل الرقم والتاريخ والإجمالي أو البنود."
    )
    return analysis_result(
        "APPROXIMATE_DUPLICATE",
        "التكرار التقريبي وتشابه المحتوى",
        status,
        message,
        match_count=len(matches),
        comparison_count=len(scored),
        max_similarity_percent=maximum,
        similarity_threshold_percent=85,
        similarity_signals=evidence["factors"] if evidence else [],
        privacy_note="تعرض النتيجة درجات وأسبابًا مجمعة دون بيانات الفواتير الأخرى.",
    )
