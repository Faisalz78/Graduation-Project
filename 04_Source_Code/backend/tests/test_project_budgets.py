from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_invoice_data import draft, item, payload, save
from test_workflow import act

from app.models import BudgetAuditLog
from conftest import login


def create_category(client, code="MAT", name="مواد المشروع"):
    response = client.post("/api/v1/expense-categories", json={"code": code, "name": name})
    assert response.status_code == 201, response.text
    return response.json()


def budget_payload(category, total="1000.00", revision=0, lines=None):
    return {
        "currency": "SAR",
        "revision": revision,
        "total_amount": total,
        "lines": lines
        if lines is not None
        else [
            {
                "expense_category_id": category["id"],
                "description": "توريد مواد أساسية",
                "unit": "قطعة",
                "planned_quantity": "10",
                "planned_unit_price": "50",
                "allocated_amount": "500.00",
            }
        ],
    }


def create_budget(client, world, *, project="a", total="1000.00"):
    login(client, world, "finance")
    category = create_category(client)
    data = budget_payload(category, total=total)
    if Decimal(total) < Decimal("500.00"):
        data["lines"] = [
            {
                "expense_category_id": category["id"],
                "description": "مخصص المشروع",
                "unit": None,
                "planned_quantity": None,
                "planned_unit_price": None,
                "allocated_amount": total,
            }
        ]
    response = client.put(
        f"/api/v1/projects/{world['projects'][project].id}/budgets/SAR",
        json=data,
    )
    assert response.status_code == 200, response.text
    return category, response.json()


def create_invoice_at(
    client,
    world,
    supplier_id,
    line_id,
    target,
    *,
    document_type="INVOICE",
    related_invoice_id=None,
):
    login(client, world)
    invoice = draft(client, world)
    result = save(
        client,
        invoice,
        payload(
            invoice,
            supplier_id=supplier_id,
            document_type=document_type,
            related_invoice_id=related_invoice_id,
            items=[item(project_budget_line_id=line_id)],
        ),
    )
    assert result.status_code == 200, result.text
    invoice = act(client, result.json()).json()
    if target == "PROJECT_REVIEW":
        return invoice
    login(client, world, "manager")
    invoice = act(client, invoice, "APPROVE").json()
    if target == "FINANCE_REVIEW":
        return invoice
    login(client, world, "finance")
    return act(client, invoice, "APPROVE").json()


def test_categories_are_company_scoped_finance_managed_and_audited(client, world):
    login(client, world, "finance")
    category = create_category(client, "lab", "عمالة")
    assert category["code"] == "LAB"
    assert (
        client.post("/api/v1/expense-categories", json={"code": "LAB", "name": "مكرر"}).status_code
        == 409
    )

    login(client, world, "employee")
    assert client.get("/api/v1/expense-categories").json()[0]["name"] == "عمالة"
    assert (
        client.post("/api/v1/expense-categories", json={"code": "EQP", "name": "معدات"}).status_code
        == 403
    )
    login(client, world, "outsider")
    assert client.get("/api/v1/expense-categories").json() == []

    with Session(world["admin_engine"]) as db:
        event = db.scalar(
            select(BudgetAuditLog).where(BudgetAuditLog.action == "EXPENSE_CATEGORY_CREATED")
        )
        assert event.details["category"]["code"] == "LAB"
        try:
            db.execute(
                update(BudgetAuditLog).where(BudgetAuditLog.id == event.id).values(action="CHANGED")
            )
            db.commit()
        except DBAPIError:
            db.rollback()
        else:
            raise AssertionError("Budget audit log accepted a forbidden update")


def test_budget_validation_permissions_scope_and_optimistic_revision(client, world):
    category, created = create_budget(client, world)
    project_id = world["projects"]["a"].id
    budget = created["budget"]
    assert budget["revision"] == 1
    assert budget["allocated_amount"] == "500.00"
    assert budget["unallocated_reserve"] == "500.00"

    invalid = budget_payload(category, total="499.99")
    invalid["revision"] = budget["revision"]
    assert client.put(f"/api/v1/projects/{project_id}/budgets/SAR", json=invalid).status_code == 422

    stale = budget_payload(category, revision=0)
    assert client.put(f"/api/v1/projects/{project_id}/budgets/SAR", json=stale).status_code == 409

    for actor in ("employee", "manager"):
        login(client, world, actor)
        view = client.get(f"/api/v1/projects/{project_id}/budgets/SAR")
        assert view.status_code == 200 and view.json()["budget"]["revision"] == 1
        assert (
            client.put(
                f"/api/v1/projects/{project_id}/budgets/SAR",
                json=budget_payload(category, revision=1),
            ).status_code
            == 403
        )
    login(client, world, "manager_b")
    assert client.get(f"/api/v1/projects/{project_id}/budgets/SAR").status_code == 404
    login(client, world, "outsider")
    assert client.get(f"/api/v1/projects/{project_id}/budgets/SAR").status_code == 404


