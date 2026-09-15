import uuid
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    ApprovalLimit,
    ApprovalLimitAuditLog,
    Supplier,
    SupplierAuditLog,
    User,
    utcnow,
)

CURRENCIES = ("SAR", "AED", "USD", "EUR")


def approval_limit_for(db, user, currency):
    if not currency:
        return None
    return db.scalar(
        select(ApprovalLimit).where(
            ApprovalLimit.company_id == user.company_id,
            ApprovalLimit.user_id == user.id,
            ApprovalLimit.currency == currency,
        )
    )


def approval_authority(db, user, invoice):
    relevant = (user.role == "PROJECT_MANAGER" and invoice.status == "PROJECT_REVIEW") or (
        user.role == "FINANCE_MANAGER" and invoice.status == "FINANCE_REVIEW"
    )
    if not relevant:
        return None
    limit = approval_limit_for(db, user, invoice.currency)
    total = invoice.grand_total
    allowed = bool(limit is not None and total is not None and total <= limit.amount)
    return {
        "currency": invoice.currency,
        "invoice_total": format(total, ".2f") if total is not None else None,
        "limit": format(limit.amount, ".2f") if limit else None,
        "can_approve": allowed,
        "reason": (
            "المبلغ ضمن حد موافقتك."
            if allowed
            else "لا يوجد حد موافقة مسجل لك لهذه العملة."
            if limit is None
            else "إجمالي المستند يتجاوز حد موافقتك ويحتاج مراجعًا مخولًا بحد أعلى."
        ),
    }


def require_approval_authority(db, user, invoice):
    authority = approval_authority(db, user, invoice)
    if not authority or not authority["can_approve"]:
        raise HTTPException(403, authority["reason"] if authority else "لا تملك صلاحية الموافقة.")
    return authority


def approval_limits_result(db, company_id):
    users = list(
        db.scalars(
            select(User)
            .where(
                User.company_id == company_id,
                User.is_active.is_(True),
                User.role.in_(("PROJECT_MANAGER", "FINANCE_MANAGER")),
            )
            .order_by(User.role, User.name, User.id)
        )
    )
    limits = {
        (limit.user_id, limit.currency): limit
        for limit in db.scalars(select(ApprovalLimit).where(ApprovalLimit.company_id == company_id))
    }
    return [
        {
            "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
            "limits": {
                currency: (
                    format(limits[(user.id, currency)].amount, ".2f")
                    if (user.id, currency) in limits
                    else None
                )
                for currency in CURRENCIES
            },
        }
        for user in users
    ]


def set_approval_limit(db, actor, target_id: uuid.UUID, currency: str, amount: Decimal):
    if actor.role != "FINANCE_MANAGER":
        raise HTTPException(403, "إدارة حدود الموافقات متاحة لمدير المالية فقط.")
    if actor.id == target_id:
        raise HTTPException(403, "لا يمكنك تعديل حد موافقتك بنفسك؛ استخدم مدير مالية آخر.")
    target = db.scalar(
        select(User).where(
            User.id == target_id,
            User.company_id == actor.company_id,
            User.is_active.is_(True),
            User.role.in_(("PROJECT_MANAGER", "FINANCE_MANAGER")),
        )
    )
    if not target:
        raise HTTPException(404, "المراجع غير موجود أو غير متاح لشركتك.")
    record = db.scalar(
        select(ApprovalLimit)
        .where(ApprovalLimit.user_id == target.id, ApprovalLimit.currency == currency)
        .with_for_update()
    )
    before = format(record.amount, ".2f") if record else None
    if record is None:
        record = ApprovalLimit(
            company_id=actor.company_id,
            user_id=target.id,
            currency=currency,
            amount=amount,
            updated_by=actor.id,
        )
        db.add(record)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "تغير الحد من جلسة أخرى. أعد تحميل الصفحة.") from None
    else:
        record.amount = amount
        record.updated_by = actor.id
        record.updated_at = utcnow()
    db.add(
        ApprovalLimitAuditLog(
            company_id=actor.company_id,
            approval_limit_id=record.id,
            actor_id=actor.id,
            details={
                "target_user_id": str(target.id),
                "target_role": target.role,
                "currency": currency,
                "before": before,
                "after": format(amount, ".2f"),
            },
        )
    )
    db.commit()
    return approval_limits_result(db, actor.company_id)


def verify_supplier(db, actor, supplier_id, data):
    if actor.role != "FINANCE_MANAGER":
        raise HTTPException(403, "مراجعة المورد متاحة لمدير المالية فقط.")
    supplier = db.scalar(
        select(Supplier)
        .where(Supplier.id == supplier_id, Supplier.company_id == actor.company_id)
        .with_for_update()
    )
    if not supplier:
        raise HTTPException(404, "المورد غير موجود أو غير متاح لشركتك.")
    if data.status == "VERIFIED" and not supplier.tax_number:
        raise HTTPException(422, "أضف الرقم الضريبي قبل اعتماد التحقق الداخلي من المورد.")
    before = {
        "status": supplier.verification_status,
        "note": supplier.verification_note,
        "region_code": supplier.region_code,
    }
    supplier.verification_status = data.status
    supplier.verification_note = data.note
    supplier.region_code = data.region_code
    supplier.verified_by = actor.id
    supplier.verified_at = utcnow()
    db.add(
        SupplierAuditLog(
            company_id=actor.company_id,
            supplier_id=supplier.id,
            actor_id=actor.id,
            action="SUPPLIER_VERIFICATION_CHANGED",
            details={
                "before": before,
                "after": {
                    "status": data.status,
                    "note": data.note,
                    "region_code": data.region_code,
                },
                "method": "INTERNAL_MANUAL_REVIEW",
            },
        )
    )
    db.commit()
    return supplier
