import unicodedata
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.models import (
    ApprovalLimit,
    Attachment,
    ExtractionJob,
    GoodsReceipt,
    GoodsReceiptItem,
    Invoice,
    InvoiceItem,
    ProjectBudget,
    ProjectMember,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    User,
)
from app.services.financial_intelligence import (
    approximate_duplicate_check,
    price_history_check,
    regional_price_check,
)


def normalize_invoice_number(value: str) -> str:
    digits = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    normalized = unicodedata.normalize("NFKC", value).translate(digits).casefold()
    return "".join(character for character in normalized if character.isalnum())


def check_result(
    code,
    label,
    status,
    message,
    *,
    document_value=None,
    calculated_value=None,
    difference=None,
    match_count=None,
    source_count=None,
    comparisons=None,
):
    return {
        "code": code,
        "label": label,
        "status": status,
        "message": message,
        "document_value": document_value,
        "calculated_value": calculated_value,
        "difference": difference,
        "match_count": match_count,
        "source_count": source_count,
        "comparisons": comparisons or [],
    }


def total_check(invoice, code, label, document_field, calculated_value):
    document_value = getattr(invoice, document_field)
    if document_value is None:
        return check_result(
            code,
            label,
            "NOT_CHECKED",
            "لم يُدخل المبلغ الظاهر على أصل الفاتورة لهذا الحقل.",
            calculated_value=(
                format(calculated_value, ".2f") if calculated_value is not None else None
            ),
        )
    if calculated_value is None:
        return check_result(
            code,
            label,
            "NOT_CHECKED",
            "لا توجد بنود محسوبة يمكن مقارنتها بالمبلغ الظاهر على الأصل.",
            document_value=format(document_value, ".2f"),
        )
    difference = document_value - calculated_value
    if difference == Decimal("0.00"):
        return check_result(
            code,
            label,
            "PASS",
            "المبلغ الظاهر على الأصل يطابق المبلغ المحسوب من البنود.",
            document_value=format(document_value, ".2f"),
            calculated_value=format(calculated_value, ".2f"),
            difference="0.00",
        )
    return check_result(
        code,
        label,
        "WARNING",
        "يوجد فرق بين المبلغ الظاهر على الأصل والمبلغ المحسوب من البنود.",
        document_value=format(document_value, ".2f"),
        calculated_value=format(calculated_value, ".2f"),
        difference=format(difference, ".2f"),
    )


def exact_file_duplicate_check(db, invoice):
    attachment = db.scalar(select(Attachment).where(Attachment.invoice_id == invoice.id))
    matches = 0
    if attachment:
        matches = (
            db.scalar(
                select(func.count())
                .select_from(Attachment)
                .join(Invoice, Invoice.id == Attachment.invoice_id)
                .where(
                    Invoice.company_id == invoice.company_id,
                    Invoice.id != invoice.id,
                    Attachment.sha256 == attachment.sha256,
                )
            )
            or 0
        )
    return check_result(
        "EXACT_FILE_DUPLICATE",
        "تطابق الملف الأصلي",
        "WARNING" if matches else "PASS",
        (
            "توجد فاتورة أخرى في الشركة تحمل الملف نفسه تمامًا؛ راجع سبب إعادة الرفع."
            if matches
            else "لم يظهر ملف آخر مطابق تمامًا داخل الشركة."
        ),
        match_count=matches,
    )


def potential_duplicate_check(db, invoice):
    ready = all(
        value is not None
        for value in (
            invoice.supplier_id,
            invoice.invoice_number,
            invoice.invoice_date,
            invoice.currency,
            invoice.grand_total,
        )
    )
    if not ready:
        return check_result(
            "POTENTIAL_DUPLICATE",
            "تكرار بيانات الفاتورة",
            "NOT_CHECKED",
            "يلزم المورد ورقم الفاتورة والتاريخ والعملة والإجمالي لإجراء المقارنة.",
        )
    number_key = normalize_invoice_number(invoice.invoice_number)
    if not number_key:
        return check_result(
            "POTENTIAL_DUPLICATE",
            "تكرار بيانات الفاتورة",
            "NOT_CHECKED",
            "رقم الفاتورة لا يحتوي أحرفًا أو أرقامًا قابلة للمقارنة.",
        )
    candidates = db.scalars(
        select(Invoice).where(
            Invoice.company_id == invoice.company_id,
            Invoice.id != invoice.id,
            Invoice.document_type == invoice.document_type,
            Invoice.supplier_id == invoice.supplier_id,
            Invoice.invoice_date == invoice.invoice_date,
            Invoice.currency == invoice.currency,
            Invoice.grand_total == invoice.grand_total,
            Invoice.invoice_number.is_not(None),
        )
    )
    matches = sum(
        1
        for candidate in candidates
        if normalize_invoice_number(candidate.invoice_number) == number_key
    )
    return check_result(
        "POTENTIAL_DUPLICATE",
        "تكرار بيانات الفاتورة",
        "WARNING" if matches else "PASS",
        (
            "توجد فاتورة أخرى ببيانات المورد والرقم والتاريخ والعملة والإجمالي نفسها."
            if matches
            else "لم تظهر فاتورة أخرى بالهوية المالية نفسها داخل الشركة."
        ),
        match_count=matches,
    )


