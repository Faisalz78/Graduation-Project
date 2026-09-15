import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import Db, Identity, require_csrf
from app.models import Attachment, Invoice
from app.schemas.invoice_data import CalculationInput, InvoiceUpdate
from app.schemas.workflow import InvoiceStatus, WorkflowInput
from app.services.calculations import calculate
from app.services.documents import validate_document
from app.services.invoice_data import related_invoice_options, update_invoice
from app.services.invoices import create_draft, require_invoice, serialize_invoice, visible_invoices
from app.services.workflow import transition

router = APIRouter(prefix="/invoices", tags=["Invoices"])


@router.get("")
def list_invoices(
    db: Db,
    identity: Identity,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    status: InvoiceStatus | None = None,
):
    query = visible_invoices(identity[0])
    if status:
        query = query.where(Invoice.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))

    invoices = db.scalars(
        query.order_by(Invoice.created_at.desc(), Invoice.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [serialize_invoice(db, i) for i in invoices],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
async def upload_invoice(
    db: Db,
    identity: Identity,
    response: Response,
    project_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[
        str, Header(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    ],
    note: Annotated[str | None, Form(max_length=1000)] = None,
):
    if identity[0].role != "EMPLOYEE":
        raise HTTPException(403, "إنشاء المسودات متاح للموظف فقط.")
    chunks, size = [], 0
    try:
        while chunk := await file.read(256 * 1024):
            size += len(chunk)
            if size > get_settings().max_upload_bytes:
                raise HTTPException(413, "حجم الملف يتجاوز 10 ميغابايت.")
            chunks.append(chunk)
    finally:
        await file.close()
    data = b"".join(chunks)
    from starlette.concurrency import run_in_threadpool

    name, media, digest = await run_in_threadpool(
        validate_document, data, file.filename or "invoice"
    )
    # Validation and database work use a worker thread, leaving the event loop responsive.
    invoice, replayed = await run_in_threadpool(
        create_draft,
        db,
        identity[0],
        project_id,
        data,
        name,
        media,
        digest,
        (note or "").strip() or None,
        idempotency_key,
    )
    if replayed:
        response.status_code = 200
        response.headers["Idempotency-Replayed"] = "true"
    return serialize_invoice(db, invoice, include_events=True, user=identity[0])


@router.get("/{invoice_id}")
def invoice_details(invoice_id: uuid.UUID, db: Db, identity: Identity):
    return serialize_invoice(
        db, require_invoice(db, identity[0], invoice_id), include_events=True, user=identity[0]
    )


@router.get("/{invoice_id}/file")
def original_file(invoice_id: uuid.UUID, db: Db, identity: Identity, inline: bool = False):
    invoice = require_invoice(db, identity[0], invoice_id)
    attachment = db.scalar(select(Attachment).where(Attachment.invoice_id == invoice.id))
    path = (get_settings().upload_dir / attachment.storage_key).resolve()
    if not path.is_relative_to(get_settings().upload_dir.resolve()) or not path.is_file():
        raise HTTPException(404, "الملف غير متاح حاليًا.")
    return FileResponse(
        path,
        media_type=attachment.media_type,
        filename=attachment.original_name,
        content_disposition_type="inline" if inline else "attachment",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.put("/{invoice_id}", dependencies=[Depends(require_csrf)])
def save_invoice_data(invoice_id: uuid.UUID, data: InvoiceUpdate, db: Db, identity: Identity):
    invoice = update_invoice(db, identity[0], invoice_id, data)
    return serialize_invoice(db, invoice, include_events=True, user=identity[0])


@router.get("/{invoice_id}/related-options")
def list_related_invoice_options(invoice_id: uuid.UUID, db: Db, identity: Identity):
    invoice = require_invoice(db, identity[0], invoice_id)
    if identity[0].role != "EMPLOYEE" or invoice.created_by != identity[0].id:
        raise HTTPException(403, "اختيار الفاتورة الأصلية متاح لصاحب المسودة فقط.")
    return related_invoice_options(db, identity[0], invoice)


@router.get("/{invoice_id}/preview/{page}")
def preview_page(invoice_id: uuid.UUID, page: int, db: Db, identity: Identity):
    from app.services.preview import pdf_preview

    invoice = require_invoice(db, identity[0], invoice_id)
    attachment = db.scalar(select(Attachment).where(Attachment.invoice_id == invoice.id))
    if attachment.media_type != "application/pdf" or not 1 <= page <= 3:
        raise HTTPException(404, "صفحة المعاينة غير متاحة.")
    return FileResponse(pdf_preview(attachment, page), media_type="image/png")


@router.post("/{invoice_id}/workflow", dependencies=[Depends(require_csrf)])
def invoice_workflow(invoice_id: uuid.UUID, data: WorkflowInput, db: Db, identity: Identity):
    invoice = transition(db, identity[0], invoice_id, data)
    return serialize_invoice(db, invoice, include_events=True, user=identity[0])


@router.post("/{invoice_id}/calculate", dependencies=[Depends(require_csrf)])
def preview_totals(invoice_id: uuid.UUID, data: CalculationInput, db: Db, identity: Identity):
    require_invoice(db, identity[0], invoice_id)
    return calculate(data)
