import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import engine
from app.core.security import COOKIE
from app.main import app
from app.models import Attachment, AuditLog, AuthSession, Invoice, ProjectMember, User, utcnow
from conftest import login


def pdf_bytes():
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.write(output)
    return output.getvalue()


def image_bytes(format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (60, 80), "white").save(output, format=format)
    return output.getvalue()


def xml_bytes(invoice_number="XML-001"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>{invoice_number}</cbc:ID>
</Invoice>""".encode("utf-8")


def unsafe_utf16_xml():
    return (
        '<?xml version="1.0" encoding="utf-16"?>'
        '<!DOCTYPE Invoice [<!ENTITY x "unsafe">]>'
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">'
        "&x;</Invoice>"
    ).encode("utf-16")


def upload(
    client, world, *, key=None, content=None, filename="invoice.pdf", project="a", note="Test note"
):
    return client.post(
        "/api/v1/invoices",
        data={"project_id": str(world["projects"][project].id), "note": note},
        files={
            "file": (
                filename,
                pdf_bytes() if content is None else content,
                "application/octet-stream",
            )
        },
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )


def test_health_and_anonymous_access(client):
    assert client.get("/api/v1/health").json()["database"] == "postgresql"
    for url in (
        "/api/v1/auth/session",
        "/api/v1/projects",
        "/api/v1/invoices",
        f"/api/v1/invoices/{uuid.uuid4()}/file",
    ):
        assert client.get(url).status_code == 401


def test_login_cookie_invalid_password_and_revoked_logout(client, world):
    bad = client.post(
        "/api/v1/auth/login",
        json={"email": world["users"]["employee"].email, "password": "incorrect"},
    )
    assert bad.status_code == 401
    good = login(client, world)
    assert "httponly" in good.headers["set-cookie"].lower()
    token = client.cookies.get(COOKIE)
    assert client.get("/api/v1/auth/session").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/session").status_code == 401
    client.cookies.set(COOKIE, token)
    assert client.get("/api/v1/auth/session").status_code == 401


def test_origin_csrf_and_tampered_cookie(client, world):
    assert (
        client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://example.invalid"},
            json={"email": "e@x.test", "password": "x"},
        ).status_code
        == 403
    )
    login(client, world)
    client.headers["X-CSRF-Token"] = "wrong"
    assert upload(client, world).status_code == 403
    client.cookies.clear()
    client.cookies.set(COOKIE, "tampered")
    assert client.get("/api/v1/auth/session").status_code == 401


@pytest.mark.parametrize("change", ["inactive", "expired"])
def test_session_invalidated_by_current_database_state(client, world, change):
    login(client, world)
    with Session(world["admin_engine"]) as db:
        if change == "inactive":
            db.execute(
                update(User).where(User.id == world["users"]["employee"].id).values(is_active=False)
            )
        else:
            db.execute(update(AuthSession).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert client.get("/api/v1/auth/session").status_code == 401


@pytest.mark.parametrize(
    "user,expected",
    [
        ("employee", ["A"]),
        ("manager", ["A"]),
        ("manager_b", ["B"]),
        ("finance", ["A", "B"]),
        ("outsider", ["X"]),
    ],
)
def test_project_scopes(client, world, user, expected):
    login(client, world, user)
    assert sorted(x["code"] for x in client.get("/api/v1/projects").json()) == expected


def test_upload_persistence_original_file_and_audit(client, world):
    login(client, world)
    content = pdf_bytes()
    result = upload(client, world, content=content)
    assert result.status_code == 201, result.text
    invoice = result.json()
    assert invoice["status"] == "DRAFT" and invoice["note"] == "Test note"
    assert {e["action"] for e in invoice["events"]} == {"DRAFT_CREATED", "FILE_ATTACHED"}
    assert "storage_key" not in invoice["attachment"]
    file = client.get(invoice["attachment"]["url"])
    assert file.content == content and file.headers["cache-control"] == "no-store"
    assert "attachment" in file.headers["content-disposition"]
    with TestClient(app) as refreshed:
        refreshed.headers["Origin"] = get_settings().app_origin
        login(refreshed, world)
        assert refreshed.get(f"/api/v1/invoices/{invoice['id']}").json()["id"] == invoice["id"]
        assert refreshed.get("/api/v1/invoices").json()["total"] == 1
    with Session(world["admin_engine"]) as db:
        assert db.scalar(select(func.count()).select_from(Invoice)) == 1
        assert db.scalar(select(func.count()).select_from(Attachment)) == 1
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 2


@pytest.mark.parametrize(
    "filename,content", [("sample.png", image_bytes()), ("sample.jpg", image_bytes("JPEG"))]
)
def test_valid_image_types(client, world, filename, content):
    login(client, world)
    result = upload(client, world, filename=filename, content=content)
    assert result.status_code == 201, result.text
    assert client.get(result.json()["attachment"]["url"]).content == content


def test_valid_ubl_xml_is_stored_privately(client, world):
    login(client, world)
    content = xml_bytes()
    result = upload(client, world, filename="invoice.xml", content=content)
    assert result.status_code == 201, result.text
    assert result.json()["attachment"]["media_type"] == "application/xml"
    downloaded = client.get(result.json()["attachment"]["url"])
    assert downloaded.content == content
    assert "attachment" in downloaded.headers["content-disposition"]


@pytest.mark.parametrize(
    "filename,content",
    [
        ("invoice.pdf", b"not PDF"),
        ("invoice.png", b"\x89PNG\r\n\x1a\n"),
        ("invoice.exe", pdf_bytes()),
        ("invoice.svg", b"<svg/>"),
        ("invoice.xml", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
        ("invoice.xml", unsafe_utf16_xml()),
        ("invoice.xml", b'<!DOCTYPE Invoice [<!ENTITY x "unsafe">]><Invoice>&x;</Invoice>'),
        ("invoice.jpg", image_bytes()),
        ("empty.pdf", b""),
    ],
)
def test_invalid_or_disguised_files_leave_no_records(client, world, filename, content):
    login(client, world)
    assert upload(client, world, filename=filename, content=content).status_code == 422
    assert client.get("/api/v1/invoices").json()["total"] == 0
    assert not get_settings().upload_dir.exists() or not list(get_settings().upload_dir.iterdir())


def test_oversized_body_and_encrypted_pdf(client, world):
    login(client, world)
    assert upload(client, world, content=b"x" * (11 * 1024 * 1024)).status_code == 413
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    data = io.BytesIO()
    writer.write(data)
    assert upload(client, world, content=data.getvalue()).status_code == 422
    assert client.get("/api/v1/invoices").json()["total"] == 0


@pytest.mark.parametrize("other", ["peer", "manager", "manager_b", "finance", "outsider"])
def test_draft_and_file_are_private_to_owner(client, world, other):
    login(client, world)
    response = upload(client, world)
    assert response.status_code == 201
    invoice = response.json()
    login(client, world, other)
    assert client.get("/api/v1/invoices").json()["total"] == 0
    assert client.get(f"/api/v1/invoices/{invoice['id']}").status_code == 404
    assert client.get(invoice["attachment"]["url"]).status_code == 404


def test_project_access_revocation_and_forbidden_creation(client, world):
    login(client, world)
    assert upload(client, world, project="b").status_code == 404
    assert upload(client, world, project="other").status_code == 404
    invoice = upload(client, world).json()
    with Session(world["admin_engine"]) as db:
        db.execute(
            delete(ProjectMember).where(ProjectMember.user_id == world["users"]["employee"].id)
        )
        db.commit()
    assert client.get(invoice["attachment"]["url"]).status_code == 404
    assert client.get("/api/v1/invoices").json()["total"] == 0
    login(client, world, "manager")
    assert upload(client, world).status_code == 403


def test_idempotency_replays_and_rejects_changed_payload(client, world):
    login(client, world)
    key = str(uuid.uuid4())
    data = pdf_bytes()
    first = upload(client, world, key=key, content=data)
    replay = upload(client, world, key=key, content=data)
    assert first.status_code == 201 and replay.status_code == 200
    assert first.json()["id"] == replay.json()["id"]
    assert replay.headers["idempotency-replayed"] == "true"
    assert upload(client, world, key=key, content=data, note="Changed").status_code == 409
    assert client.get("/api/v1/invoices").json()["total"] == 1


def test_concurrent_retry_has_one_committed_effect(world):
    key = str(uuid.uuid4())
    data = pdf_bytes()

    def request():
        with TestClient(app) as client:
            client.headers["Origin"] = get_settings().app_origin
            login(client, world)
            result = upload(client, world, key=key, content=data)
            return result.status_code, result.json()["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: request(), range(2)))
    assert sorted(x[0] for x in results) == [200, 201]
    assert len({x[1] for x in results}) == 1
    with Session(world["admin_engine"]) as db:
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 2


def test_commit_failure_cleans_uncommitted_file(client, world, monkeypatch):
    login(client, world)

    def fail_commit(self):
        raise OSError("Simulated commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    assert upload(client, world).status_code == 500
    assert not list(get_settings().upload_dir.iterdir())
    with Session(world["admin_engine"]) as db:
        assert db.scalar(select(func.count()).select_from(Invoice)) == 0


def test_audit_table_rejects_modification(client, world):
    login(client, world)
    upload(client, world)
    with engine.connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("DELETE FROM audit_logs"))
        connection.rollback()
    with world["admin_engine"].connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("UPDATE audit_logs SET action = 'CHANGED'"))
        connection.rollback()


def test_login_rate_limit(client, world):
    previous = get_settings().login_attempts
    get_settings().login_attempts = 2
    try:
        payload = {"email": "unknown@test.invalid", "password": "wrong"}
        assert client.post("/api/v1/auth/login", json=payload).status_code == 401
        assert client.post("/api/v1/auth/login", json=payload).status_code == 401
        assert client.post("/api/v1/auth/login", json=payload).status_code == 429
    finally:
        get_settings().login_attempts = previous


def test_successful_logins_do_not_consume_failed_attempt_limit(client, world):
    previous = get_settings().login_attempts
    get_settings().login_attempts = 2
    try:
        credentials = {
            "email": world["users"]["employee"].email,
            "password": world["password"],
        }
        for _ in range(3):
            assert client.post("/api/v1/auth/login", json=credentials).status_code == 200
    finally:
        get_settings().login_attempts = previous