def structured_sources(db, invoice):
    attachment = db.scalar(select(Attachment).where(Attachment.invoice_id == invoice.id))
    if attachment is None:
        return []
    job = db.scalar(
        select(ExtractionJob)
        .where(
            ExtractionJob.invoice_id == invoice.id,
            ExtractionJob.attachment_id == attachment.id,
            ExtractionJob.source_sha256 == attachment.sha256,
            ExtractionJob.status == "SUCCEEDED",
            ExtractionJob.result.is_not(None),
        )
        .order_by(ExtractionJob.finished_at.desc(), ExtractionJob.id.desc())
        .limit(1)
    )
    result = job.result if job and isinstance(job.result, dict) else {}
    sources = result.get("structured_sources", [])
    return sources if isinstance(sources, list) else []


def normalized_text(value):
    if value is None:
        return None
    digits = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    normalized = unicodedata.normalize("NFKC", str(value)).translate(digits).casefold()
    return "".join(character for character in normalized if character.isalnum()) or None


def normalized_money(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number >= 0 else None
    except Exception:
        return None


def current_values(invoice):
    supplier = invoice.supplier_snapshot or {}
    net = (
        invoice.subtotal - invoice.discount_total
        if invoice.subtotal is not None and invoice.discount_total is not None
        else None
    )
    return {
        "document_type": {
            "INVOICE": "Invoice",
            "CREDIT_NOTE": "CreditNote",
            "DEBIT_NOTE": "DebitNote",
        }.get(invoice.document_type),
        "supplier_name": supplier.get("name"),
        "supplier_tax_number": supplier.get("tax_number"),
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "currency": invoice.currency,
        "subtotal": invoice.document_subtotal if invoice.document_subtotal is not None else net,
        "tax_total": (
            invoice.document_tax_total
            if invoice.document_tax_total is not None
            else invoice.tax_total
        ),
        "grand_total": (
            invoice.document_grand_total
            if invoice.document_grand_total is not None
            else invoice.grand_total
        ),
    }


SOURCE_FIELDS = {
    "QR": (
        ("supplier_name", "اسم المورد", "text"),
        ("supplier_tax_number", "الرقم الضريبي للمورد", "text"),
        ("invoice_date", "تاريخ الفاتورة", "text"),
        ("tax_total", "إجمالي الضريبة", "money"),
        ("grand_total", "الإجمالي شامل الضريبة", "money"),
    ),
    "XML": (
        ("document_type", "نوع المستند", "text"),
        ("supplier_name", "اسم المورد", "text"),
        ("supplier_tax_number", "الرقم الضريبي للمورد", "text"),
        ("invoice_number", "رقم الفاتورة", "invoice_number"),
        ("invoice_date", "تاريخ الفاتورة", "text"),
        ("currency", "العملة", "text"),
        ("subtotal", "الصافي قبل الضريبة", "money"),
        ("tax_total", "إجمالي الضريبة", "money"),
        ("grand_total", "الإجمالي شامل الضريبة", "money"),
    ),
}


def comparable(left, right, kind):
    if kind == "money":
        left, right = normalized_money(left), normalized_money(right)
    elif kind == "invoice_number":
        left = normalize_invoice_number(str(left)) if left is not None else None
        right = normalize_invoice_number(str(right)) if right is not None else None
    else:
        left, right = normalized_text(left), normalized_text(right)
    return left is not None and right is not None and left == right


def source_check(db, invoice, source_type, code, label):
    sources = [
        source
        for source in structured_sources(db, invoice)
        if isinstance(source, dict) and source.get("type") == source_type
    ]
    if not sources:
        noun = "QR قابل للقراءة" if source_type == "QR" else "UBL XML صالح"
        return check_result(
            code,
            label,
            "NOT_CHECKED",
            f"لم تتوفر نتيجة {noun} من قراءة المستند الحالية.",
            source_count=0,
        )
    confirmed = current_values(invoice)
    comparisons = []
    seen = set()
    for source in sources:
        fields = source.get("fields", {}) if isinstance(source.get("fields"), dict) else {}
        for field_name, field_label, kind in SOURCE_FIELDS[source_type]:
            if field_name == "document_type":
                source_value = source.get("document_type")
            else:
                value = fields.get(field_name)
                source_value = value.get("value") if isinstance(value, dict) else None
            if source_value is None:
                continue
            confirmed_value = confirmed.get(field_name)
            key = (field_name, str(source_value), str(confirmed_value))
            if key in seen:
                continue
            seen.add(key)
            if confirmed_value is None:
                status = "NOT_COMPARABLE"
            else:
                status = "MATCH" if comparable(source_value, confirmed_value, kind) else "MISMATCH"
            comparisons.append(
                {
                    "field": field_name,
                    "label": field_label,
                    "source_value": str(source_value),
                    "invoice_value": str(confirmed_value) if confirmed_value is not None else None,
                    "status": status,
                }
            )
    compared = [value for value in comparisons if value["status"] != "NOT_COMPARABLE"]
    mismatches = [value for value in comparisons if value["status"] == "MISMATCH"]
    if mismatches:
        status = "WARNING"
        message = f"اختلفت {len(mismatches)} قيمة منظمة عن بيانات الفاتورة المؤكدة."
    elif compared:
        status = "PASS"
        message = f"تطابقت القيم المنظمة القابلة للمقارنة وعددها {len(compared)}."
    else:
        status = "NOT_CHECKED"
        message = "وُجد المصدر المنظم، لكن بيانات الفاتورة المؤكدة لا تكفي للمقارنة."
    return check_result(
        code,
        label,
        status,
        message,
        source_count=len(sources),
        comparisons=comparisons,
    )


def billed_quantities(db, invoice, purchase_order_id):
    previous = dict(
        db.execute(
            select(InvoiceItem.purchase_order_item_id, func.sum(InvoiceItem.quantity))
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .where(
                Invoice.id != invoice.id,
                Invoice.purchase_order_id == purchase_order_id,
                Invoice.status.in_(("PROJECT_REVIEW", "FINANCE_REVIEW", "APPROVED")),
                InvoiceItem.purchase_order_item_id.is_not(None),
            )
            .group_by(InvoiceItem.purchase_order_item_id)
        ).all()
    )
    current = dict(
        db.execute(
            select(InvoiceItem.purchase_order_item_id, func.sum(InvoiceItem.quantity))
            .where(
                InvoiceItem.invoice_id == invoice.id,
                InvoiceItem.purchase_order_item_id.is_not(None),
            )
            .group_by(InvoiceItem.purchase_order_item_id)
        ).all()
    )
    return {
        item_id: previous.get(item_id, Decimal("0")) + current.get(item_id, Decimal("0"))
        for item_id in set(previous) | set(current)
    }


def purchase_order_checks(db, invoice):
    labels = (
        ("PURCHASE_ORDER_HEADER", "مطابقة بيانات أمر الشراء"),
        ("PURCHASE_ORDER_LINES", "مطابقة بنود أمر الشراء"),
        ("GOODS_RECEIPT_MATCH", "مطابقة الاستلام"),
    )
    if invoice.purchase_order_id is None:
        return [
            check_result(
                code,
                label,
                "NOT_CHECKED",
                "لم يُربط أمر شراء بهذه الفاتورة؛ الربط اختياري في النسخة الحالية.",
            )
            for code, label in labels
        ]
    purchase_order = db.get(PurchaseOrder, invoice.purchase_order_id)
    if (
        purchase_order is None
        or purchase_order.company_id != invoice.company_id
        or purchase_order.project_id != invoice.project_id
    ):
        return [
            check_result(
                code,
                label,
                "WARNING",
                "ارتباط أمر الشراء غير صالح للشركة أو المشروع ويحتاج مراجعة.",
            )
            for code, label in labels
        ]

    supplier = db.get(Supplier, purchase_order.supplier_id)
    invoice_supplier = invoice.supplier_snapshot or {}
    header_comparisons = [
        {
            "field": "purchase_order_supplier",
            "label": "المورد",
            "source_value": supplier.name,
            "invoice_value": invoice_supplier.get("name"),
            "status": (
                "NOT_COMPARABLE"
                if invoice.supplier_id is None
                else "MATCH"
                if invoice.supplier_id == purchase_order.supplier_id
                else "MISMATCH"
            ),
        },
        {
            "field": "purchase_order_currency",
            "label": "العملة",
            "source_value": purchase_order.currency,
            "invoice_value": invoice.currency,
            "status": (
                "NOT_COMPARABLE"
                if invoice.currency is None
                else "MATCH"
                if invoice.currency == purchase_order.currency
                else "MISMATCH"
            ),
        },
    ]
    header_mismatches = [item for item in header_comparisons if item["status"] == "MISMATCH"]
    header_missing = [item for item in header_comparisons if item["status"] == "NOT_COMPARABLE"]
    header = check_result(
        "PURCHASE_ORDER_HEADER",
        "مطابقة بيانات أمر الشراء",
        "WARNING" if header_mismatches else "NOT_CHECKED" if header_missing else "PASS",
        (
            f"اختلفت {len(header_mismatches)} قيمة عن أمر الشراء {purchase_order.number}."
            if header_mismatches
            else "أكمل مورد الفاتورة وعملتها لمقارنتهما بأمر الشراء."
            if header_missing
            else f"المورد والعملة متطابقان مع أمر الشراء {purchase_order.number}."
        ),
        comparisons=header_comparisons,
    )

    order_items = {
        item.id: item
        for item in db.scalars(
            select(PurchaseOrderItem).where(
                PurchaseOrderItem.purchase_order_id == purchase_order.id
            )
        )
    }
    invoice_items = list(
        db.scalars(
            select(InvoiceItem)
            .where(InvoiceItem.invoice_id == invoice.id)
            .order_by(InvoiceItem.position)
        )
    )
    billed = billed_quantities(db, invoice, purchase_order.id)
    line_comparisons = []
    for item in invoice_items:
        order_item = order_items.get(item.purchase_order_item_id)
        if order_item is None:
            line_comparisons.append(
                {
                    "field": "purchase_order_item",
                    "label": f"ربط بند الفاتورة {item.position}",
                    "source_value": "غير مربوط",
                    "invoice_value": item.description,
                    "status": "MISMATCH",
                }
            )
            continue
        for field_name, field_label, source_value, invoice_value in (
            (
                "purchase_order_unit_price",
                f"سعر بند الفاتورة {item.position}",
                order_item.unit_price,
                item.unit_price,
            ),
            (
                "purchase_order_tax_rate",
                f"ضريبة بند الفاتورة {item.position}",
                order_item.tax_rate,
                item.tax_rate,
            ),
        ):
            line_comparisons.append(
                {
                    "field": field_name,
                    "label": field_label,
                    "source_value": format(source_value, ".4f"),
                    "invoice_value": format(invoice_value, ".4f"),
                    "status": "MATCH" if source_value == invoice_value else "MISMATCH",
                }
            )
        line_comparisons.append(
            {
                "field": "purchase_order_unit",
                "label": f"وحدة بند الفاتورة {item.position}",
                "source_value": order_item.unit or "غير محددة",
                "invoice_value": item.unit,
                "status": (
                    "NOT_COMPARABLE"
                    if not order_item.unit or not item.unit
                    else "MATCH"
                    if normalized_text(order_item.unit) == normalized_text(item.unit)
                    else "MISMATCH"
                ),
            }
        )
    for item_id, quantity in billed.items():
        order_item = order_items.get(item_id)
        if order_item:
            line_comparisons.append(
                {
                    "field": "purchase_order_quantity",
                    "label": f"الكمية المفوترة لبند الأمر {order_item.position}",
                    "source_value": format(order_item.ordered_quantity, ".4f"),
                    "invoice_value": format(quantity, ".4f"),
                    "status": "MATCH" if quantity <= order_item.ordered_quantity else "MISMATCH",
                }
            )
    line_mismatches = [item for item in line_comparisons if item["status"] == "MISMATCH"]
    lines = check_result(
        "PURCHASE_ORDER_LINES",
        "مطابقة بنود أمر الشراء",
        "NOT_CHECKED" if not invoice_items else "WARNING" if line_mismatches else "PASS",
        (
            "لم تُدخل بنود الفاتورة بعد."
            if not invoice_items
            else f"تحتاج {len(line_mismatches)} مقارنة في البنود إلى مراجعة."
            if line_mismatches
            else "أسعار البنود وضريبتها وكمياتها ضمن أمر الشراء."
        ),
        comparisons=line_comparisons,
    )

    receipt_count = db.scalar(
        select(func.count())
        .select_from(GoodsReceipt)
        .where(GoodsReceipt.purchase_order_id == purchase_order.id)
    )
    received = dict(
        db.execute(
            select(
                GoodsReceiptItem.purchase_order_item_id,
                func.sum(GoodsReceiptItem.received_quantity),
            )
            .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptItem.goods_receipt_id)
            .where(GoodsReceipt.purchase_order_id == purchase_order.id)
            .group_by(GoodsReceiptItem.purchase_order_item_id)
        ).all()
    )
    receipt_comparisons = []
    for item_id, quantity in billed.items():
        order_item = order_items.get(item_id)
        if order_item:
            received_quantity = received.get(item_id, Decimal("0"))
            receipt_comparisons.append(
                {
                    "field": "received_quantity",
                    "label": f"استلام بند الأمر {order_item.position}",
                    "source_value": format(received_quantity, ".4f"),
                    "invoice_value": format(quantity, ".4f"),
                    "status": "MATCH" if received_quantity >= quantity else "MISMATCH",
                }
            )
    receipt_mismatches = [item for item in receipt_comparisons if item["status"] == "MISMATCH"]
    if not billed:
        receipt_status = "NOT_CHECKED"
        receipt_message = "اربط بنود الفاتورة بأمر الشراء حتى يمكن مقارنة الاستلام."
    elif receipt_mismatches:
        receipt_status = "WARNING"
        receipt_message = f"الاستلام لا يغطي {len(receipt_mismatches)} كمية مفوترة."
    else:
        receipt_status = "PASS"
        receipt_message = f"الكميات المفوترة مغطاة بمحاضر الاستلام وعددها {receipt_count}."
    receipt = check_result(
        "GOODS_RECEIPT_MATCH",
        "مطابقة الاستلام",
        receipt_status,
        receipt_message,
        match_count=receipt_count,
        comparisons=receipt_comparisons,
    )
    return [header, lines, receipt]


