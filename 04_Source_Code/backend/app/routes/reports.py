import uuid
from datetime import date

from fastapi import APIRouter, Query, Response

from app.core.security import Db, Identity
from app.schemas.invoice_data import Currency
from app.schemas.workflow import InvoiceStatus
from app.services.reports import (
    invoice_register_csv,
    project_budgets_csv,
    regional_prices_csv,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


def csv_response(content, name):
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}-{date.today().isoformat()}.csv"'
        },
    )


@router.get("/invoices.csv")
def invoice_register(
    db: Db,
    identity: Identity,
    project_id: uuid.UUID | None = None,
    currency: Currency | None = None,
    status: InvoiceStatus | None = None,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    content = invoice_register_csv(
        db,
        identity[0],
        project_id=project_id,
        currency=currency,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    return csv_response(content, "invoice-register")


@router.get("/budgets.csv")
def budget_report(
    db: Db,
    identity: Identity,
    project_id: uuid.UUID | None = None,
    currency: Currency | None = None,
):
    return csv_response(
        project_budgets_csv(db, identity[0], project_id=project_id, currency=currency),
        "project-budgets",
    )


@router.get("/regional-prices.csv")
def regional_price_report(
    db: Db,
    identity: Identity,
    project_id: uuid.UUID | None = None,
    currency: Currency | None = None,
    status: InvoiceStatus | None = None,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    content = regional_prices_csv(
        db,
        identity[0],
        project_id=project_id,
        currency=currency,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    return csv_response(content, "regional-prices")
