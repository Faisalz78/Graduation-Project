from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from app.models import AuditLog, Invoice, Project, ProjectMember, utcnow
from app.services.financial_audit import risk_assessment, split_invoice_check
from app.services.invoices import visible_invoices

STATUSES = (
    "DRAFT",
    "PROJECT_REVIEW",
    "FINANCE_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "REJECTED",
)
REVIEW_STATUSES = ("PROJECT_REVIEW", "FINANCE_REVIEW")


def accessible_projects(db, user):
    query = select(Project).where(
        Project.company_id == user.company_id,
        Project.is_active.is_(True),
    )
    if user.role == "PROJECT_MANAGER":
        query = query.join(ProjectMember).where(
            ProjectMember.user_id == user.id,
            ProjectMember.membership_role == "MANAGER",
        )
    return list(db.scalars(query.order_by(Project.name, Project.id)))


def signed_total(invoice):
    value = invoice.grand_total or Decimal("0")
    return -value if invoice.document_type == "CREDIT_NOTE" else value


def money(value):
    return format(value, ".2f")


def month_keys(count=6):
    current = date.today().replace(day=1)
    result = []
    for distance in range(count - 1, -1, -1):
        index = current.year * 12 + current.month - 1 - distance
        year, month = divmod(index, 12)
        result.append(f"{year:04d}-{month + 1:02d}")
    return result


def dashboard_data(db, user, currency, project_id=None):
    if user.role not in {"PROJECT_MANAGER", "FINANCE_MANAGER"}:
        raise HTTPException(403, "اللوحة المالية متاحة لمدير المشروع ومدير المالية فقط.")

    projects = accessible_projects(db, user)
    projects_by_id = {project.id: project for project in projects}
    if project_id and project_id not in projects_by_id:
        raise HTTPException(404, "المشروع غير موجود أو غير متاح لك.")

    query = visible_invoices(user).where(Invoice.currency == currency)
    if project_id:
        query = query.where(Invoice.project_id == project_id)
    invoices = list(db.scalars(query.order_by(Invoice.created_at.desc(), Invoice.id)))

    status_counts = {status: 0 for status in STATUSES}
    approved_net = Decimal("0")
    review_net = Decimal("0")
    approved_count = 0
    review_count = 0
    project_values = {
        project.id: {
            "project": {"id": project.id, "name": project.name, "code": project.code},
            "document_count": 0,
            "approved_net": Decimal("0"),
            "under_review_net": Decimal("0"),
            "exception_count": 0,
        }
        for project in projects
        if project_id is None or project.id == project_id
    }
    supplier_values = defaultdict(lambda: {"approved_net": Decimal("0"), "document_count": 0})
    monthly_values = {key: Decimal("0") for key in month_keys()}
    exceptions = []
    review_ids = [invoice.id for invoice in invoices if invoice.status in REVIEW_STATUSES]
    audit_snapshots = {}
    if review_ids:
        events = db.scalars(
            select(AuditLog)
            .where(
                AuditLog.company_id == user.company_id,
                AuditLog.invoice_id.in_(review_ids),
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        )
        for event in events:
            if event.invoice_id in audit_snapshots:
                continue
            snapshot = (event.details or {}).get("audit_snapshot")
            if isinstance(snapshot, dict) and isinstance(snapshot.get("checks"), list):
                audit_snapshots[event.invoice_id] = snapshot

    for invoice in invoices:
        status_counts[invoice.status] += 1
        value = signed_total(invoice)
        project_row = project_values[invoice.project_id]
        project_row["document_count"] += 1
        if invoice.status == "APPROVED":
            approved_net += value
            approved_count += 1
            project_row["approved_net"] += value
            supplier_name = (invoice.supplier_snapshot or {}).get("name") or "مورد غير محدد"
            supplier_values[supplier_name]["approved_net"] += value
            supplier_values[supplier_name]["document_count"] += 1
            if invoice.invoice_date:
                key = invoice.invoice_date.strftime("%Y-%m")
                if key in monthly_values:
                    monthly_values[key] += value
        elif invoice.status in REVIEW_STATUSES:
            review_net += value
            review_count += 1
            project_row["under_review_net"] += value
            snapshot = audit_snapshots.get(invoice.id, {})
            checks = [
                check
                for check in snapshot.get("checks", [])
                if isinstance(check, dict) and check.get("code") != "SPLIT_INVOICE"
            ]
            checks.append(split_invoice_check(db, invoice))
            risk = risk_assessment(checks)
            if risk["score"] > 0:
                project_row["exception_count"] += 1
                top_factor = risk["factors"][0]
                exceptions.append(
                    {
                        "invoice_id": invoice.id,
                        "invoice_number": invoice.invoice_number,
                        "project": project_row["project"],
                        "supplier_name": (invoice.supplier_snapshot or {}).get("name"),
                        "status": invoice.status,
                        "document_type": invoice.document_type,
                        "grand_total": money(invoice.grand_total or Decimal("0")),
                        "risk": risk,
                        "top_reason": top_factor["label"],
                    }
                )

    exceptions.sort(key=lambda item: (-item["risk"]["score"], str(item["invoice_id"])))
    project_rows = [
        {
            **row,
            "approved_net": money(row["approved_net"]),
            "under_review_net": money(row["under_review_net"]),
        }
        for row in project_values.values()
    ]
    project_rows.sort(
        key=lambda row: (
            -(abs(Decimal(row["approved_net"])) + abs(Decimal(row["under_review_net"]))),
            row["project"]["name"],
        )
    )
    supplier_rows = [
        {**row, "supplier_name": name, "approved_net": money(row["approved_net"])}
        for name, row in supplier_values.items()
    ]
    supplier_rows.sort(key=lambda row: (-abs(Decimal(row["approved_net"])), row["supplier_name"]))

    return {
        "generated_at": utcnow(),
        "currency": currency,
        "project_id": project_id,
        "projects": [
            {"id": project.id, "name": project.name, "code": project.code} for project in projects
        ],
        "summary": {
            "document_count": len(invoices),
            "approved_document_count": approved_count,
            "under_review_document_count": review_count,
            "approved_net": money(approved_net),
            "under_review_net": money(review_net),
            "exception_count": len(exceptions),
            "high_risk_count": sum(item["risk"]["level"] == "HIGH" for item in exceptions),
        },
        "status_counts": status_counts,
        "monthly_approved_net": [
            {"month": key, "amount": money(value)} for key, value in monthly_values.items()
        ],
        "project_breakdown": project_rows,
        "supplier_breakdown": supplier_rows[:6],
        "exception_queue": exceptions[:10],
        "definitions": {
            "approved_net": "الفواتير والإشعارات المعتمدة: الأصل + المدين − الدائن.",
            "under_review_net": "المستندات في مراجعة المشروع أو المالية بالقيمة الصافية نفسها.",
            "exception_queue": "مستندات المراجعة التي تحمل عامل مخاطر واحدًا على الأقل.",
            "currency": "كل عملة تعرض منفصلة دون تحويل تلقائي.",
        },
    }