def supplier_verification_check(db, invoice):
    if not invoice.supplier_id:
        return check_result(
            "SUPPLIER_VERIFICATION",
            "التحقق الداخلي من المورد",
            "NOT_CHECKED",
            "اختر المورد حتى تظهر نتيجة التحقق الداخلي.",
        )
    supplier = db.get(Supplier, invoice.supplier_id)
    if not supplier or supplier.company_id != invoice.company_id:
        return check_result(
            "SUPPLIER_VERIFICATION",
            "التحقق الداخلي من المورد",
            "WARNING",
            "مرجع المورد غير صالح ويحتاج مراجعة.",
        )
    labels = {
        "UNVERIFIED": "لم يراجع فريق المالية المورد داخليًا بعد.",
        "PENDING": "التحقق الداخلي من المورد ما زال قيد المراجعة.",
        "VERIFIED": "راجع فريق المالية بيانات المورد واعتمدها داخليًا.",
        "REJECTED": "رفض فريق المالية التحقق الداخلي من المورد؛ راجع الملاحظة في سجل المورد.",
    }
    status = (
        "PASS"
        if supplier.verification_status == "VERIFIED"
        else "WARNING"
        if supplier.verification_status == "REJECTED"
        else "NOT_CHECKED"
    )
    return check_result(
        "SUPPLIER_VERIFICATION",
        "التحقق الداخلي من المورد",
        status,
        labels[supplier.verification_status],
        document_value=supplier.verification_status,
    )


