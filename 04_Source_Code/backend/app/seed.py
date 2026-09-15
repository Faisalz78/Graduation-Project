"""Idempotent local demo accounts. Run: python -m app.seed"""

import json
from decimal import Decimal

from dotenv import dotenv_values
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import ROOT
from app.core.security import passwords
from app.models import (
    ApprovalLimit,
    BudgetAuditLog,
    Company,
    ExpenseCategory,
    Project,
    ProjectBudget,
    ProjectBudgetLine,
    ProjectMember,
    User,
)


def main():
    state = json.loads((ROOT / ".local/runtime.json").read_text(encoding="utf-8"))
    values = dotenv_values(ROOT / ".env")
    engine = create_engine(values["MIGRATION_DATABASE_URL"])
    accounts = [
        ("employee@demo.test", "موظف المشتريات", "EMPLOYEE", (0, 1)),
        ("employee2@demo.test", "موظف آخر", "EMPLOYEE", (0,)),
        ("manager@demo.test", "مدير المشروع", "PROJECT_MANAGER", (0,)),
        ("manager2@demo.test", "مدير المستودع", "PROJECT_MANAGER", (1,)),
        ("finance@demo.test", "مدير المالية", "FINANCE_MANAGER", ()),
        ("finance2@demo.test", "مدير مالية ثانٍ", "FINANCE_MANAGER", ()),
    ]
    with Session(engine) as db:
        company = db.scalar(select(Company).where(Company.name == "شركة المشاريع التجريبية"))
        if not company:
            company = Company(name="شركة المشاريع التجريبية")
            db.add(company)
            db.flush()
        projects = []
        for name, code in [
            ("تطوير المقر الرئيسي", "PRJ-001"),
            ("تجهيز مستودع العمليات", "PRJ-002"),
        ]:
            project = db.scalar(
                select(Project).where(Project.company_id == company.id, Project.code == code)
            )
            if not project:
                project = Project(company_id=company.id, name=name, code=code)
                db.add(project)
                db.flush()
            projects.append(project)
        users = {}
        for email, name, role, memberships in accounts:
            user = db.scalar(select(User).where(User.email == email))
            if not user:
                user = User(
                    company_id=company.id,
                    email=email,
                    name=name,
                    role=role,
                    password_hash=passwords.hash(state["demo_password"]),
                )
                db.add(user)
                db.flush()
            users[email] = user
            for index in memberships:
                if not db.get(ProjectMember, (projects[index].id, user.id)):
                    db.add(
                        ProjectMember(
                            project_id=projects[index].id,
                            user_id=user.id,
                            membership_role="MANAGER" if role == "PROJECT_MANAGER" else "MEMBER",
                        )
                    )
        default_limits = {
            "manager@demo.test": "100000.00",
            "manager2@demo.test": "100000.00",
            "finance@demo.test": "500000.00",
            "finance2@demo.test": "1000000.00",
        }
        for email, amount in default_limits.items():
            reviewer = users[email]
            for currency in ("SAR", "AED", "USD", "EUR"):
                exists = db.scalar(
                    select(ApprovalLimit).where(
                        ApprovalLimit.user_id == reviewer.id,
                        ApprovalLimit.currency == currency,
                    )
                )
                if not exists:
                    db.add(
                        ApprovalLimit(
                            company_id=company.id,
                            user_id=reviewer.id,
                            currency=currency,
                            amount=Decimal(amount),
                            updated_by=users["finance2@demo.test"].id,
                        )
                    )
        finance = users["finance@demo.test"]
        categories = {}
        for code, name in [
            ("MAT", "مواد المشروع"),
            ("LAB", "العمالة"),
            ("EQP", "المعدات"),
            ("SUB", "مقاولو الباطن"),
        ]:
            category = db.scalar(
                select(ExpenseCategory).where(
                    ExpenseCategory.company_id == company.id,
                    ExpenseCategory.code == code,
                )
            )
            if not category:
                category = ExpenseCategory(
                    company_id=company.id,
                    code=code,
                    name=name,
                    created_by=finance.id,
                )
                db.add(category)
                db.flush()
                db.add(
                    BudgetAuditLog(
                        company_id=company.id,
                        project_id=None,
                        actor_id=finance.id,
                        action="EXPENSE_CATEGORY_CREATED",
                        details={
                            "source": "DEMO_SEED",
                            "category": {"id": str(category.id), "code": code, "name": name},
                        },
                    )
                )
            categories[code] = category
        for project in projects:
            budget = db.scalar(
                select(ProjectBudget).where(
                    ProjectBudget.project_id == project.id,
                    ProjectBudget.currency == "SAR",
                )
            )
            if budget:
                continue
            budget = ProjectBudget(
                company_id=company.id,
                project_id=project.id,
                currency="SAR",
                total_amount=Decimal("1000000.00"),
                updated_by=finance.id,
            )
            db.add(budget)
            db.flush()
            demo_lines = [
                ("MAT", "توريد مواد المشروع", "500000.00"),
                ("LAB", "تكلفة العمالة", "200000.00"),
                ("EQP", "استئجار وتشغيل المعدات", "150000.00"),
                ("SUB", "أعمال مقاولي الباطن", "100000.00"),
            ]
            for position, (code, description, allocation) in enumerate(demo_lines, 1):
                db.add(
                    ProjectBudgetLine(
                        project_budget_id=budget.id,
                        expense_category_id=categories[code].id,
                        position=position,
                        description=description,
                        allocated_amount=Decimal(allocation),
                    )
                )
            db.add(
                BudgetAuditLog(
                    company_id=company.id,
                    project_id=project.id,
                    actor_id=finance.id,
                    action="PROJECT_BUDGET_CREATED",
                    details={
                        "source": "DEMO_SEED",
                        "currency": "SAR",
                        "total_amount": "1000000.00",
                    },
                )
            )
        db.commit()
    text = "# حسابات التجربة المحلية\n\nهذه بيانات تطوير محلية. افتح http://127.0.0.1:3000 وسجل الدخول.\n\n"
    text += "| الحساب | الدور |\n|---|---|\n" + "\n".join(
        f"| {email} | {name} |" for email, name, _, _ in accounts
    )
    text += f"\n\nكلمة المرور للحسابات التجريبية:\n\n`{state['demo_password']}`\n\nالمديرون لا يرون المسودات الخاصة؛ الإرسال والمراجعة يأتيان في الجزء التالي.\n"
    (ROOT / ".local/DEMO_ACCOUNTS.md").write_text(text, encoding="utf-8")
    print("Demo accounts prepared. Open .local/DEMO_ACCOUNTS.md for local credentials.")


if __name__ == "__main__":
    main()
