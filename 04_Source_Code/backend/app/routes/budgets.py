import uuid

from fastapi import APIRouter, Depends

from app.core.security import Db, Identity, require_csrf
from app.schemas.budgets import ExpenseCategoryInput, ProjectBudgetInput
from app.schemas.invoice_data import Currency
from app.services.budgets import budget_view, create_category, list_categories, save_budget

router = APIRouter(tags=["Project budgets"])


@router.get("/expense-categories")
def expense_categories(db: Db, identity: Identity):
    return list_categories(db, identity[0])


@router.post("/expense-categories", status_code=201, dependencies=[Depends(require_csrf)])
def add_expense_category(data: ExpenseCategoryInput, db: Db, identity: Identity):
    return create_category(db, identity[0], data)


@router.get("/projects/{project_id}/budgets/{currency}")
def get_project_budget(project_id: uuid.UUID, currency: Currency, db: Db, identity: Identity):
    return budget_view(db, identity[0], project_id, currency)


@router.put("/projects/{project_id}/budgets/{currency}", dependencies=[Depends(require_csrf)])
def put_project_budget(
    project_id: uuid.UUID,
    currency: Currency,
    data: ProjectBudgetInput,
    db: Db,
    identity: Identity,
):
    if data.currency != currency:
        from fastapi import HTTPException

        raise HTTPException(422, "عملة المسار لا تطابق عملة الميزانية المرسلة.")
    return save_budget(db, identity[0], project_id, data)