def related_financial_document_check(db, invoice):
    label = "ربط الإشعار بالفاتورة الأصلية"
    if invoice.document_type == "INVOICE":
        notes = list(
            db.scalars(
                select(Invoice).where(
                    Invoice.related_invoice_id == invoice.id,
                    Invoice.company_id == invoice.company_id,
                    Invoice.project_id == invoice.project_id,
                    Invoice.status.in_(("PROJECT_REVIEW", "FINANCE_REVIEW", "APPROVED")),
                )
            )
        )
        credits = sum(
            (item.grand_total or Decimal("0"))
            for item in notes
            if item.document_type == "CREDIT_NOTE"
        )
        debits = sum(
            (item.grand_total or Decimal("0"))
            for item in notes
            if item.document_type == "DEBIT_NOTE"
        )
        original_total = invoice.grand_total
        balance = original_total + debits - credits if original_total is not None else None
        over_credit = balance is not None and balance < 0
        return check_result(
            "RELATED_FINANCIAL_DOCUMENT",
            label,
            "WARNING" if over_credit else "PASS",
            (
                "إجمالي الإشعارات الدائنة يتجاوز قيمة الفاتورة الأصلية بعد الإشعارات المدينة."
                if over_credit
                else f"الفاتورة أصلية ومرتبطة بعدد {len(notes)} من الإشعارات المرسلة."
            ),
            document_value=format(original_total, ".2f") if original_total is not None else None,
            calculated_value=format(balance, ".2f") if balance is not None else None,
            match_count=len(notes),
        )

    original = db.get(Invoice, invoice.related_invoice_id) if invoice.related_invoice_id else None
    valid = bool(
        original
        and original.company_id == invoice.company_id
        and original.project_id == invoice.project_id
        and original.document_type == "INVOICE"
    )
    if not valid:
        return check_result(
            "RELATED_FINANCIAL_DOCUMENT",
            label,
            "WARNING",
            "رابط الفاتورة الأصلية غير صالح للشركة أو المشروع.",
        )
    comparisons = [
        {
            "field": "related_supplier",
            "label": "المورد",
            "source_value": str(original.supplier_id or ""),
            "invoice_value": str(invoice.supplier_id or ""),
            "status": "MATCH" if original.supplier_id == invoice.supplier_id else "MISMATCH",
        },
        {
            "field": "related_currency",
            "label": "العملة",
            "source_value": original.currency,
            "invoice_value": invoice.currency,
            "status": "MATCH" if original.currency == invoice.currency else "MISMATCH",
        },
    ]
    related = list(
        db.scalars(
            select(Invoice).where(
                Invoice.related_invoice_id == original.id,
                Invoice.id != invoice.id,
                Invoice.company_id == invoice.company_id,
                Invoice.project_id == invoice.project_id,
                Invoice.status.in_(("PROJECT_REVIEW", "FINANCE_REVIEW", "APPROVED")),
            )
        )
    )
    related.append(invoice)
    credits = sum(
        (item.grand_total or Decimal("0"))
        for item in related
        if item.document_type == "CREDIT_NOTE"
    )
    debits = sum(
        (item.grand_total or Decimal("0")) for item in related if item.document_type == "DEBIT_NOTE"
    )
    balance = (original.grand_total or Decimal("0")) + debits - credits
    mismatch = any(item["status"] == "MISMATCH" for item in comparisons)
    over_credit = balance < 0
    return check_result(
        "RELATED_FINANCIAL_DOCUMENT",
        label,
        "WARNING" if mismatch or over_credit else "PASS",
        (
            "ارتباط الإشعار يحتاج مراجعة بسبب اختلاف البيانات أو تجاوز الرصيد."
            if mismatch or over_credit
            else "الإشعار مرتبط بفاتورة أصلية مطابقة، والرصيد بعد الإشعارات غير سالب."
        ),
        document_value=format(original.grand_total or Decimal("0"), ".2f"),
        calculated_value=format(balance, ".2f"),
        match_count=len(related),
        comparisons=comparisons,
    )


