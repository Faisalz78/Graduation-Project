import hashlib
import json
import logging
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Attachment,
    AuditLog,
    IdempotencyRecord,
    Invoice,
    Project,
    ProjectMember,
    User,
)

log = logging.getLogger(__name__)


def visible_invoices(user: User):
    scope = select(Invoice).where(Invoice.company_id == user.company_id)
    if user.role == "FINANCE_MANAGER":
        return scope.where(
            Invoice.status != "DRAFT",
            exists(
                select(Project.id).where(
                    Project.id == Invoice.project_id,
                    Project.company_id == user.company_id,
                    Project.is_active.is_(True),
                )
            ),
        )
    membership = exists(
        select(ProjectMember.project_id)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(
            ProjectMember.user_id == user.id,
            ProjectMember.project_id == Invoice.project_id,
            Project.is_active.is_(True),
            Project.company_id == user.company_id,
        )
    )
    if user.role == "PROJECT_MANAGER":
        manager = exists(
            select(ProjectMember.project_id).where(
                ProjectMember.project_id == Invoice.project_id,
                ProjectMember.user_id == user.id,
                ProjectMember.membership_role == "MANAGER",
            )
        )
        return scope.where(Invoice.status != "DRAFT", membership, manager)
    return scope.where(Invoice.created_by == user.id, membership)


def require_invoice(db: Session, user: User, invoice_id: uuid.UUID) -> Invoice:
    invoice = db.scalar(visible_invoices(user).where(Invoice.id == invoice_id))
    if not invoice:
        raise HTTPException(404, "الفاتورة غير موجودة أو غير متاحة لك.")
    return invoice


def lock_invoice(db: Session, user: User, invoice_id: uuid.UUID) -> Invoice:
    scoped = require_invoice(db, user, invoice_id)
    # All mutations lock project/membership before invoice, including edits and uploads.
    query = select(Project).where(
        Project.id == scoped.project_id,
        Project.company_id == user.company_id,
        Project.is_active.is_(True),
    )
    if user.role != "FINANCE_MANAGER":
        query = query.join(ProjectMember).where(ProjectMember.user_id == user.id)
        if user.role == "PROJECT_MANAGER":
            query = query.where(ProjectMember.membership_role == "MANAGER")
    if not db.scalar(query.with_for_update()):
        raise HTTPException(404, "الفاتورة غير موجودة أو غير متاحة لك.")
    invoice = db.scalar(
        visible_invoices(user)
        .where(Invoice.id == invoice_id)
        .with_for_update(of=Invoice)
        .execution_options(populate_existing=True)
    )
    if not invoice:
        raise HTTPException(404, "الفاتورة غير موجودة أو غير متاحة لك.")
    return invoice


def serialize_invoice(db: Session, invoice: Invoice, *, include_events=False, user=None):
    from app.services.invoice_data import financial_data

    attachment = db.scalar(select(Attachment).where(Attachment.invoice_id == invoice.id))
    project = db.get(Project, invoice.project_id)
    creator = db.get(User, invoice.created_by)
    result = {
        "id": invoice.id,
        "status": invoice.status,
        "revision": invoice.revision,
        "note": invoice.note,
        "created_at": invoice.created_at,
        "updated_at": invoice.updated_at,
        "project": {"id": project.id, "name": project.name, "code": project.code},
        "created_by": {"id": creator.id, "name": creator.name},
        "attachment": {
            "id": attachment.id,
            "name": attachment.original_name,
            "media_type": attachment.media_type,
            "size_bytes": attachment.size_bytes,
            "url": f"/api/v1/invoices/{invoice.id}/file",
        },
    }
    if include_events:
        events = db.scalars(
            select(AuditLog)
            .where(AuditLog.invoice_id == invoice.id)
            .order_by(AuditLog.created_at, AuditLog.id)
        )
        result["events"] = [
            {
                "id": e.id,
                "action": e.action,
                "created_at": e.created_at,
                "actor_name": db.get(User, e.actor_id).name,
                "details": e.details,
            }
            for e in events
        ]
    result.update(financial_data(db, invoice, include_items=include_events))
    if include_events and user is not None:
        from app.services.financial_audit import audit_data
        from app.services.workflow import workflow_data

        result["audit"] = audit_data(db, invoice)
        result["workflow"] = workflow_data(db, user, invoice)
    return result


def create_draft(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    data: bytes,
    name: str,
    media: str,
    digest: str,
    note: str | None,
    key: str,
) -> tuple[Invoice, bool]:
    if user.role != "EMPLOYEE":
        raise HTTPException(403, "إنشاء المسودات متاح للموظف فقط.")
    project = db.scalar(
        select(Project)
        .join(ProjectMember)
        .where(
            Project.id == project_id,
            Project.company_id == user.company_id,
            Project.is_active.is_(True),
            ProjectMember.user_id == user.id,
        )
        .with_for_update()
    )
    if not project:
        raise HTTPException(404, "المشروع غير موجود أو غير متاح لك.")

    fingerprint = hashlib.sha256(
        json.dumps(
            {"project": str(project_id), "sha256": digest, "name": name, "note": note},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    # Transaction-scoped locks serialize simultaneous retries of the same request across workers.
    lock_id = int.from_bytes(
        hashlib.sha256(f"{user.id}:invoice:{key}".encode()).digest()[:8], "big", signed=True
    )
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
    record = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.operation == "CREATE_DRAFT",
            IdempotencyRecord.key == key,
        )
    )
    if record:
        if record.request_hash != fingerprint:
            raise HTTPException(409, "استُخدم معرّف الطلب لملف أو بيانات مختلفة. ابدأ رفعًا جديدًا.")
        invoice = require_invoice(db, user, record.invoice_id)
        db.commit()
        return invoice, True

    invoice = Invoice(
        id=uuid.uuid4(),
        company_id=user.company_id,
        project_id=project.id,
        created_by=user.id,
        status="DRAFT",
        note=note,
    )
    attachment_id = uuid.uuid4()
    storage_key = f"{attachment_id.hex}{Path(name).suffix.lower()}"
    directory = get_settings().upload_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / storage_key
    try:
        with path.open("xb") as output:
            output.write(data)
        db.add(invoice)
        db.flush()
        db.add(
            Attachment(
                id=attachment_id,
                invoice_id=invoice.id,
                storage_key=storage_key,
                original_name=name,
                media_type=media,
                size_bytes=len(data),
                sha256=digest,
                uploaded_by=user.id,
            )
        )
        db.add_all(
            [
                AuditLog(
                    company_id=user.company_id,
                    invoice_id=invoice.id,
                    actor_id=user.id,
                    action="DRAFT_CREATED",
                    details={"revision": 1},
                ),
                AuditLog(
                    company_id=user.company_id,
                    invoice_id=invoice.id,
                    actor_id=user.id,
                    action="FILE_ATTACHED",
                    details={"attachment_id": str(attachment_id)},
                ),
            ]
        )
        db.add(
            IdempotencyRecord(
                user_id=user.id,
                operation="CREATE_DRAFT",
                key=key,
                request_hash=fingerprint,
                invoice_id=invoice.id,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        # A lost connection during COMMIT has an uncertain outcome. Only remove a file
        # after a fresh query confirms that no committed attachment refers to it.
        try:
            with Session(db.get_bind()) as check:
                if not check.get(Attachment, attachment_id):
                    path.unlink(missing_ok=True)
        except Exception:
            log.exception("Could not confirm attachment cleanup for %s", attachment_id)
        raise
    return invoice, False
