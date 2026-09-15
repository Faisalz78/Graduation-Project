from sqlalchemy import select, update

from app.models import Notification, Project, ProjectMember, User, utcnow


def _active_project_managers(db, invoice):
    return list(
        db.scalars(
            select(User)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(
                User.company_id == invoice.company_id,
                User.role == "PROJECT_MANAGER",
                User.is_active.is_(True),
                ProjectMember.project_id == invoice.project_id,
                ProjectMember.membership_role == "MANAGER",
            )
            .order_by(User.id)
        )
    )


def _active_finance_managers(db, invoice):
    return list(
        db.scalars(
            select(User)
            .where(
                User.company_id == invoice.company_id,
                User.role == "FINANCE_MANAGER",
                User.is_active.is_(True),
            )
            .order_by(User.id)
        )
    )


def _active_owner(db, invoice):
    return db.scalar(
        select(User).where(
            User.id == invoice.created_by,
            User.company_id == invoice.company_id,
            User.is_active.is_(True),
        )
    )


def add_workflow_notifications(db, actor, invoice, event, audit):
    project = db.get(Project, invoice.project_id)
    project_name = project.name if project else "المشروع"
    invoice_label = invoice.invoice_number or "دون رقم"
    risk = audit.get("risk", {})
    risk_levels = {"LOW": "منخفضة", "MEDIUM": "متوسطة", "HIGH": "مرتفعة"}
    priority = risk_levels.get(risk.get("level"), "غير مكتملة")
    entries = []

    if event in {"INVOICE_SUBMITTED", "INVOICE_RESUBMITTED"}:
        for recipient in _active_project_managers(db, invoice):
            entries.append(
                (
                    recipient,
                    "PROJECT_REVIEW_REQUIRED",
                    "فاتورة بانتظار مراجعة المشروع",
                    f"الفاتورة {invoice_label} في {project_name} بانتظار مراجعتك. "
                    f"أولوية المراجعة {priority}.",
                )
            )
    elif event == "PROJECT_APPROVED":
        for recipient in _active_finance_managers(db, invoice):
            entries.append(
                (
                    recipient,
                    "FINANCE_REVIEW_REQUIRED",
                    "فاتورة بانتظار مراجعة المالية",
                    f"الفاتورة {invoice_label} في {project_name} اعتمدها مدير المشروع "
                    f"وبانتظار المراجعة المالية. أولوية المراجعة {priority}.",
                )
            )
        owner = _active_owner(db, invoice)
        if owner:
            entries.append(
                (
                    owner,
                    "PROJECT_APPROVED",
                    "اعتمد مدير المشروع فاتورتك",
                    f"انتقلت الفاتورة {invoice_label} في {project_name} إلى المراجعة المالية.",
                )
            )
    elif event in {"CHANGES_REQUESTED", "INVOICE_REJECTED", "FINANCE_APPROVED"}:
        owner = _active_owner(db, invoice)
        if owner:
            content = {
                "CHANGES_REQUESTED": (
                    "طُلب تعديل فاتورتك",
                    f"الفاتورة {invoice_label} في {project_name} تحتاج تعديلًا. "
                    "افتحها للاطلاع على سبب المراجع.",
                ),
                "INVOICE_REJECTED": (
                    "رُفضت فاتورتك",
                    f"رُفضت الفاتورة {invoice_label} في {project_name}. "
                    "افتحها للاطلاع على سبب القرار.",
                ),
                "FINANCE_APPROVED": (
                    "اعتمدت المالية فاتورتك",
                    f"اكتملت موافقة الفاتورة {invoice_label} في {project_name}.",
                ),
            }[event]
            entries.append((owner, event, *content))

    for recipient, kind, title, message in entries:
        db.add(
            Notification(
                company_id=invoice.company_id,
                recipient_user_id=recipient.id,
                invoice_id=invoice.id,
                project_id=invoice.project_id,
                kind=kind,
                title=title,
                message=message,
                dedupe_key=f"{invoice.id}:{invoice.revision}:{event}:{kind}",
            )
        )


def notification_result(notification):
    return {
        "id": notification.id,
        "kind": notification.kind,
        "title": notification.title,
        "message": notification.message,
        "invoice_id": notification.invoice_id,
        "project_id": notification.project_id,
        "created_at": notification.created_at,
        "read_at": notification.read_at,
    }


def mark_all_read(db, user):
    changed = db.execute(
        update(Notification)
        .where(
            Notification.company_id == user.company_id,
            Notification.recipient_user_id == user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=utcnow())
    ).rowcount
    db.commit()
    return changed
