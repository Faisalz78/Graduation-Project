import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import Db, Identity, require_csrf
from app.schemas.governance import ApprovalLimitInput
from app.services.governance import approval_limits_result, set_approval_limit

router = APIRouter(prefix="/governance", tags=["Governance"])


@router.get("/approval-limits")
def list_approval_limits(db: Db, identity: Identity):
    if identity[0].role != "FINANCE_MANAGER":
        raise HTTPException(403, "إدارة حدود الموافقات متاحة لمدير المالية فقط.")
    return approval_limits_result(db, identity[0].company_id)


@router.put("/approval-limits/{user_id}/{currency}", dependencies=[Depends(require_csrf)])
def update_approval_limit(
    user_id: uuid.UUID,
    currency: Literal["SAR", "AED", "USD", "EUR"],
    data: ApprovalLimitInput,
    db: Db,
    identity: Identity,
):
    return set_approval_limit(db, identity[0], user_id, currency, data.amount)
