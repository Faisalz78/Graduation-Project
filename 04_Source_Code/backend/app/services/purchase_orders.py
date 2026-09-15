import logging
import unicodedata
import uuid
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    ProcurementAuditLog,
    Project,
    ProjectMember,
    PurchaseOrder,
    PurchaseOrderItem,
    ReceiptAttachment,
    Supplier,
    User,
)
from app.schemas.purchase_orders import PurchaseOrderInput, ReceiptInput
from app.services.calculations import money

log = logging.getLogger(__name__)


def normalize_reference(value: str) -> str:
    digits = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    normalized = unicodedata.normalize("NFKC", value).translate(digits).casefold()
    return "".join(character for character in normalized if character.isalnum())


def visible_purchase_orders(user: User):
    query = (
        select(PurchaseOrder)
        .join(Project, Project.id == PurchaseOrder.project_id)
        .where(
            PurchaseOrder.company_id == user.company_id,
            Project.company_id == user.company_id,
            Project.is_active.is_(True),
        )
    )
    if user.role == "FINANCE_MANAGER":
        return query
    membership = exists(
        select(ProjectMember.project_id).where(
            ProjectMember.project_id == PurchaseOrder.project_id,
            ProjectMember.user_id == user.id,
        )
    )
    query = query.where(membership)
    if user.role == "PROJECT_MANAGER":
        manager = exists(
            select(ProjectMember.project_id).where(
                ProjectMember.project_id == PurchaseOrder.project_id,
                ProjectMember.user_id == user.id,
                ProjectMember.membership_role == "MANAGER",
            )
        )
        query = query.where(manager)
    return query


def require_purchase_order(db: Session, user: User, purchase_order_id: uuid.UUID):
    purchase_order = db.scalar(
        visible_purchase_orders(user).where(PurchaseOrder.id == purchase_order_id)
    )
    if purchase_order is None:
        raise HTTPException(404, "أمر الشراء غير موجود أو غير متاح لك.")
    return purchase_order


def purchase_order_reference(db: Session, purchase_order_id: uuid.UUID | None):
    if purchase_order_id is None:
        return None
    purchase_order = db.get(PurchaseOrder, purchase_order_id)
    if purchase_order is None:
        return None
    project = db.get(Project, purchase_order.project_id)
    supplier = db.get(Supplier, purchase_order.supplier_id)
    return {
        "id": str(purchase_order.id),
        "number": purchase_order.number,
        "order_date": purchase_order.order_date.isoformat(),
        "currency": purchase_order.currency,
        "project": {"id": str(project.id), "name": project.name, "code": project.code},
        "supplier": {
            "id": str(supplier.id),
            "name": supplier.name,
            "tax_number": supplier.tax_number,
        },
    }


