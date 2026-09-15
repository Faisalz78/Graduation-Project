import uuid

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.security import passwords
from app.models import (
    AdministrationAuditLog,
    AuthSession,
    Invoice,
    Project,
    ProjectBudget,
    ProjectMember,
    PurchaseOrder,
    User,
    utcnow,
)

EDITABLE_INVOICES = ("DRAFT", "CHANGES_REQUESTED")


def require_finance(user):
    if user.role != "FINANCE_MANAGER":
        raise HTTPException(403, "إدارة المشاريع والمستخدمين متاحة لمدير المالية فقط.")


def member_role(role):
    return "MANAGER" if role == "PROJECT_MANAGER" else "MEMBER"


def user_result(db, user):
    memberships = db.execute(
        select(ProjectMember, Project)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(ProjectMember.user_id == user.id)
        .order_by(Project.name, Project.id)
    ).all()
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "revision": user.revision,
        "updated_at": user.updated_at,
        "memberships": [
            {
                "project": {
                    "id": project.id,
                    "name": project.name,
                    "code": project.code,
                    "is_active": project.is_active,
                },
                "membership_role": membership.membership_role,
            }
            for membership, project in memberships
        ],
    }


def list_users(db, actor):
    require_finance(actor)
    users = db.scalars(
        select(User).where(User.company_id == actor.company_id).order_by(User.name, User.id)
    )
    return [user_result(db, user) for user in users]


def project_result(db, project):
    members = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project.id)
        .order_by(User.role, User.name, User.id)
    ).all()
    return {
        "id": project.id,
        "name": project.name,
        "code": project.code,
        "is_active": project.is_active,
        "revision": project.revision,
        "updated_at": project.updated_at,
        "members": [
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
                "membership_role": membership.membership_role,
            }
            for membership, user in members
        ],
    }


def list_projects(db, actor):
    require_finance(actor)
    projects = db.scalars(
        select(Project)
        .where(Project.company_id == actor.company_id)
        .order_by(Project.name, Project.id)
    )
    return [project_result(db, project) for project in projects]


def audit(db, actor, action, *, target_user=None, target_project=None, details=None):
    db.add(
        AdministrationAuditLog(
            company_id=actor.company_id,
            actor_id=actor.id,
            action=action,
            target_user_id=target_user,
            target_project_id=target_project,
            details=details or {},
        )
    )


def commit_unique(db, message):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, message) from None


def flush_unique(db, message):
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, message) from None


def create_user(db, actor, data):
    require_finance(actor)
    if db.scalar(select(User.id).where(User.email == data.email)):
        raise HTTPException(409, "البريد الإلكتروني مستخدم في حساب آخر.")
    user = User(
        company_id=actor.company_id,
        email=data.email,
        name=data.name,
        password_hash=passwords.hash(data.temporary_password),
        role=data.role,
    )
    db.add(user)
    flush_unique(db, "البريد الإلكتروني مستخدم في حساب آخر.")
    audit(
        db,
        actor,
        "USER_CREATED",
        target_user=user.id,
        details={"name": user.name, "email": user.email, "role": user.role},
    )
    commit_unique(db, "البريد الإلكتروني مستخدم في حساب آخر.")
    return user_result(db, user)


def locked_user(db, actor, user_id: uuid.UUID):
    require_finance(actor)
    user = db.scalar(
        select(User)
        .where(User.id == user_id, User.company_id == actor.company_id)
        .with_for_update()
    )
    if not user:
        raise HTTPException(404, "المستخدم غير موجود أو غير متاح لشركتك.")
    return user