def split_invoice_check(db, invoice):
    label = "كشف تجزئة الفواتير حول حد الموافقة"
    if invoice.document_type != "INVOICE":
        result = check_result(
            "SPLIT_INVOICE",
            label,
            "NOT_CHECKED",
            "يطبق كشف التجزئة على الفواتير الأصلية فقط.",
        )
        result["split_analysis"] = None
        return result
    if any(
        value is None
        for value in (
            invoice.supplier_id,
            invoice.invoice_date,
            invoice.currency,
            invoice.grand_total,
        )
    ):
        result = check_result(
            "SPLIT_INVOICE",
            label,
            "NOT_CHECKED",
            "يلزم المورد والتاريخ والعملة والإجمالي لمقارنة مجموعة الفواتير.",
        )
        result["split_analysis"] = None
        return result

    limits = list(
        db.scalars(
            select(ApprovalLimit.amount)
            .join(User, User.id == ApprovalLimit.user_id)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(
                ApprovalLimit.company_id == invoice.company_id,
                ApprovalLimit.currency == invoice.currency,
                User.company_id == invoice.company_id,
                User.role == "PROJECT_MANAGER",
                User.is_active.is_(True),
                ProjectMember.project_id == invoice.project_id,
                ProjectMember.membership_role == "MANAGER",
            )
        )
    )
    if not limits:
        result = check_result(
            "SPLIT_INVOICE",
            label,
            "NOT_CHECKED",
            "لا يوجد حد موافقة مسجل لمدير هذا المشروع بهذه العملة.",
        )
        result["split_analysis"] = None
        return result

    window_days = 7
    candidates = list(
        db.scalars(
            select(Invoice).where(
                Invoice.id != invoice.id,
                Invoice.company_id == invoice.company_id,
                Invoice.project_id == invoice.project_id,
                Invoice.supplier_id == invoice.supplier_id,
                Invoice.currency == invoice.currency,
                Invoice.document_type == "INVOICE",
                Invoice.grand_total.is_not(None),
                Invoice.invoice_date.between(
                    invoice.invoice_date - timedelta(days=window_days),
                    invoice.invoice_date + timedelta(days=window_days),
                ),
                Invoice.status.in_(("PROJECT_REVIEW", "FINANCE_REVIEW", "APPROVED")),
            )
        )
    )
    candidates.append(invoice)
    threshold = min(limits)
    combined_total = sum((candidate.grand_total for candidate in candidates), Decimal("0"))
    individually_within_limit = all(candidate.grand_total <= threshold for candidate in candidates)
    suspected = len(candidates) >= 2 and individually_within_limit and combined_total > threshold
    result = check_result(
        "SPLIT_INVOICE",
        label,
        "WARNING" if suspected else "PASS",
        (
            "توجد فواتير منفردة ضمن الحد، لكن مجموعها للمورد والمشروع خلال سبعة أيام يتجاوز الحد."
            if suspected
            else "لم تظهر مجموعة فواتير تستوفي قاعدة التجزئة حول حد الموافقة."
        ),
        document_value=format(invoice.grand_total, ".2f"),
        calculated_value=format(combined_total, ".2f"),
        match_count=max(len(candidates) - 1, 0),
    )
    result["split_analysis"] = {
        "window_days": window_days,
        "document_count": len(candidates),
        "combined_total": format(combined_total, ".2f"),
        "approval_threshold": format(threshold, ".2f"),
        "all_documents_within_threshold": individually_within_limit,
        "privacy_note": "تعرض النتيجة عدد المستندات والمجموع دون أرقام الفواتير الأخرى أو أصحابها.",
    }
    return result


