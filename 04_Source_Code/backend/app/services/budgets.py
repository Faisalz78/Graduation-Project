import uuid
from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    BudgetAuditLog,
    ExpenseCategory,
    Invoice,
    InvoiceItem,
    Project,
    ProjectBudget,
    ProjectBudgetLine,
    ProjectMember,
    utcnow,
)
from app.schemas.budgets import ExpenseCategoryInput, ProjectBudgetInput

COUNTED_STATUSES = ("PROJECT_REVIEW", "FINANCE_REVIEW", "CHANGES_REQUESTED", "APPROVED")
PENDING_STATUSES = ("PROJECT_REVIEW", "CHANGES_REQUESTED")


def money(value):
    return format(value or Decimal("0"), ".2f")


def signed_amount(document_type, value):
    amount = value or Decimal("0")
    return -amount if document_type == "CREDIT_NOTE" else amount


def require_project_scope(db, user, project_id: uuid.UUID):
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.company_id == user.company_id,
            Project.is_active.is_(True),
        )
    )
    if not project:
        raise HTTPException(404, "المشروع غير موجود أو غير متاح لك.")
    if user.role == "FINANCE_MANAGER":
        return project
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        )
    )
    if not membership or (
        user.role == "PROJECT_MANAGER" and membership.membership_role != "MANAGER"
    ):
        raise HTTPException(404, "المشروع غير موجود أو غير متاح لك.")
    return project


def category_data(category):
    return {
        "id": category.id,
        "code": category.code,
        "name": category.name,
        "is_active": category.is_active,
    }


def list_categories(db, user):
    return [
        category_data(category)
        for category in db.scalars(
            select(ExpenseCategory)
            .where(
                ExpenseCategory.company_id == user.company_id,
                ExpenseCategory.is_active.is_(True),
            )
            .order_by(ExpenseCategory.code, ExpenseCategory.id)
        )
    ]