def ensure_user_change_safe(db, target, new_role, new_active):
    losing_employee_access = target.role == "EMPLOYEE" and (
        new_role != "EMPLOYEE" or not new_active
    )
    if losing_employee_access and db.scalar(
        select(func.count())
        .select_from(Invoice)
        .where(Invoice.created_by == target.id, Invoice.status.in_(EDITABLE_INVOICES))
    ):
        raise HTTPException(
            409,
            "لا يمكن تغيير هذا الحساب؛ لديه فواتير مسودة أو مطلوب تعديلها ويجب إكمالها أولًا.",
        )

    losing_manager_access = target.role == "PROJECT_MANAGER" and (
        new_role != "PROJECT_MANAGER" or not new_active
    )
    if not losing_manager_access:
        return
    projects = list(
        db.scalars(
            select(Project.id)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                ProjectMember.user_id == target.id,
                ProjectMember.membership_role == "MANAGER",
                Project.company_id == target.company_id,
            )
        )
    )
    for project_id in projects:
        pending = db.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.project_id == project_id, Invoice.status == "PROJECT_REVIEW")
        )
        other_managers = db.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id != target.id,
                ProjectMember.membership_role == "MANAGER",
                User.role == "PROJECT_MANAGER",
                User.is_active.is_(True),
            )
        )
        if pending and not other_managers:
            raise HTTPException(
                409,
                "لا يمكن تغيير هذا الحساب؛ هو المدير النشط الوحيد لمشروع لديه فواتير قيد المراجعة.",
            )


def update_user(db, actor, user_id, data):
    target = locked_user(db, actor, user_id)
    if target.id == actor.id:
        raise HTTPException(403, "لا يمكنك تعديل دور حسابك أو حالته من هذه الصفحة.")
    if target.revision != data.revision:
        raise HTTPException(409, "تغير الحساب من جلسة أخرى. أعد تحميل الصفحة.")
    if (
        target.role == "FINANCE_MANAGER"
        and target.is_active
        and (data.role != "FINANCE_MANAGER" or not data.is_active)
    ):
        active_finance = db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.company_id == actor.company_id,
                User.role == "FINANCE_MANAGER",
                User.is_active.is_(True),
                User.id != target.id,
            )
        )
        if not active_finance:
            raise HTTPException(409, "لا يمكن تعطيل أو تغيير دور آخر مدير مالية نشط.")
    ensure_user_change_safe(db, target, data.role, data.is_active)
    before = {"name": target.name, "role": target.role, "is_active": target.is_active}
    target.name = data.name
    target.role = data.role
    target.is_active = data.is_active
    target.revision += 1
    target.updated_at = utcnow()
    if target.role == "FINANCE_MANAGER":
        db.execute(delete(ProjectMember).where(ProjectMember.user_id == target.id))
    else:
        db.execute(
            update(ProjectMember)
            .where(ProjectMember.user_id == target.id)
            .values(membership_role=member_role(target.role))
        )
    audit(
        db,
        actor,
        "USER_UPDATED",
        target_user=target.id,
        details={
            "before": before,
            "after": {"name": target.name, "role": target.role, "is_active": target.is_active},
        },
    )
    db.commit()
    return user_result(db, target)


def reset_password(db, actor, user_id, data):
    target = locked_user(db, actor, user_id)
    if target.id == actor.id:
        raise HTTPException(403, "استخدم حساب مدير مالية آخر لإعادة ضبط كلمة مرورك.")
    if target.revision != data.revision:
        raise HTTPException(409, "تغير الحساب من جلسة أخرى. أعد تحميل الصفحة.")
    target.password_hash = passwords.hash(data.temporary_password)
    target.revision += 1
    target.updated_at = utcnow()
    revoked = db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == target.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    ).rowcount
    audit(
        db,
        actor,
        "USER_PASSWORD_RESET",
        target_user=target.id,
        details={"sessions_revoked": revoked},
    )
    db.commit()
    return user_result(db, target)


def create_project(db, actor, data):
    require_finance(actor)
    if db.scalar(
        select(Project.id).where(Project.company_id == actor.company_id, Project.code == data.code)
    ):
        raise HTTPException(409, "رمز المشروع مستخدم في مشروع آخر داخل الشركة.")
    project = Project(company_id=actor.company_id, name=data.name, code=data.code)
    db.add(project)
    flush_unique(db, "رمز المشروع مستخدم في مشروع آخر داخل الشركة.")
    audit(
        db,
        actor,
        "PROJECT_CREATED",
        target_project=project.id,
        details={"name": project.name, "code": project.code},
    )
    commit_unique(db, "رمز المشروع مستخدم في مشروع آخر داخل الشركة.")
    return project_result(db, project)