def project_budget_checks(db, invoice):
    relevance_label = "ربط البنود بميزانية المشروع"
    capacity_label = "سعة ميزانية المشروع"
    if not invoice.currency:
        return [
            check_result(
                "PROJECT_BUDGET_RELEVANCE",
                relevance_label,
                "NOT_CHECKED",
                "اختر العملة حتى يمكن تحديد ميزانية المشروع.",
            ),
            check_result(
                "PROJECT_BUDGET_CAPACITY",
                capacity_label,
                "NOT_CHECKED",
                "اختر العملة والإجمالي حتى يمكن حساب أثر المستند على الميزانية.",
            ),
        ]
    budget = db.scalar(
        select(ProjectBudget).where(
            ProjectBudget.company_id == invoice.company_id,
            ProjectBudget.project_id == invoice.project_id,
            ProjectBudget.currency == invoice.currency,
        )
    )
    if not budget:
        message = "لا توجد ميزانية مسجلة لهذا المشروع بهذه العملة."
        return [
            check_result("PROJECT_BUDGET_RELEVANCE", relevance_label, "NOT_CHECKED", message),
            check_result("PROJECT_BUDGET_CAPACITY", capacity_label, "NOT_CHECKED", message),
        ]

    items = list(
        db.scalars(
            select(InvoiceItem)
            .where(InvoiceItem.invoice_id == invoice.id)
            .order_by(InvoiceItem.position)
        )
    )
    if not items:
        relevance = check_result(
            "PROJECT_BUDGET_RELEVANCE",
            relevance_label,
            "NOT_CHECKED",
            "لا توجد بنود فاتورة لربطها ببنود الميزانية.",
        )
    else:
        missing = [item for item in items if not item.project_budget_line_id]
        relevance = check_result(
            "PROJECT_BUDGET_RELEVANCE",
            relevance_label,
            "WARNING" if missing else "PASS",
            (
                f"يوجد {len(missing)} بند فاتورة غير مصنف على بند ميزانية."
                if missing
                else "جميع بنود الفاتورة مصنفة على بنود ميزانية المشروع."
            ),
            match_count=len(items) - len(missing),
            source_count=len(items),
        )

    if invoice.grand_total is None:
        capacity = check_result(
            "PROJECT_BUDGET_CAPACITY",
            capacity_label,
            "NOT_CHECKED",
            "لا يوجد إجمالي محسوب لقياس أثر المستند على الميزانية.",
        )
        return [relevance, capacity]

    counted = list(
        db.scalars(
            select(Invoice).where(
                Invoice.id != invoice.id,
                Invoice.company_id == invoice.company_id,
                Invoice.project_id == invoice.project_id,
                Invoice.currency == invoice.currency,
                Invoice.status.in_(
                    ("PROJECT_REVIEW", "FINANCE_REVIEW", "CHANGES_REQUESTED", "APPROVED")
                ),
            )
        )
    )
    exposure_before = sum(
        (
            -(candidate.grand_total or Decimal("0"))
            if candidate.document_type == "CREDIT_NOTE"
            else candidate.grand_total or Decimal("0")
            for candidate in counted
        ),
        Decimal("0"),
    )
    document_amount = (
        -invoice.grand_total if invoice.document_type == "CREDIT_NOTE" else invoice.grand_total
    )
    exposure_after = exposure_before + document_amount
    remaining = budget.total_amount - exposure_after
    capacity = check_result(
        "PROJECT_BUDGET_CAPACITY",
        capacity_label,
        "WARNING" if remaining < 0 else "PASS",
        (
            "يتجاوز الأثر المتوقع لهذا المستند ميزانية المشروع المسجلة."
            if remaining < 0
            else "الأثر المتوقع للمستند ضمن إجمالي ميزانية المشروع المسجلة."
        ),
        document_value=format(document_amount, ".2f"),
        calculated_value=format(remaining, ".2f"),
        match_count=len(counted),
    )
    capacity["budget_analysis"] = {
        "currency": budget.currency,
        "budget_total": format(budget.total_amount, ".2f"),
        "exposure_before_document": format(exposure_before, ".2f"),
        "document_effect": format(document_amount, ".2f"),
        "exposure_after_document": format(exposure_after, ".2f"),
        "remaining_after_document": format(remaining, ".2f"),
        "definition": "يشمل المعتمد والملتزم وقيد المراجعة، ويستبعد المسودات والمرفوض.",
    }
    return [relevance, capacity]


