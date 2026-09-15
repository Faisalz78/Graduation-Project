import uuid
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.models import (
    AuditLog,
    ExpenseCategory,
    Invoice,
    InvoiceItem,
    ProjectBudget,
    ProjectBudgetLine,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    utcnow,
)
from app.schemas.invoice_data import InvoiceUpdate
from app.services.calculations import POLICY, calculate
from app.services.invoices import lock_invoice

DECIMAL_FIELDS = {
    "quantity": 4,
    "unit_price": 4,
    "discount_amount": 2,
    "tax_rate": 4,
    "gross_amount": 2,
    "net_amount": 2,
    "tax_amount": 2,
    "total_amount": 2,
}


def financial_data(db, invoice, *, include_items=False):
    totals = None
    if invoice.grand_total is not None:
        totals = {
            key: format(getattr(invoice, key), ".2f")
            for key in ("subtotal", "discount_total", "tax_total", "grand_total")
        }
        totals["net_total"] = format(invoice.subtotal - invoice.discount_total, ".2f")
    supplier_data = dict(invoice.supplier_snapshot) if invoice.supplier_snapshot else None
    if supplier_data and invoice.supplier_id:
        supplier = db.get(Supplier, invoice.supplier_id)
        if supplier and supplier.company_id == invoice.company_id:
            supplier_data.update(
                verification_status=supplier.verification_status,
                verification_note=supplier.verification_note,
                verified_at=supplier.verified_at.isoformat() if supplier.verified_at else None,
            )
    result = {
        "supplier": supplier_data,
        "purchase_order": None,
        "document_type": invoice.document_type,
        "related_document": related_document_reference(
            db, invoice.related_invoice_id, invoice.company_id
        ),
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "currency": invoice.currency,
        "document_totals": (
            {
                "subtotal": (
                    format(invoice.document_subtotal, ".2f")
                    if invoice.document_subtotal is not None
                    else None
                ),
                "tax_total": (
                    format(invoice.document_tax_total, ".2f")
                    if invoice.document_tax_total is not None
                    else None
                ),
                "grand_total": (
                    format(invoice.document_grand_total, ".2f")
                    if invoice.document_grand_total is not None
                    else None
                ),
            }
            if any(
                value is not None
                for value in (
                    invoice.document_subtotal,
                    invoice.document_tax_total,
                    invoice.document_grand_total,
                )
            )
            else None
        ),
        "totals": totals,
        "calculation_policy": POLICY,
    }
    if invoice.purchase_order_id:
        from app.services.purchase_orders import purchase_order_reference

        result["purchase_order"] = purchase_order_reference(db, invoice.purchase_order_id)
    if include_items:
        items = list(
            db.scalars(
                select(InvoiceItem)
                .where(InvoiceItem.invoice_id == invoice.id)
                .order_by(InvoiceItem.position)
            )
        )
        budget_line_ids = {
            item.project_budget_line_id for item in items if item.project_budget_line_id
        }
        budget_lines = {
            line.id: line
            for line in db.scalars(
                select(ProjectBudgetLine).where(ProjectBudgetLine.id.in_(budget_line_ids))
            )
        }
        result["items"] = [
            {
                "position": item.position,
                "description": item.description,
                "unit": item.unit,
                "purchase_order_item_id": (
                    str(item.purchase_order_item_id) if item.purchase_order_item_id else None
                ),
                "purchase_order_item_position": (
                    db.get(PurchaseOrderItem, item.purchase_order_item_id).position
                    if item.purchase_order_item_id
                    else None
                ),
                "project_budget_line_id": (
                    str(item.project_budget_line_id) if item.project_budget_line_id else None
                ),
                "budget_line": budget_line_reference(
                    db, budget_lines.get(item.project_budget_line_id)
                ),
                **{
                    key: format(getattr(item, key), f".{digits}f")
                    for key, digits in DECIMAL_FIELDS.items()
                },
            }
            for item in items
        ]
    return result


def budget_line_reference(db, line):
    if not line:
        return None
    category = db.get(ExpenseCategory, line.expense_category_id)
    budget = db.get(ProjectBudget, line.project_budget_id)
    return {
        "id": str(line.id),
        "position": line.position,
        "description": line.description,
        "allocated_amount": format(line.allocated_amount, ".2f"),
        "is_active": line.is_active,
        "currency": budget.currency,
        "category": {
            "id": str(category.id),
            "code": category.code,
            "name": category.name,
        },
    }


def related_document_reference(db, invoice_id, company_id=None):
    if not invoice_id:
        return None
    original = db.get(Invoice, invoice_id)
    if not original or (company_id is not None and original.company_id != company_id):
        return None
    return {
        "id": str(original.id),
        "invoice_number": original.invoice_number,
        "invoice_date": original.invoice_date.isoformat() if original.invoice_date else None,
        "currency": original.currency,
        "grand_total": format(original.grand_total, ".2f")
        if original.grand_total is not None
        else None,
        "status": original.status,
    }