def locked_project(db, actor, project_id):
    require_finance(actor)
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id, Project.company_id == actor.company_id)
        .with_for_update()
    )
    if not project:
        raise HTTPException(404, "المشروع غير موجود أو غير متاح لشركتك.")
    return project


def update_project(db, actor, project_id, data):
    project = locked_project(db, actor, project_id)
    if project.revision != data.revision:
        raise HTTPException(409, "تغير المشروع من جلسة أخرى. أعد تحميل الصفحة.")
    if project.is_active and not data.is_active:
        has_records = any(
            db.scalar(select(func.count()).select_from(model).where(model.project_id == project.id))
            for model in (Invoice, PurchaseOrder, ProjectBudget)
        )
        if has_records:
            raise HTTPException(
                409,
                "لا يمكن تعطيل مشروع مرتبط بفواتير أو أوامر شراء أو ميزانية؛ احتفظ به نشطًا.",
            )
    before = {"name": project.name, "code": project.code, "is_active": project.is_active}
    project.name = data.name
    project.code = data.code
    project.is_active = data.is_active
    project.revision += 1
    project.updated_at = utcnow()
    audit(
        db,
        actor,
        "PROJECT_UPDATED",
        target_project=project.id,
        details={
            "before": before,
            "after": {
                "name": project.name,
                "code": project.code,
                "is_active": project.is_active,
            },
        },
    )
    commit_unique(db, "رمز المشروع مستخدم في مشروع آخر داخل الشركة.")
    return project_result(db, project)


def update_project_members(db, actor, project_id, data):
    project = locked_project(db, actor, project_id)
    if project.revision != data.revision:
        raise HTTPException(409, "تغير المشروع من جلسة أخرى. أعد تحميل الصفحة.")
    if not project.is_active:
        raise HTTPException(409, "فعّل المشروع قبل تعديل أعضائه.")
    users = list(
        db.scalars(
            select(User).where(
                User.id.in_(data.members),
                User.company_id == actor.company_id,
                User.is_active.is_(True),
                User.role.in_(("EMPLOYEE", "PROJECT_MANAGER")),
            )
        )
    )
    if len(users) != len(data.members):
        raise HTTPException(422, "اختر حسابات نشطة من الموظفين ومديري المشاريع في شركتك فقط.")
    old_members = list(
        db.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project.id)
        ).all()
    )
    new_ids = set(data.members)
    for _, old_user in old_members:
        if old_user.id not in new_ids and old_user.role == "EMPLOYEE":
            if db.scalar(
                select(func.count())
                .select_from(Invoice)
                .where(
                    Invoice.project_id == project.id,
                    Invoice.created_by == old_user.id,
                    Invoice.status.in_(EDITABLE_INVOICES),
                )
            ):
                raise HTTPException(
                    409,
                    f"لا يمكن إزالة {old_user.name}؛ لديه فواتير مسودة أو مطلوب تعديلها في المشروع.",
                )
    if db.scalar(
        select(func.count())
        .select_from(Invoice)
        .where(Invoice.project_id == project.id, Invoice.status == "PROJECT_REVIEW")
    ) and not any(user.role == "PROJECT_MANAGER" for user in users):
        raise HTTPException(409, "المشروع لديه فواتير قيد المراجعة ويحتاج مدير مشروع نشطًا.")

    before = [str(membership.user_id) for membership, _ in old_members]
    db.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id))
    db.add_all(
        [
            ProjectMember(
                project_id=project.id,
                user_id=user.id,
                membership_role=member_role(user.role),
            )
            for user in users
        ]
    )
    project.revision += 1
    project.updated_at = utcnow()
    audit(
        db,
        actor,
        "PROJECT_MEMBERS_REPLACED",
        target_project=project.id,
        details={"before": before, "after": [str(value) for value in data.members]},
    )
    db.commit()
    return project_result(db, project)
