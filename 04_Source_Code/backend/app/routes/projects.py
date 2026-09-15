from fastapi import APIRouter
from sqlalchemy import select

from app.core.security import Db, Identity
from app.models import Project, ProjectMember

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("")
def list_projects(db: Db, identity: Identity):
    user, _ = identity
    query = select(Project).where(
        Project.company_id == user.company_id, Project.is_active.is_(True)
    )
    if user.role != "FINANCE_MANAGER":
        query = query.join(ProjectMember).where(ProjectMember.user_id == user.id)
        if user.role == "PROJECT_MANAGER":
            query = query.where(ProjectMember.membership_role == "MANAGER")
    return [
        {"id": p.id, "name": p.name, "code": p.code}
        for p in db.scalars(query.order_by(Project.name))
    ]
