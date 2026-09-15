import hashlib
import unicodedata
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.security import Db, Identity, require_csrf
from app.models import Supplier, User
from app.regions import SAUDI_REGIONS
from app.schemas.governance import SupplierVerificationInput
from app.schemas.invoice_data import SupplierInput
from app.services.governance import verify_supplier

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


def supplier_result(db, supplier):
    reviewer = db.get(User, supplier.verified_by) if supplier.verified_by else None
    return {
        "id": supplier.id,
        "name": supplier.name,
        "tax_number": supplier.tax_number,
        "region_code": supplier.region_code,
        "region_name": SAUDI_REGIONS.get(supplier.region_code),
        "verification_status": supplier.verification_status,
        "verification_note": supplier.verification_note,
        "verified_at": supplier.verified_at,
        "verified_by": ({"id": reviewer.id, "name": reviewer.name} if reviewer else None),
        "created_at": supplier.created_at,
    }


@router.get("")
def list_suppliers(db: Db, identity: Identity):
    suppliers = db.scalars(
        select(Supplier)
        .where(Supplier.company_id == identity[0].company_id)
        .order_by(Supplier.name, Supplier.id)
    )
    return [supplier_result(db, supplier) for supplier in suppliers]


@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
def add_supplier(data: SupplierInput, db: Db, identity: Identity):
    user = identity[0]
    if user.role not in {"EMPLOYEE", "FINANCE_MANAGER"}:
        raise HTTPException(403, "إضافة المورد متاحة للموظف ومدير المالية.")
    name = " ".join(data.name.split())
    key = hashlib.sha256(unicodedata.normalize("NFKC", name).casefold().encode()).hexdigest()
    supplier = Supplier(
        company_id=user.company_id,
        name=name,
        name_key=key,
        tax_number=data.tax_number,
        region_code=data.region_code,
        created_by=user.id,
    )
    db.add(supplier)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "يوجد مورد بهذا الاسم في الشركة. اختره من قائمة الموردين."
        ) from None
    return supplier_result(db, supplier)


@router.put("/{supplier_id}/verification", dependencies=[Depends(require_csrf)])
def update_supplier_verification(
    supplier_id: uuid.UUID,
    data: SupplierVerificationInput,
    db: Db,
    identity: Identity,
):
    return supplier_result(db, verify_supplier(db, identity[0], supplier_id, data))
