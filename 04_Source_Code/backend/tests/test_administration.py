from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.database import engine
from app.main import app
from app.models import AdministrationAuditLog, Invoice, User
from conftest import login

TEMPORARY_PASSWORD = "New-account-Password-42!"


def create_user(client, *, email="New.User@Example.test", role="EMPLOYEE"):
    response = client.post(
        "/api/v1/administration/users",
        json={
            "name": "مستخدم جديد",
            "email": email,
            "role": role,
            "temporary_password": TEMPORARY_PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_administration_is_finance_only_and_company_scoped(client, world):
    login(client, world, "employee")
    assert client.get("/api/v1/administration/users").status_code == 403
    assert client.get("/api/v1/administration/projects").status_code == 403

    login(client, world, "finance")
    users = client.get("/api/v1/administration/users")
    projects = client.get("/api/v1/administration/projects")
    assert users.status_code == projects.status_code == 200
    assert len(users.json()) == 6
    assert {item["code"] for item in projects.json()} == {"A", "B"}
    assert "outsider@test.invalid" not in {item["email"] for item in users.json()}


def test_create_user_normalizes_email_hashes_password_and_hides_secret_from_audit(client, world):
    login(client, world, "finance")
    created = create_user(client)
    assert created["email"] == "new.user@example.test"
    assert created["revision"] == 1
    assert created["memberships"] == []
    assert (
        client.post(
            "/api/v1/administration/users",
            json={
                "name": "مكرر",
                "email": "new.user@example.test",
                "role": "EMPLOYEE",
                "temporary_password": TEMPORARY_PASSWORD,
            },
        ).status_code
        == 409
    )
    with Session(world["admin_engine"]) as db:
        stored = db.get(User, created["id"])
        audit = db.scalar(
            select(AdministrationAuditLog).where(AdministrationAuditLog.target_user_id == stored.id)
        )
        assert stored.password_hash != TEMPORARY_PASSWORD
        assert "password" not in str(audit.details).casefold()
        assert TEMPORARY_PASSWORD not in str(audit.details)


def test_user_update_normalizes_memberships_and_rejects_stale_or_self_change(client, world):
    login(client, world, "finance")
    manager_id = str(world["users"]["manager"].id)
    current = next(
        item
        for item in client.get("/api/v1/administration/users").json()
        if item["id"] == manager_id
    )
    updated = client.put(
        f"/api/v1/administration/users/{manager_id}",
        json={
            "revision": current["revision"],
            "name": "مدير أصبح موظفًا",
            "role": "EMPLOYEE",
            "is_active": True,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == current["revision"] + 1
    assert {row["membership_role"] for row in updated.json()["memberships"]} == {"MEMBER"}
    assert (
        client.put(
            f"/api/v1/administration/users/{manager_id}",
            json={
                "revision": current["revision"],
                "name": "قيمة قديمة",
                "role": "EMPLOYEE",
                "is_active": True,
            },
        ).status_code
        == 409
    )
    finance = world["users"]["finance"]
    assert (
        client.put(
            f"/api/v1/administration/users/{finance.id}",
            json={
                "revision": finance.revision,
                "name": finance.name,
                "role": finance.role,
                "is_active": False,
            },
        ).status_code
        == 403
    )


def test_password_reset_revokes_sessions_and_replaces_credentials(client, world):
    with TestClient(app, raise_server_exceptions=False) as employee_client:
        employee_client.headers["Origin"] = client.headers["Origin"]
        login(employee_client, world, "employee")
        login(client, world, "finance")
        employee_id = str(world["users"]["employee"].id)
        current = next(
            item
            for item in client.get("/api/v1/administration/users").json()
            if item["id"] == employee_id
        )
        reset = client.post(
            f"/api/v1/administration/users/{employee_id}/reset-password",
            json={"revision": current["revision"], "temporary_password": TEMPORARY_PASSWORD},
        )
        assert reset.status_code == 200, reset.text
        assert reset.json()["revision"] == current["revision"] + 1
        assert employee_client.get("/api/v1/auth/session").status_code == 401
        assert (
            employee_client.post(
                "/api/v1/auth/login",
                json={
                    "email": world["users"]["employee"].email,
                    "password": world["password"],
                },
            ).status_code
            == 401
        )
        assert (
            employee_client.post(
                "/api/v1/auth/login",
                json={
                    "email": world["users"]["employee"].email,
                    "password": TEMPORARY_PASSWORD,
                },
            ).status_code
            == 200
        )


def test_project_creation_membership_replacement_and_concurrency(client, world):
    login(client, world, "finance")
    project = client.post(
        "/api/v1/administration/projects",
        json={"name": "مشروع الإدارة", "code": " adm-42 "},
    )
    assert project.status_code == 201, project.text
    created = project.json()
    assert created["code"] == "ADM-42"
    assert (
        client.post(
            "/api/v1/administration/projects",
            json={"name": "مشروع مكرر", "code": "ADM-42"},
        ).status_code
        == 409
    )
    member_ids = [
        str(world["users"]["employee"].id),
        str(world["users"]["manager"].id),
    ]
    members = client.put(
        f"/api/v1/administration/projects/{created['id']}/members",
        json={"revision": created["revision"], "members": member_ids},
    )
    assert members.status_code == 200, members.text
    assert {item["membership_role"] for item in members.json()["members"]} == {
        "MEMBER",
        "MANAGER",
    }
    assert (
        client.put(
            f"/api/v1/administration/projects/{created['id']}/members",
            json={"revision": created["revision"], "members": member_ids},
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/api/v1/administration/projects/{created['id']}/members",
            json={
                "revision": members.json()["revision"],
                "members": [str(world["users"]["finance"].id)],
            },
        ).status_code
        == 422
    )


def test_safety_guards_keep_editable_and_review_invoices_reachable(client, world):
    with Session(world["admin_engine"], expire_on_commit=False) as db:
        editable = Invoice(
            company_id=world["users"]["employee"].company_id,
            project_id=world["projects"]["a"].id,
            created_by=world["users"]["employee"].id,
            status="DRAFT",
        )
        review = Invoice(
            company_id=world["users"]["employee"].company_id,
            project_id=world["projects"]["a"].id,
            created_by=world["users"]["peer"].id,
            status="PROJECT_REVIEW",
            submitted_revision=1,
            submitted_at=datetime.now(timezone.utc),
        )
        db.add_all([editable, review])
        db.commit()

    login(client, world, "finance")
    users = client.get("/api/v1/administration/users").json()
    employee = next(item for item in users if item["id"] == str(world["users"]["employee"].id))
    manager = next(item for item in users if item["id"] == str(world["users"]["manager"].id))
    assert (
        client.put(
            f"/api/v1/administration/users/{employee['id']}",
            json={
                **{key: employee[key] for key in ("revision", "name", "role")},
                "is_active": False,
            },
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/api/v1/administration/users/{manager['id']}",
            json={
                **{key: manager[key] for key in ("revision", "name", "role")},
                "is_active": False,
            },
        ).status_code
        == 409
    )
    project = next(
        item
        for item in client.get("/api/v1/administration/projects").json()
        if item["id"] == str(world["projects"]["a"].id)
    )
    assert (
        client.put(
            f"/api/v1/administration/projects/{project['id']}/members",
            json={
                "revision": project["revision"],
                "members": [str(world["users"]["peer"].id)],
            },
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/api/v1/administration/projects/{project['id']}",
            json={
                "revision": project["revision"],
                "name": project["name"],
                "code": project["code"],
                "is_active": False,
            },
        ).status_code
        == 409
    )


def test_empty_project_can_be_deactivated_and_administration_audit_is_append_only(client, world):
    login(client, world, "finance")
    created = client.post(
        "/api/v1/administration/projects",
        json={"name": "مشروع مؤقت", "code": "TMP-99"},
    ).json()
    deactivated = client.put(
        f"/api/v1/administration/projects/{created['id']}",
        json={
            "revision": created["revision"],
            "name": created["name"],
            "code": created["code"],
            "is_active": False,
        },
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["is_active"] is False
    with Session(world["admin_engine"]) as db:
        assert db.scalar(select(func.count()).select_from(AdministrationAuditLog)) == 2
    with engine.connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("DELETE FROM administration_audit_logs"))
        connection.rollback()
