import csv
import io
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from app.models import AuditLog, Invoice, Project, ProjectBudget, User
from app.services.analytics import accessible_projects, signed_total
from app.services.budgets import budget_view
from app.services.financial_intelligence import regional_price_check
from app.services.invoices import visible_invoices

REPORT_INVOICE_LIMIT = 5000
REGIONAL_REPORT_INVOICE_LIMIT = 500
STATUS_LABELS = {
    "DRAFT": "مسودة",
    "PROJECT_REVIEW": "مراجعة المشروع",
    "FINANCE_REVIEW": "مراجعة المالية",
    "CHANGES_REQUESTED": "مطلوب تعديل",
    "APPROVED": "معتمد",
    "REJECTED": "مرفوض",
}
DOCUMENT_LABELS = {
    "INVOICE": "فاتورة",
    "CREDIT_NOTE": "إشعار دائن",
    "DEBIT_NOTE": "إشعار مدين",
}
CHECK_LABELS = {
    "PASS": "ضمن السياسة",
    "WARNING": "يحتاج مراجعة",
    "NOT_CHECKED": "بيانات غير كافية",
}
RISK_LABELS = {"LOW": "منخفضة", "MEDIUM": "متوسطة", "HIGH": "مرتفعة"}


def require_report_role(user):
    if user.role not in {"PROJECT_MANAGER", "FINANCE_MANAGER"}:
        raise HTTPException(403, "التقارير متاحة لمدير المشروع ومدير المالية فقط.")


def project_scope(db, user, project_id=None):
    require_report_role(user)
    projects = accessible_projects(db, user)
    by_id = {project.id: project for project in projects}
    if project_id and project_id not in by_id:
        raise HTTPException(404, "المشروع غير موجود أو غير متاح لك.")
    return [by_id[project_id]] if project_id else projects


def filtered_invoices(
    db,
    user,
    *,
    project_id=None,
    currency=None,
    status=None,
    date_from=None,
    date_to=None,
    limit=REPORT_INVOICE_LIMIT,
):
    project_scope(db, user, project_id)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "تاريخ البداية يجب ألا يتجاوز تاريخ النهاية.")
    query = visible_invoices(user)
    if project_id:
        query = query.where(Invoice.project_id == project_id)
    if currency:
        query = query.where(Invoice.currency == currency)
    if status:
        query = query.where(Invoice.status == status)
    if date_from:
        query = query.where(Invoice.invoice_date >= date_from)
    if date_to:
        query = query.where(Invoice.invoice_date <= date_to)
    invoices = list(db.scalars(query.order_by(Invoice.invoice_date.desc().nullslast(), Invoice.id)))
    if len(invoices) > limit:
        raise HTTPException(422, f"النتيجة تتجاوز {limit} مستندًا. ضيق المرشحات ثم أعد التصدير.")
    return invoices