def serialize_purchase_order(db: Session, purchase_order: PurchaseOrder):
    result = purchase_order_reference(db, purchase_order.id)
    creator = db.get(User, purchase_order.created_by)
    items = list(
        db.scalars(
            select(PurchaseOrderItem)
            .where(PurchaseOrderItem.purchase_order_id == purchase_order.id)
            .order_by(PurchaseOrderItem.position)
        )
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
    subtotal = tax_total = Decimal("0")
    item_results = []
    for item in items:
        gross = money(item.ordered_quantity * item.unit_price)
        tax = money(gross * item.tax_rate / Decimal("100"))
        subtotal += gross
        tax_total += tax
        item_results.append(
            {
                "id": item.id,
                "position": item.position,
                "description": item.description,
                "unit": item.unit,
                "ordered_quantity": format(item.ordered_quantity, ".4f"),
                "received_quantity": format(received.get(item.id, Decimal("0")), ".4f"),
                "unit_price": format(item.unit_price, ".4f"),
                "tax_rate": format(item.tax_rate, ".4f"),
                "subtotal": format(gross, ".2f"),
                "tax_total": format(tax, ".2f"),
                "grand_total": format(gross + tax, ".2f"),
            }
        )
    receipts = []
    for receipt in db.scalars(
        select(GoodsReceipt)
        .where(GoodsReceipt.purchase_order_id == purchase_order.id)
        .order_by(GoodsReceipt.received_date.desc(), GoodsReceipt.created_at.desc())
    ):
        evidence = db.scalar(
            select(ReceiptAttachment).where(ReceiptAttachment.goods_receipt_id == receipt.id)
        )
        receipt_items = {
            item_id: quantity
            for item_id, quantity in db.execute(
                select(
                    GoodsReceiptItem.purchase_order_item_id,
                    GoodsReceiptItem.received_quantity,
                ).where(GoodsReceiptItem.goods_receipt_id == receipt.id)
            )
        }
        receipts.append(
            {
                "id": receipt.id,
                "number": receipt.number,
                "received_date": receipt.received_date.isoformat(),
                "note": receipt.note,
                "created_by": {
                    "id": receipt.created_by,
                    "name": db.get(User, receipt.created_by).name,
                },
                "created_at": receipt.created_at,
                "items": [
                    {
                        "purchase_order_item_id": item.id,
                        "position": item.position,
                        "received_quantity": format(receipt_items[item.id], ".4f"),
                    }
                    for item in items
                    if item.id in receipt_items
                ],
                "evidence": {
                    "id": evidence.id,
                    "name": evidence.original_name,
                    "media_type": evidence.media_type,
                    "size_bytes": evidence.size_bytes,
                    "url": (
                        f"/api/v1/purchase-orders/{purchase_order.id}/receipts/{receipt.id}/file"
                    ),
                },
            }
        )
    result.update(
        {
            "created_by": {"id": creator.id, "name": creator.name},
            "created_at": purchase_order.created_at,
            "items": item_results,
            "receipts": receipts,
            "totals": {
                "subtotal": format(subtotal, ".2f"),
                "tax_total": format(tax_total, ".2f"),
                "grand_total": format(subtotal + tax_total, ".2f"),
            },
        }
    )
    return result


def create_purchase_order(db: Session, user: User, data: PurchaseOrderInput):
    if user.role != "FINANCE_MANAGER":
        raise HTTPException(403, "إنشاء أمر الشراء متاح لمدير المالية فقط.")
    project = db.scalar(
        select(Project).where(
            Project.id == data.project_id,
            Project.company_id == user.company_id,
            Project.is_active.is_(True),
        )
    )
    supplier = db.scalar(
        select(Supplier).where(
            Supplier.id == data.supplier_id, Supplier.company_id == user.company_id
        )
    )
    if project is None or supplier is None:
        raise HTTPException(404, "المشروع أو المورد غير موجود داخل شركتك.")
    number = " ".join(data.number.split())
    number_key = normalize_reference(number)
    if not number_key:
        raise HTTPException(422, "رقم أمر الشراء غير صالح.")
    purchase_order = PurchaseOrder(
        company_id=user.company_id,
        project_id=project.id,
        supplier_id=supplier.id,
        number=number,
        number_key=number_key,
        order_date=data.order_date,
        currency=data.currency,
        created_by=user.id,
    )
    db.add(purchase_order)
    try:
        db.flush()
        for position, item in enumerate(data.items, 1):
            db.add(
                PurchaseOrderItem(
                    purchase_order_id=purchase_order.id,
                    position=position,
                    description=item.description,
                    unit=item.unit,
                    ordered_quantity=item.ordered_quantity,
                    unit_price=item.unit_price,
                    tax_rate=item.tax_rate,
                )
            )
        db.add(
            ProcurementAuditLog(
                company_id=user.company_id,
                purchase_order_id=purchase_order.id,
                actor_id=user.id,
                action="PURCHASE_ORDER_CREATED",
                details={
                    "number": number,
                    "project_id": str(project.id),
                    "supplier_id": str(supplier.id),
                    "currency": data.currency,
                    "item_count": len(data.items),
                },
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "يوجد أمر شراء بهذا الرقم داخل الشركة.") from None
    return purchase_order


def create_goods_receipt(
    db: Session,
    user: User,
    purchase_order_id: uuid.UUID,
    data: ReceiptInput,
    content: bytes,
    name: str,
    media_type: str,
    digest: str,
):
    if user.role != "EMPLOYEE":
        raise HTTPException(403, "تسجيل الاستلام متاح لموظف المشتريات فقط.")
    require_purchase_order(db, user, purchase_order_id)
    purchase_order = db.scalar(
        visible_purchase_orders(user)
        .where(PurchaseOrder.id == purchase_order_id)
        .with_for_update(of=PurchaseOrder)
        .execution_options(populate_existing=True)
    )
    if purchase_order is None:
        raise HTTPException(404, "أمر الشراء غير موجود أو غير متاح لك.")
    number = " ".join(data.number.split())
    number_key = normalize_reference(number)
    if not number_key:
        raise HTTPException(422, "رقم محضر الاستلام غير صالح.")
    duplicate = db.scalar(
        select(GoodsReceipt.id).where(
            GoodsReceipt.purchase_order_id == purchase_order.id,
            GoodsReceipt.number_key == number_key,
        )
    )
    if duplicate:
        raise HTTPException(409, "يوجد محضر استلام بهذا الرقم لأمر الشراء.")
    order_items = {
        item.id: item
        for item in db.scalars(
            select(PurchaseOrderItem).where(
                PurchaseOrderItem.purchase_order_id == purchase_order.id
            )
        )
    }
    if any(item.purchase_order_item_id not in order_items for item in data.items):
        raise HTTPException(422, "يتضمن محضر الاستلام بندًا لا ينتمي إلى أمر الشراء.")

    receipt = GoodsReceipt(
        purchase_order_id=purchase_order.id,
        number=number,
        number_key=number_key,
        received_date=data.received_date,
        note=data.note,
        created_by=user.id,
    )
    attachment_id = uuid.uuid4()
    suffix = Path(name).suffix.lower()
    storage_key = f"receipts/{attachment_id.hex}{suffix}"
    root = get_settings().upload_dir.resolve()
    path = root / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as output:
            output.write(content)
        db.add(receipt)
        db.flush()
        db.add_all(
            [
                GoodsReceiptItem(
                    goods_receipt_id=receipt.id,
                    purchase_order_item_id=item.purchase_order_item_id,
                    received_quantity=item.received_quantity,
                )
                for item in data.items
            ]
        )
        db.add(
            ReceiptAttachment(
                id=attachment_id,
                goods_receipt_id=receipt.id,
                storage_key=storage_key,
                original_name=name,
                media_type=media_type,
                size_bytes=len(content),
                sha256=digest,
                uploaded_by=user.id,
            )
        )
        db.add(
            ProcurementAuditLog(
                company_id=user.company_id,
                purchase_order_id=purchase_order.id,
                goods_receipt_id=receipt.id,
                actor_id=user.id,
                action="GOODS_RECEIPT_RECORDED",
                details={
                    "number": number,
                    "received_date": data.received_date.isoformat(),
                    "items": [
                        {
                            "purchase_order_item_id": str(item.purchase_order_item_id),
                            "received_quantity": format(item.received_quantity, ".4f"),
                        }
                        for item in data.items
                    ],
                    "attachment_id": str(attachment_id),
                    "attachment_name": name,
                },
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        try:
            with Session(db.get_bind()) as check:
                if check.get(ReceiptAttachment, attachment_id) is None:
                    path.unlink(missing_ok=True)
        except Exception:
            log.exception("Could not confirm receipt evidence cleanup for %s", attachment_id)
        raise
    return purchase_order
