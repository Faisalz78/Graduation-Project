import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.security import Db, Identity, require_csrf
from app.models import GoodsReceipt, PurchaseOrder, ReceiptAttachment
from app.schemas.purchase_orders import PurchaseOrderInput, ReceiptInput
from app.services.documents import validate_document
from app.services.purchase_orders import (
    create_goods_receipt,
    create_purchase_order,
    require_purchase_order,
    serialize_purchase_order,
    visible_purchase_orders,
)

router = APIRouter(prefix="/purchase-orders", tags=["Purchase orders"])


@router.get("")
def list_purchase_orders(db: Db, identity: Identity):
    orders = db.scalars(
        visible_purchase_orders(identity[0]).order_by(
            PurchaseOrder.order_date.desc(), PurchaseOrder.created_at.desc()
        )
    )
    return [serialize_purchase_order(db, order) for order in orders]


@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
def add_purchase_order(data: PurchaseOrderInput, db: Db, identity: Identity):
    order = create_purchase_order(db, identity[0], data)
    return serialize_purchase_order(db, order)


@router.post("/{purchase_order_id}/receipts", status_code=201, dependencies=[Depends(require_csrf)])
async def add_goods_receipt(
    purchase_order_id: uuid.UUID,
    db: Db,
    identity: Identity,
    receipt_data: Annotated[str, Form(min_length=2, max_length=30_000)],
    file: Annotated[UploadFile, File()],
):
    try:
        data = ReceiptInput.model_validate_json(receipt_data)
    except ValidationError:
        raise HTTPException(422, "راجع رقم المحضر وتاريخه والكميات المستلمة.") from None
    chunks, size = [], 0
    try:
        while chunk := await file.read(256 * 1024):
            size += len(chunk)
            if size > get_settings().max_upload_bytes:
                raise HTTPException(413, "حجم ملف إثبات الاستلام يتجاوز 10 ميغابايت.")
            chunks.append(chunk)
    finally:
        await file.close()
    content = b"".join(chunks)
    name, media_type, digest = await run_in_threadpool(
        validate_document, content, file.filename or "receipt"
    )
    if media_type not in {"application/pdf", "image/jpeg", "image/png"}:
        raise HTTPException(422, "إثبات الاستلام يجب أن يكون PDF أو JPEG أو PNG.")
    order = await run_in_threadpool(
        create_goods_receipt,
        db,
        identity[0],
        purchase_order_id,
        data,
        content,
        name,
        media_type,
        digest,
    )
    return serialize_purchase_order(db, order)


@router.get("/{purchase_order_id}/receipts/{receipt_id}/file")
def receipt_file(purchase_order_id: uuid.UUID, receipt_id: uuid.UUID, db: Db, identity: Identity):
    purchase_order = require_purchase_order(db, identity[0], purchase_order_id)
    receipt = db.scalar(
        select(GoodsReceipt).where(
            GoodsReceipt.id == receipt_id,
            GoodsReceipt.purchase_order_id == purchase_order.id,
        )
    )
    if receipt is None:
        raise HTTPException(404, "محضر الاستلام غير موجود أو غير متاح لك.")
    attachment = db.scalar(
        select(ReceiptAttachment).where(ReceiptAttachment.goods_receipt_id == receipt.id)
    )
    path = (get_settings().upload_dir / attachment.storage_key).resolve() if attachment else None
    if (
        path is None
        or not path.is_relative_to(get_settings().upload_dir.resolve())
        or not path.is_file()
    ):
        raise HTTPException(404, "ملف إثبات الاستلام غير متاح حاليًا.")
    return FileResponse(
        path,
        media_type=attachment.media_type,
        filename=attachment.original_name,
        content_disposition_type="attachment",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