RISK_WEIGHTS = {
    "DOCUMENT_SUBTOTAL": 6,
    "DOCUMENT_TAX_TOTAL": 8,
    "DOCUMENT_GRAND_TOTAL": 10,
    "EXACT_FILE_DUPLICATE": 25,
    "POTENTIAL_DUPLICATE": 20,
    "APPROXIMATE_DUPLICATE": 20,
    "HISTORICAL_PRICE_ANOMALY": 15,
    "REGIONAL_SUPPLIER_PRICE": 15,
    "QR_SOURCE_COMPARISON": 8,
    "XML_SOURCE_COMPARISON": 8,
    "SUPPLIER_VERIFICATION": 10,
    "RELATED_FINANCIAL_DOCUMENT": 15,
    "PURCHASE_ORDER_HEADER": 8,
    "PURCHASE_ORDER_LINES": 12,
    "GOODS_RECEIPT_MATCH": 12,
    "SPLIT_INVOICE": 25,
    "PROJECT_BUDGET_RELEVANCE": 10,
    "PROJECT_BUDGET_CAPACITY": 20,
}


def risk_assessment(checks):
    factors = [
        {
            "code": check["code"],
            "label": check["label"],
            "weight": RISK_WEIGHTS[check["code"]],
            "message": check["message"],
        }
        for check in checks
        if check["status"] == "WARNING"
    ]
    factors.sort(key=lambda factor: (-factor["weight"], factor["code"]))
    score = min(sum(factor["weight"] for factor in factors), 100)
    evaluated_count = sum(check["status"] != "NOT_CHECKED" for check in checks)
    confidence = "HIGH" if evaluated_count >= 10 else "MEDIUM" if evaluated_count >= 6 else "LOW"
    level = "HIGH" if score >= 50 else "MEDIUM" if score >= 20 else "LOW"
    return {
        "score": score,
        "level": level,
        "confidence": confidence,
        "warning_count": len(factors),
        "evaluated_count": evaluated_count,
        "total_checks": len(checks),
        "factors": factors,
        "policy": {
            "version": "explainable-review-priority-v1",
            "medium_from": 20,
            "high_from": 50,
            "maximum_score": 100,
        },
        "advisory": "الدرجة ترتب أولوية المراجعة ولا تمثل احتمال احتيال أو قرار اعتماد آلي.",
    }