def create_category(db, user, data: ExpenseCategoryInput):
    if user.role != "FINANCE_MANAGER":
        raise HTTPException(403, "إدارة فئات المصروفات متاحة لمدير المالية فقط.")
    existing = db.scalar(
        select(ExpenseCategory).where(
            ExpenseCategory.company_id == user.company_id,
            ExpenseCategory.code == data.code,
        )
    )
    if existing:
        raise HTTPException(409, "رمز فئة المصروف مستخدم داخل الشركة.")
    category = ExpenseCategory(
        company_id=user.company_id,
        code=data.code,
        name=data.name,
        created_by=user.id,
    )
    db.add(category)
    db.flush()
    db.add(
        BudgetAuditLog(
            company_id=user.company_id,
            project_id=None,
            actor_id=user.id,
            action="EXPENSE_CATEGORY_CREATED",
            details={"category": {**category_data(category), "id": str(category.id)}},
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "رمز فئة المصروف مستخدم داخل الشركة.") from None
    return category_data(category)


def budget_config(db, budget):
    if not budget:
        return None
    categories = {
        category.id: category
        for category in db.scalars(
            select(ExpenseCategory).where(ExpenseCategory.company_id == budget.company_id)
        )
    }
    lines = list(
        db.scalars(
            select(ProjectBudgetLine)
            .where(ProjectBudgetLine.project_budget_id == budget.id)
            .order_by(ProjectBudgetLine.position, ProjectBudgetLine.id)
        )
    )
    return {
        "id": budget.id,
        "revision": budget.revision,
        "total_amount": money(budget.total_amount),
        "allocated_amount": money(
            sum(
                (line.allocated_amount for line in lines if line.is_active),
                Decimal("0"),
            )
        ),
        "lines": [
            {
                "id": line.id,
                "position": line.position,
                "expense_category": category_data(categories[line.expense_category_id]),
                "description": line.description,
                "unit": line.unit,
                "planned_quantity": (
                    format(line.planned_quantity, ".4f")
                    if line.planned_quantity is not None
                    else None
                ),
                "planned_unit_price": (
                    format(line.planned_unit_price, ".4f")
                    if line.planned_unit_price is not None
                    else None
                ),
                "allocated_amount": money(line.allocated_amount),
                "is_active": line.is_active,
            }
            for line in lines
        ],
    }


def _empty_usage():
    return {
        "approved": Decimal("0"),
        "committed": Decimal("0"),
        "pending": Decimal("0"),
    }


def _add_usage(usage, status, value):
    if status == "APPROVED":
        usage["approved"] += value
    elif status == "FINANCE_REVIEW":
        usage["committed"] += value
    elif status in PENDING_STATUSES:
        usage["pending"] += value


def _format_usage(usage, allocation):
    exposure = usage["approved"] + usage["committed"] + usage["pending"]
    return {
        "approved": money(usage["approved"]),
        "committed": money(usage["committed"]),
        "pending": money(usage["pending"]),
        "exposure": money(exposure),
        "remaining": money(allocation - exposure),
    }


def budget_view(db, user, project_id, currency):
    project = require_project_scope(db, user, project_id)
    budget = db.scalar(
        select(ProjectBudget).where(
            ProjectBudget.project_id == project.id,
            ProjectBudget.currency == currency,
        )
    )
    result = {
        "project": {"id": project.id, "name": project.name, "code": project.code},
        "currency": currency,
        "budget": None,
        "definitions": {
            "approved": "مستندات اعتمدتها المالية.",
            "committed": "مستندات وافق عليها مدير المشروع وتنتظر المالية.",
            "pending": "مستندات تنتظر مراجعة المشروع أو أُعيدت للتعديل بعد إرسالها.",
            "excluded": "المسودات والمستندات المرفوضة لا تدخل في الاستخدام.",
            "currency": "كل عملة تحسب في ميزانية مستقلة دون تحويل تلقائي.",
        },
    }
    if not budget:
        return result

    config = budget_config(db, budget)
    overall = _empty_usage()
    invoices = list(
        db.scalars(
            select(Invoice).where(
                Invoice.project_id == project.id,
                Invoice.company_id == user.company_id,
                Invoice.currency == currency,
                Invoice.status.in_(COUNTED_STATUSES),
            )
        )
    )
    for invoice in invoices:
        _add_usage(
            overall, invoice.status, signed_amount(invoice.document_type, invoice.grand_total)
        )

    line_usage = defaultdict(_empty_usage)
    rows = db.execute(
        select(
            InvoiceItem.project_budget_line_id,
            Invoice.status,
            Invoice.document_type,
            InvoiceItem.total_amount,
        )
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(
            Invoice.company_id == user.company_id,
            Invoice.project_id == project.id,
            Invoice.currency == currency,
            Invoice.status.in_(COUNTED_STATUSES),
            InvoiceItem.project_budget_line_id.is_not(None),
        )
    )
    for line_id, status, document_type, total in rows:
        _add_usage(line_usage[line_id], status, signed_amount(document_type, total))

    active_lines = []
    archived_lines = []
    for line in config["lines"]:
        line["usage"] = _format_usage(line_usage[line["id"]], Decimal(line["allocated_amount"]))
        (active_lines if line["is_active"] else archived_lines).append(line)
    total = Decimal(config["total_amount"])
    allocated = Decimal(config["allocated_amount"])
    result["budget"] = {
        **{key: value for key, value in config.items() if key != "lines"},
        "unallocated_reserve": money(total - allocated),
        "usage": _format_usage(overall, total),
        "lines": active_lines,
        "archived_lines": archived_lines,
        "updated_at": budget.updated_at,
    }
    return result


def save_budget(db, user, project_id, data: ProjectBudgetInput):
    if user.role != "FINANCE_MANAGER":
        raise HTTPException(403, "تعديل ميزانية المشروع متاح لمدير المالية فقط.")
    project = require_project_scope(db, user, project_id)
    budget = db.scalar(
        select(ProjectBudget)
        .where(
            ProjectBudget.project_id == project.id,
            ProjectBudget.currency == data.currency,
        )
        .with_for_update()
    )
    if budget is None:
        if data.revision != 0:
            raise HTTPException(409, "لم تُنشأ الميزانية بعد. حدّث الصفحة وحاول مجددًا.")
        budget = ProjectBudget(
            company_id=user.company_id,
            project_id=project.id,
            currency=data.currency,
            total_amount=data.total_amount,
            revision=1,
            updated_by=user.id,
        )
        db.add(budget)
        db.flush()
        before = None
    else:
        if budget.revision != data.revision:
            raise HTTPException(409, "حُفظت نسخة أحدث من الميزانية. حدّث الصفحة قبل إعادة المحاولة.")
        before = budget_config(db, budget)
        budget.total_amount = data.total_amount
        budget.revision += 1
        budget.updated_by = user.id
        budget.updated_at = utcnow()

    category_ids = {line.expense_category_id for line in data.lines}
    valid_category_ids = set(
        db.scalars(
            select(ExpenseCategory.id).where(
                ExpenseCategory.company_id == user.company_id,
                ExpenseCategory.is_active.is_(True),
                ExpenseCategory.id.in_(category_ids),
            )
        )
    )
    if valid_category_ids != category_ids:
        raise HTTPException(422, "تتضمن الميزانية فئة مصروف غير صالحة لهذه الشركة.")

    current_lines = {
        line.id: line
        for line in db.scalars(
            select(ProjectBudgetLine)
            .where(ProjectBudgetLine.project_budget_id == budget.id)
            .with_for_update()
        )
    }
    supplied_ids = {line.id for line in data.lines if line.id}
    if not supplied_ids.issubset(current_lines):
        raise HTTPException(422, "تتضمن الميزانية بندًا لا يخص النسخة الحالية.")
    for line in current_lines.values():
        line.is_active = line.id in supplied_ids
    for position, source in enumerate(data.lines, 1):
        line = current_lines.get(source.id) if source.id else None
        if line is None:
            line = ProjectBudgetLine(project_budget_id=budget.id)
            db.add(line)
        line.expense_category_id = source.expense_category_id
        line.position = position
        line.description = source.description
        line.unit = source.unit
        line.planned_quantity = source.planned_quantity
        line.planned_unit_price = source.planned_unit_price
        line.allocated_amount = source.allocated_amount
        line.is_active = True
    db.flush()
    after = budget_config(db, budget)
    db.add(
        BudgetAuditLog(
            company_id=user.company_id,
            project_id=project.id,
            actor_id=user.id,
            action="PROJECT_BUDGET_CREATED" if before is None else "PROJECT_BUDGET_UPDATED",
            details=jsonable_encoder({"currency": data.currency, "before": before, "after": after}),
        )
    )
    db.commit()
    return budget_view(db, user, project.id, data.currency)
