import uuid

from fastapi import APIRouter, Depends, status

from app.core.security import Db, Identity, require_csrf
from app.schemas.administration import (
    PasswordResetInput,
    ProjectCreateInput,
    ProjectMembersInput,
    ProjectUpdateInput,
    UserCreateInput,
    UserUpdateInput,
)
from app.services import administration

router = APIRouter(prefix="/administration", tags=["Administration"])


@router.get("/users")
def list_users(db: Db, identity: Identity):
    return administration.list_users(db, identity[0])


@router.post("/users", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
def create_user(data: UserCreateInput, db: Db, identity: Identity):
    return administration.create_user(db, identity[0], data)


@router.put("/users/{user_id}", dependencies=[Depends(require_csrf)])
def update_user(user_id: uuid.UUID, data: UserUpdateInput, db: Db, identity: Identity):
    return administration.update_user(db, identity[0], user_id, data)


@router.post("/users/{user_id}/reset-password", dependencies=[Depends(require_csrf)])
def reset_password(user_id: uuid.UUID, data: PasswordResetInput, db: Db, identity: Identity):
    return administration.reset_password(db, identity[0], user_id, data)


@router.get("/projects")
def list_projects(db: Db, identity: Identity):
    return administration.list_projects(db, identity[0])


@router.post("/projects", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
def create_project(data: ProjectCreateInput, db: Db, identity: Identity):
    return administration.create_project(db, identity[0], data)


@router.put("/projects/{project_id}", dependencies=[Depends(require_csrf)])
def update_project(project_id: uuid.UUID, data: ProjectUpdateInput, db: Db, identity: Identity):
    return administration.update_project(db, identity[0], project_id, data)


@router.put("/projects/{project_id}/members", dependencies=[Depends(require_csrf)])
def update_project_members(
    project_id: uuid.UUID, data: ProjectMembersInput, db: Db, identity: Identity
):
    return administration.update_project_members(db, identity[0], project_id, data)
