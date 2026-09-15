import uuid
from typing import Literal

from fastapi import APIRouter

from app.core.security import Db, Identity
from app.services.analytics import dashboard_data

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/dashboard")
def dashboard(
    db: Db,
    identity: Identity,
    currency: Literal["SAR", "AED", "USD", "EUR"] = "SAR",
    project_id: uuid.UUID | None = None,
):
    return dashboard_data(db, identity[0], currency, project_id)
