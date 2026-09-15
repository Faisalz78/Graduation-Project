import uuid

from fastapi import APIRouter, Depends

from app.core.security import Db, Identity, require_csrf
from app.schemas.extraction import ExtractionRequest
from app.services.extraction import (
    attachment_for,
    available,
    latest,
    owner,
    request_extraction,
    serialize,
)

router = APIRouter(prefix="/invoices", tags=["Extraction"])


@router.get("/{invoice_id}/extraction")
def get_extraction(invoice_id: uuid.UUID, db: Db, identity: Identity):
    invoice = owner(db, identity[0], invoice_id)
    return {
        "available": available(),
        "job": serialize(latest(db, invoice_id), invoice, attachment_for(db, invoice)),
    }


@router.post("/{invoice_id}/extraction", dependencies=[Depends(require_csrf)])
def start_extraction(invoice_id: uuid.UUID, data: ExtractionRequest, db: Db, identity: Identity):
    return request_extraction(db, identity[0], invoice_id, data)