def audit_data(db, invoice):
    calculated_net = (
        invoice.subtotal - invoice.discount_total
        if invoice.subtotal is not None and invoice.discount_total is not None
        else None
    )
    checks = [
        total_check(
            invoice,
            "DOCUMENT_SUBTOTAL",
            "الصافي قبل الضريبة",
            "document_subtotal",
            calculated_net,
        ),
        total_check(
            invoice,
            "DOCUMENT_TAX_TOTAL",
            "إجمالي الضريبة",
            "document_tax_total",
            invoice.tax_total,
        ),
        total_check(
            invoice,
            "DOCUMENT_GRAND_TOTAL",
            "الإجمالي المستحق",
            "document_grand_total",
            invoice.grand_total,
        ),
        exact_file_duplicate_check(db, invoice),
        potential_duplicate_check(db, invoice),
        approximate_duplicate_check(db, invoice),
        price_history_check(db, invoice),
        regional_price_check(db, invoice),
        source_check(db, invoice, "QR", "QR_SOURCE_COMPARISON", "مطابقة بيانات QR"),
        source_check(db, invoice, "XML", "XML_SOURCE_COMPARISON", "مطابقة بيانات XML"),
        supplier_verification_check(db, invoice),
        related_financial_document_check(db, invoice),
        *purchase_order_checks(db, invoice),
        split_invoice_check(db, invoice),
        *project_budget_checks(db, invoice),
    ]
    if any(check["status"] == "WARNING" for check in checks):
        summary = "NEEDS_REVIEW"
    elif any(check["status"] == "NOT_CHECKED" for check in checks[:5]):
        summary = "INCOMPLETE"
    else:
        summary = "PASS"
    return {
        "revision": invoice.revision,
        "summary": summary,
        "blocking": False,
        "checks": checks,
        "risk": risk_assessment(checks),
    }