def safe_csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, (int, Decimal)):
        return str(value)
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def csv_bytes(headers, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(safe_csv_cell(value) for value in row)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def latest_audit_snapshots(db, user, invoice_ids):
    snapshots = {}
    if not invoice_ids:
        return snapshots
    events = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.company_id == user.company_id,
            AuditLog.invoice_id.in_(invoice_ids),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    for event in events:
        if event.invoice_id in snapshots:
            continue
        snapshot = (event.details or {}).get("audit_snapshot")
        if isinstance(snapshot, dict):
            snapshots[event.invoice_id] = snapshot
    return snapshots


def invoice_register_csv(db, user, **filters):
    invoices = filtered_invoices(db, user, **filters)
    projects = {
        project.id: project
        for project in db.scalars(
            select(Project).where(Project.id.in_([invoice.project_id for invoice in invoices]))
        )
    }
    users = {
        item.id: item
        for item in db.scalars(
            select(User).where(User.id.in_([invoice.created_by for invoice in invoices]))
        )
    }
    snapshots = latest_audit_snapshots(db, user, [invoice.id for invoice in invoices])
    rows = []
    for invoice in invoices:
        project = projects[invoice.project_id]
        creator = users[invoice.created_by]
        supplier = invoice.supplier_snapshot or {}
        risk = snapshots.get(invoice.id, {}).get("risk", {})
        rows.append(
            (
                invoice.invoice_number,
                DOCUMENT_LABELS[invoice.document_type],
                STATUS_LABELS[invoice.status],
                project.code,
                project.name,
                supplier.get("name"),
                supplier.get("region_code"),
                invoice.invoice_date,
                invoice.currency,
                invoice.subtotal,
                invoice.discount_total,
                invoice.tax_total,
                invoice.grand_total,
                signed_total(invoice),
                risk.get("score"),
                RISK_LABELS.get(risk.get("level")),
                risk.get("warning_count"),
                creator.name,
                invoice.created_at.isoformat(),
                invoice.submitted_at.isoformat() if invoice.submitted_at else None,
            )
        )
    return csv_bytes(
        (
            "رقم المستند",
            "نوع المستند",
            "الحالة",
            "رمز المشروع",
            "المشروع",
            "المورد",
            "رمز منطقة المورد",
            "تاريخ المستند",
            "العملة",
            "الإجمالي قبل الخصم",
            "الخصم",
            "الضريبة",
            "الإجمالي",
            "الأثر الصافي",
            "درجة آخر قرار",
            "مستوى أولوية آخر قرار",
            "تحذيرات آخر قرار",
            "منشئ المستند",
            "وقت الإنشاء UTC",
            "وقت الإرسال UTC",
        ),
        rows,
    )


def project_budgets_csv(db, user, *, project_id=None, currency=None):
    projects = project_scope(db, user, project_id)
    project_ids = [project.id for project in projects]
    query = select(ProjectBudget).where(ProjectBudget.project_id.in_(project_ids))
    if currency:
        query = query.where(ProjectBudget.currency == currency)
    budgets = list(db.scalars(query.order_by(ProjectBudget.currency, ProjectBudget.project_id)))
    rows = []
    for budget in budgets:
        data = budget_view(db, user, budget.project_id, budget.currency)
        summary = data["budget"]
        rows.append(
            (
                data["project"]["code"],
                data["project"]["name"],
                data["currency"],
                Decimal(summary["total_amount"]),
                Decimal(summary["allocated_amount"]),
                Decimal(summary["unallocated_reserve"]),
                Decimal(summary["usage"]["approved"]),
                Decimal(summary["usage"]["committed"]),
                Decimal(summary["usage"]["pending"]),
                Decimal(summary["usage"]["exposure"]),
                Decimal(summary["usage"]["remaining"]),
                len(summary["lines"]),
                summary["updated_at"].isoformat(),
            )
        )
    return csv_bytes(
        (
            "رمز المشروع",
            "المشروع",
            "العملة",
            "إجمالي الميزانية",
            "المخصص للبنود",
            "الاحتياطي غير الموزع",
            "المعتمد",
            "الملتزم",
            "قيد المراجعة",
            "الاستخدام",
            "المتبقي",
            "عدد البنود النشطة",
            "آخر تحديث UTC",
        ),
        rows,
    )


def regional_prices_csv(db, user, **filters):
    invoices = filtered_invoices(db, user, limit=REGIONAL_REPORT_INVOICE_LIMIT, **filters)
    projects = {
        project.id: project
        for project in db.scalars(
            select(Project).where(Project.id.in_([invoice.project_id for invoice in invoices]))
        )
    }
    rows = []
    for invoice in invoices:
        check = regional_price_check(db, invoice)
        supplier = invoice.supplier_snapshot or {}
        for finding in check.get("regional_findings", []):
            comparison_rows = finding["region_comparisons"] or [None]
            for comparison in comparison_rows:
                rows.append(
                    (
                        invoice.invoice_number,
                        invoice.invoice_date,
                        projects[invoice.project_id].code,
                        projects[invoice.project_id].name,
                        supplier.get("name"),
                        finding["current_region_name"],
                        finding["position"],
                        finding["description"],
                        finding["unit"],
                        Decimal(finding["current_unit_price"])
                        if finding["current_unit_price"] is not None
                        else None,
                        Decimal(finding["current_region_median"])
                        if finding["current_region_median"] is not None
                        else None,
                        Decimal(finding["difference_percent"])
                        if finding["difference_percent"] is not None
                        else None,
                        Decimal(finding["potential_saving"])
                        if finding["potential_saving"] is not None
                        else None,
                        CHECK_LABELS[finding["status"]],
                        finding["confidence"],
                        finding["sample_count"],
                        finding["supplier_count"],
                        finding["region_count"],
                        comparison["region_name"] if comparison else None,
                        Decimal(comparison["median_unit_price"]) if comparison else None,
                        comparison["invoice_count"] if comparison else None,
                        comparison["supplier_count"] if comparison else None,
                    )
                )
    return csv_bytes(
        (
            "رقم الفاتورة",
            "تاريخ الفاتورة",
            "رمز المشروع",
            "المشروع",
            "المورد الحالي",
            "منطقة المورد الحالية",
            "رقم البند",
            "وصف البند",
            "الوحدة",
            "السعر الحالي",
            "وسيط المنطقة الحالية",
            "فرق السعر %",
            "فرق تكلفة الكمية",
            "النتيجة",
            "الموثوقية",
            "عدد الفواتير المرجعية",
            "عدد الموردين",
            "عدد المناطق",
            "منطقة المقارنة",
            "وسيط منطقة المقارنة",
            "فواتير منطقة المقارنة",
            "موردو منطقة المقارنة",
        ),
        rows,
    )