def test_existing_budget_line_identity_is_preserved_and_removed_lines_are_archived(client, world):
    category, created = create_budget(client, world)
    project_id = world["projects"]["a"].id
    old_line = created["budget"]["lines"][0]
    second = create_category(client, "SUB", "مقاولون")
    replacement = budget_payload(
        category,
        revision=created["budget"]["revision"],
        lines=[
            {
                "expense_category_id": second["id"],
                "description": "أعمال مقاول الباطن",
                "unit": None,
                "planned_quantity": None,
                "planned_unit_price": None,
                "allocated_amount": "400.00",
            }
        ],
    )
    updated = client.put(f"/api/v1/projects/{project_id}/budgets/SAR", json=replacement).json()[
        "budget"
    ]
    assert updated["revision"] == 2
    assert updated["lines"][0]["expense_category"]["code"] == "SUB"
    assert updated["archived_lines"][0]["id"] == old_line["id"]


def test_invoice_items_link_to_same_project_currency_budget_and_audit_explains_capacity(
    client, world
):
    _, created = create_budget(client, world, total="200.00")
    line_id = created["budget"]["lines"][0]["id"]
    login(client, world)
    supplier = client.post("/api/v1/suppliers", json={"name": "Budget supplier"}).json()
    invoice = draft(client, world)
    result = save(
        client,
        invoice,
        payload(
            invoice,
            supplier_id=supplier["id"],
            items=[item(project_budget_line_id=line_id)],
        ),
    )
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved["items"][0]["budget_line"]["category"]["code"] == "MAT"
    checks = {check["code"]: check for check in saved["audit"]["checks"]}
    assert checks["PROJECT_BUDGET_RELEVANCE"]["status"] == "PASS"
    assert checks["PROJECT_BUDGET_CAPACITY"]["status"] == "WARNING"
    assert (
        checks["PROJECT_BUDGET_CAPACITY"]["budget_analysis"]["remaining_after_document"] == "-18.50"
    )

    wrong_currency = payload(saved, currency="USD", supplier_id=supplier["id"])
    wrong_currency["items"] = [item(project_budget_line_id=line_id)]
    response = save(client, saved, wrong_currency)
    assert response.status_code == 422
    assert "مشروع الفاتورة وعملتها" in response.json()["detail"]


def test_budget_usage_counts_each_workflow_bucket_once(client, world):
    _, created = create_budget(client, world, total="1000.00")
    line_id = created["budget"]["lines"][0]["id"]
    login(client, world)
    supplier = client.post("/api/v1/suppliers", json={"name": "Usage supplier"}).json()
    documents = {
        status: create_invoice_at(client, world, supplier["id"], line_id, status)
        for status in ("PROJECT_REVIEW", "FINANCE_REVIEW", "APPROVED")
    }
    create_invoice_at(
        client,
        world,
        supplier["id"],
        line_id,
        "PROJECT_REVIEW",
        document_type="CREDIT_NOTE",
        related_invoice_id=documents["APPROVED"]["id"],
    )

    login(client, world, "finance")
    result = client.get(f"/api/v1/projects/{world['projects']['a'].id}/budgets/SAR").json()[
        "budget"
    ]
    assert result["usage"] == {
        "approved": "218.50",
        "committed": "218.50",
        "pending": "0.00",
        "exposure": "437.00",
        "remaining": "563.00",
    }
    assert result["lines"][0]["usage"]["exposure"] == "437.00"
    with Session(world["admin_engine"]) as db:
        assert db.scalar(select(func.count()).select_from(BudgetAuditLog)) == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(BudgetAuditLog)
                .where(BudgetAuditLog.action == "PROJECT_BUDGET_CREATED")
            )
            == 1
        )
