# The isolated database must be selected before importing application modules.
# ruff: noqa: E402
import os
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[3]
values = dotenv_values(ROOT / ".env")
test_url = os.environ.get("TEST_DATABASE_URL") or values.get("TEST_DATABASE_URL")
admin_url = os.environ.get("TEST_MIGRATION_DATABASE_URL") or values.get(
    "TEST_MIGRATION_DATABASE_URL"
)
if not test_url or not admin_url:
    raise RuntimeError("Configure the dedicated PostgreSQL test database before running tests.")
if (
    make_url(test_url).database != "invoice_audit_test"
    or make_url(admin_url).database != "invoice_audit_test"
):
    raise RuntimeError("Tests only operate on the dedicated invoice_audit_test database.")
os.environ["DATABASE_URL"] = test_url
os.environ["MIGRATION_DATABASE_URL"] = admin_url

from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.security import _attempts, passwords
from app.main import app
from app.models import ApprovalLimit, Company, Project, ProjectMember, User

admin_engine = create_engine(admin_url)
PASSWORD = "Test-only-password-42!"
PASSWORD_HASH = passwords.hash(PASSWORD)


@pytest.fixture(scope="session", autouse=True)
def migrations():
    command.upgrade(Config(str(ROOT / "04_Source_Code/backend/alembic.ini")), "head")
    yield
    engine.dispose()
    admin_engine.dispose()


@pytest.fixture(autouse=True)
def isolated_database(tmp_path):
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with admin_engine.begin() as conn:
        conn.exec_driver_sql(f"TRUNCATE TABLE {tables} CASCADE")
    previous = get_settings().upload_dir
    get_settings().upload_dir = tmp_path / "uploads"
    _attempts.clear()
    yield
    get_settings().upload_dir = previous


@pytest.fixture
def world():
    with Session(admin_engine, expire_on_commit=False) as db:
        company = Company(name="Test company")
        other = Company(name="Other company")
        db.add_all([company, other])
        db.flush()
        projects = {
            "a": Project(company_id=company.id, name="Project A", code="A"),
            "b": Project(company_id=company.id, name="Project B", code="B"),
            "other": Project(company_id=other.id, name="Other project", code="X"),
        }
        db.add_all(projects.values())
        db.flush()
        users = {}
        for name, role, memberships, tenant in [
            ("employee", "EMPLOYEE", ["a"], company),
            ("peer", "EMPLOYEE", ["a"], company),
            ("manager", "PROJECT_MANAGER", ["a"], company),
            ("manager_b", "PROJECT_MANAGER", ["b"], company),
            ("finance", "FINANCE_MANAGER", [], company),
            ("finance_peer", "FINANCE_MANAGER", [], company),
            ("outsider", "EMPLOYEE", ["other"], other),
        ]:
            user = User(
                company_id=tenant.id,
                email=f"{name}@test.invalid",
                name=name,
                role=role,
                password_hash=PASSWORD_HASH,
            )
            db.add(user)
            db.flush()
            users[name] = user
            for project in memberships:
                db.add(
                    ProjectMember(
                        project_id=projects[project].id,
                        user_id=user.id,
                        membership_role="MANAGER" if role == "PROJECT_MANAGER" else "MEMBER",
                    )
                )
        for reviewer in [
            users["manager"],
            users["manager_b"],
            users["finance"],
            users["finance_peer"],
        ]:
            for currency in ("SAR", "AED", "USD", "EUR"):
                db.add(
                    ApprovalLimit(
                        company_id=company.id,
                        user_id=reviewer.id,
                        currency=currency,
                        amount=Decimal("1000000000000000.00"),
                        updated_by=users["finance"].id,
                    )
                )
        db.commit()
        return {
            "users": users,
            "projects": projects,
            "password": PASSWORD,
            "admin_engine": admin_engine,
        }


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers["Origin"] = get_settings().app_origin
        yield client


def login(client, world, user="employee"):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": world["users"][user].email, "password": world["password"]},
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response