def related_invoice_options(db, user, invoice):
    candidates = db.scalars(
        select(Invoice)
        .where(
            Invoice.id != invoice.id,
            Invoice.company_id == user.company_id,
            Invoice.project_id == invoice.project_id,
            Invoice.created_by == user.id,
            Invoice.document_type == "INVOICE",
            Invoice.status.in_(("PROJECT_REVIEW", "FINANCE_REVIEW", "APPROVED")),
        )
        .order_by(Invoice.invoice_date.desc().nullslast(), Invoice.created_at.desc())
    )
    return [
        related_document_reference(db, candidate.id, user.company_id) for candidate in candidates
    ]


def update_invoice(db, user, invoice_id, data: InvoiceUpdate):
    if user.role != "EMPLOYEE":
        raise HTTPException(403, "تعديل المسودة متاح لصاحبها الموظف فقط.")
    invoice = lock_invoice(db, user, invoice_id)
    if invoice.status not in ("DRAFT", "CHANGES_REQUESTED"):
        raise HTTPException(
            409, "التعديل متاح للمسودة أو عند طلب تعديل فقط. حدّث الفاتورة لمعرفة حالتها."
        )
    if invoice.revision != data.revision:
        raise HTTPException(
            409, "حُفظت نسخة أحدث من الفاتورة. أعد تحميلها قبل تعديلها؛ لم نحفظ هذه التغييرات."
        )
    if data.extraction_job_id:
        from app.services.extraction import validate_review

        validate_review(db, user, invoice, data.extraction_job_id)
    purchase_order = None
    mapped_item_ids = {
        item.purchase_order_item_id for item in data.items if item.purchase_order_item_id
    }
    mapped_budget_line_ids = {
        item.project_budget_line_id for item in data.items if item.project_budget_line_id
    }
    if data.document_type != "INVOICE" and (data.purchase_order_id or mapped_item_ids):
        raise HTTPException(
            422, "الإشعار الدائن أو المدين يرتبط بالفاتورة الأصلية دون أمر شراء مباشر."
        )
    if data.purchase_order_id:
        purchase_order = db.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.id == data.purchase_order_id,
                PurchaseOrder.company_id == user.company_id,
                PurchaseOrder.project_id == invoice.project_id,
            )
        )
        if purchase_order is None:
            raise HTTPException(404, "أمر الشراء غير موجود أو لا يخص مشروع الفاتورة.")
        valid_item_ids = set(
            db.scalars(
                select(PurchaseOrderItem.id).where(
                    PurchaseOrderItem.purchase_order_id == purchase_order.id,
                    PurchaseOrderItem.id.in_(mapped_item_ids),
                )
            )
        )
        if valid_item_ids != mapped_item_ids:
            raise HTTPException(422, "يتضمن الربط بندًا لا ينتمي إلى أمر الشراء المختار.")
    elif mapped_item_ids:
        raise HTTPException(422, "اختر أمر الشراء قبل ربط بنوده بالفاتورة.")
    budget_lines = {
        line.id: line
        for line in db.scalars(
            select(ProjectBudgetLine)
            .join(ProjectBudget, ProjectBudget.id == ProjectBudgetLine.project_budget_id)
            .where(
                ProjectBudgetLine.id.in_(mapped_budget_line_ids),
                ProjectBudgetLine.is_active.is_(True),
                ProjectBudget.company_id == user.company_id,
                ProjectBudget.project_id == invoice.project_id,
                ProjectBudget.currency == data.currency,
            )
        )
    }
    if set(budget_lines) != mapped_budget_line_ids:
        raise HTTPException(
            422, "يتضمن ربط الميزانية بندًا غير نشط أو لا يخص مشروع الفاتورة وعملتها."
        )
    supplier_snapshot = None
    if data.supplier_id:
        supplier = db.scalar(
            select(Supplier).where(
                Supplier.id == data.supplier_id, Supplier.company_id == user.company_id
            )
        )
        if not supplier:
            raise HTTPException(404, "المورد غير موجود أو غير متاح لشركتك.")
        supplier_snapshot = {
            "id": str(supplier.id),
            "name": supplier.name,
            "tax_number": supplier.tax_number,
            "region_code": supplier.region_code,
            "verification_status": supplier.verification_status,
            "verification_note": supplier.verification_note,
            "verified_at": supplier.verified_at.isoformat() if supplier.verified_at else None,
        }
    related_invoice = None
    if data.related_invoice_id:
        related_invoice = db.scalar(
            select(Invoice).where(
                Invoice.id == data.related_invoice_id,
                Invoice.company_id == user.company_id,
                Invoice.project_id == invoice.project_id,
                Invoice.created_by == user.id,
                Invoice.document_type == "INVOICE",
                Invoice.status.in_(("PROJECT_REVIEW", "FINANCE_REVIEW", "APPROVED")),
            )
        )
        if not related_invoice:
            raise HTTPException(404, "الفاتورة الأصلية غير موجودة أو لم تُرسل للمراجعة بعد.")
        if data.supplier_id != related_invoice.supplier_id:
            raise HTTPException(422, "يجب أن يكون مورد الإشعار مطابقًا لمورد الفاتورة الأصلية.")
        if data.currency != related_invoice.currency:
            raise HTTPException(422, "يجب أن تكون عملة الإشعار مطابقة لعملة الفاتورة الأصلية.")
        if (
            data.invoice_date
            and related_invoice.invoice_date
            and data.invoice_date < related_invoice.invoice_date
        ):
            raise HTTPException(422, "لا يمكن أن يسبق تاريخ الإشعار تاريخ الفاتورة الأصلية.")
    calculated = calculate(data)
    purchase_order_items = {
        item.id: item
        for item in db.scalars(
            select(PurchaseOrderItem).where(PurchaseOrderItem.id.in_(mapped_item_ids))
        )
    }
    calculated_items = [
        {
            **item,
            "purchase_order_item_id": (
                str(source.purchase_order_item_id) if source.purchase_order_item_id else None
            ),
            "purchase_order_item_position": (
                purchase_order_items[source.purchase_order_item_id].position
                if source.purchase_order_item_id
                else None
            ),
            "project_budget_line_id": (
                str(source.project_budget_line_id) if source.project_budget_line_id else None
            ),
            "budget_line": budget_line_reference(
                db, budget_lines.get(source.project_budget_line_id)
            ),
        }
        for item, source in zip(calculated["items"], data.items)
    ]
    from app.services.purchase_orders import purchase_order_reference

    document_totals = data.document_totals
    document_totals_data = (
        {
            "subtotal": (
                format(document_totals.subtotal, ".2f")
                if document_totals.subtotal is not None
                else None
            ),
            "tax_total": (
                format(document_totals.tax_total, ".2f")
                if document_totals.tax_total is not None
                else None
            ),
            "grand_total": (
                format(document_totals.grand_total, ".2f")
                if document_totals.grand_total is not None
                else None
            ),
        }
        if document_totals
        and any(
            value is not None
            for value in (
                document_totals.subtotal,
                document_totals.tax_total,
                document_totals.grand_total,
            )
        )
        else None
    )
    before = {**financial_data(db, invoice, include_items=True), "note": invoice.note}
    after = {
        "supplier": supplier_snapshot,
        "purchase_order": purchase_order_reference(db, purchase_order.id)
        if purchase_order
        else None,
        "document_type": data.document_type,
        "related_document": related_document_reference(db, related_invoice.id, user.company_id)
        if related_invoice
        else None,
        "invoice_number": data.invoice_number,
        "invoice_date": data.invoice_date.isoformat() if data.invoice_date else None,
        "currency": data.currency,
        "document_totals": document_totals_data,
        "note": data.note,
        **{**calculated, "items": calculated_items},
    }
    if before == after and not data.extraction_job_id:
        db.commit()
        return invoice
    invoice.supplier_id = data.supplier_id
    invoice.supplier_snapshot = supplier_snapshot
    invoice.purchase_order_id = purchase_order.id if purchase_order else None
    invoice.document_type = data.document_type
    invoice.related_invoice_id = related_invoice.id if related_invoice else None
    invoice.invoice_number = data.invoice_number
    invoice.invoice_date = data.invoice_date
    invoice.currency = data.currency
    invoice.note = data.note
    invoice.document_subtotal = document_totals.subtotal if document_totals else None
    invoice.document_tax_total = document_totals.tax_total if document_totals else None
    invoice.document_grand_total = document_totals.grand_total if document_totals else None
    for field in ("subtotal", "discount_total", "tax_total", "grand_total"):
        setattr(
            invoice, field, Decimal(calculated["totals"][field]) if calculated["totals"] else None
        )
    db.execute(delete(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))
    for item in calculated_items:
        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                **{
                    key: (
                        Decimal(value)
                        if key in DECIMAL_FIELDS
                        else uuid.UUID(value)
                        if key in {"purchase_order_item_id", "project_budget_line_id"} and value
                        else value
                    )
                    for key, value in item.items()
                    if key not in {"purchase_order_item_position", "budget_line"}
                },
            )
        )
    invoice.revision += 1
    invoice.updated_at = utcnow()
    if data.extraction_job_id:
        db.add(
            AuditLog(
                company_id=invoice.company_id,
                invoice_id=invoice.id,
                actor_id=user.id,
                action="EXTRACTION_REVIEWED",
                details={
                    "job_id": str(data.extraction_job_id),
                    "revision": invoice.revision,
                    "confirmed": True,
                },
            )
        )
    db.add(
        AuditLog(
            company_id=invoice.company_id,
            invoice_id=invoice.id,
            actor_id=user.id,
            action="DRAFT_UPDATED",
            details={"revision": invoice.revision, "before": before, "after": after},
        )
    )
    db.commit()
    return invoice
