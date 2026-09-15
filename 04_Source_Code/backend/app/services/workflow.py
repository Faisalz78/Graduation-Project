from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.models import Attachment, AuditLog, Supplier, utcnow
from app.schemas.invoice_data import CalculationInput
from app.schemas.workflow import WorkflowInput
from app.services.calculations import calculate
from app.services.financial_audit import audit_data
from app.services.invoice_data import financial_data
from app.services.invoices import lock_invoice

EDITABLE = ("DRAFT", "CHANGES_REQUESTED")


def allowed_actions(db, user, invoice):
    if user.role == "EMPLOYEE" and invoice.created_by == user.id and invoice.status in EDITABLE:
        return ["EDIT", "SUBMIT"]
    if invoice.created_by == user.id:
        return []
    if (user.role == "PROJECT_MANAGER" and invoice.status == "PROJECT_REVIEW") or (
        user.role == "FINANCE_MANAGER"
        and invoice.status == "FINANCE_REVIEW"
        and invoice.project_approved_by != user.id
    ):
        from app.services.governance import approval_authority

        actions = ["REQUEST_CHANGES", "REJECT"]
        authority = approval_authority(db, user, invoice)
        if authority and authority["can_approve"]:
            actions.insert(0, "APPROVE")
        return actions
    return []


def missing_fields(invoice, financial):
    missing = []
    for field, label in [
        ("supplier_id", "المورد"),
        ("invoice_number", "رقم الفاتورة"),
        ("invoice_date", "تاريخ الفاتورة"),
        ("currency", "العملة"),
    ]:
        if not getattr(invoice, field):
            missing.append(label)
    if not financial["items"]:
        missing.append("بند واحد على الأقل")
    return missing


def workflow_data(db, user, invoice):
    from app.services.governance import approval_authority

    return {
        "allowed_actions": allowed_actions(db, user, invoice),
        "missing_fields": missing_fields(invoice, financial_data(db, invoice, include_items=True)),
        "submitted_revision": invoice.submitted_revision,
        "submitted_at": invoice.submitted_at,
        "project_approved_revision": invoice.project_approved_revision,
        "approval_authority": approval_authority(db, user, invoice),
    }


def validate_submission(db, invoice, financial):
    missing = missing_fields(invoice, financial)
    if missing:
        raise HTTPException(422, "أكمل البيانات قبل الإرسال: " + "، ".join(missing) + ".")
    supplier = db.get(Supplier, invoice.supplier_id)
    if not supplier or supplier.company_id != invoice.company_id or not invoice.supplier_snapshot:
        raise HTTPException(422, "راجع المورد واحفظ بيانات الفاتورة مجددًا.")
    attachment = db.scalar(select(Attachment).where(Attachment.invoice_id == invoice.id))
    path = (get_settings().upload_dir / attachment.storage_key).resolve() if attachment else None
    if (
        not path
        or not path.is_relative_to(get_settings().upload_dir.resolve())
        or not path.is_file()
    ):
        raise HTTPException(422, "الملف الأصلي غير متاح. لا يمكن إرسال الفاتورة دون أصلها.")
    fields = ("description", "unit", "quantity", "unit_price", "discount_amount", "tax_rate")
    calculated = calculate(
        CalculationInput.model_validate(
            {
                "currency": invoice.currency,
                "items": [{key: line[key] for key in fields} for line in financial["items"]],
            }
        )
    )
    expected_items = [
        {
            key: value
            for key, value in line.items()
            if key
            not in (
                "purchase_order_item_id",
                "purchase_order_item_position",
                "project_budget_line_id",
                "budget_line",
            )
        }
        for line in financial["items"]
    ]
    if calculated["totals"] != financial["totals"] or calculated["items"] != expected_items:
        raise HTTPException(422, "الحسابات المحفوظة غير متطابقة. راجع البنود واحفظها مجددًا.")


def transition(db, user, invoice_id, data: WorkflowInput):
    invoice = lock_invoice(db, user, invoice_id)
    if invoice.revision != data.revision:
        raise HTTPException(
            409, "تغيرت نسخة الفاتورة أو حالتها. حمّل أحدث نسخة وراجعها قبل اتخاذ القرار."
        )
    if data.action not in allowed_actions(db, user, invoice):
        raise HTTPException(
            403,
            "هذا الإجراء غير متاح لدورك أو لحالة الفاتورة الحالية؛ لا يمكنك مراجعة فاتورتك أو اعتماد المرحلتين بالحساب نفسه.",
        )
    previous_status = invoice.status
    financial = financial_data(db, invoice, include_items=True)
    audit = audit_data(db, invoice)
    if data.action == "SUBMIT":
        validate_submission(db, invoice, financial)
        invoice.status = "PROJECT_REVIEW"
        invoice.submitted_revision = invoice.revision + 1
        invoice.submitted_at = utcnow()
        invoice.project_approved_by = None
        invoice.project_approved_revision = None
        event = "INVOICE_SUBMITTED" if previous_status == "DRAFT" else "INVOICE_RESUBMITTED"
    elif data.action == "APPROVE":
        from app.services.governance import require_approval_authority

        require_approval_authority(db, user, invoice)
        if previous_status == "PROJECT_REVIEW":
            invoice.status = "FINANCE_REVIEW"
            invoice.project_approved_by = user.id
            invoice.project_approved_revision = invoice.submitted_revision
            event = "PROJECT_APPROVED"
        else:
            if (
                not invoice.project_approved_by
                or invoice.project_approved_revision != invoice.submitted_revision
            ):
                raise HTTPException(409, "يلزم اعتماد مدير المشروع للنسخة المرسلة نفسها.")
            invoice.status = "APPROVED"
            event = "FINANCE_APPROVED"
    else:
        invoice.status = "CHANGES_REQUESTED" if data.action == "REQUEST_CHANGES" else "REJECTED"
        invoice.project_approved_by = None
        invoice.project_approved_revision = None
        event = "CHANGES_REQUESTED" if data.action == "REQUEST_CHANGES" else "INVOICE_REJECTED"
    invoice.revision += 1
    invoice.updated_at = utcnow()
    db.add(
        AuditLog(
            company_id=invoice.company_id,
            invoice_id=invoice.id,
            actor_id=user.id,
            action=event,
            details={
                "revision": invoice.revision,
                "previous_revision": data.revision,
                "from_status": previous_status,
                "to_status": invoice.status,
                "submitted_revision": invoice.submitted_revision,
                "actor_role": user.role,
                "comment": data.comment,
                "employee_confirmed": data.action == "SUBMIT" and data.confirmed,
                "snapshot": {**financial, "note": invoice.note},
                "audit_snapshot": audit,
            },
        )
    )
    from app.services.notifications import add_workflow_notifications

    add_workflow_notifications(db, user, invoice, event, audit)
    db.commit()
    return invoice
