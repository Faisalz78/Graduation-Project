import io
import uuid

from PIL import Image

from app.core.security import COOKIE


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (60, 80), "white").save(output, format="PNG")
    return output.getvalue()


def mobile_login(client, world, user="employee"):
    return client.post(
        "/api/v1/auth/mobile/login",
        json={"email": world["users"][user].email, "password": world["password"]},
    )


def test_mobile_login_uses_revocable_bearer_without_setting_cookie(client, world):
    response = mobile_login(client, world)

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["user"]["role"] == "EMPLOYEE"
    assert response.json()["access_token"]
    assert COOKIE not in client.cookies
    assert "set-cookie" not in response.headers

    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    assert client.get("/api/v1/auth/session").status_code == 200
    assert [project["code"] for project in client.get("/api/v1/projects").json()] == ["A"]

    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/session").status_code == 401


def test_mobile_bearer_can_upload_without_browser_csrf_headers(client, world):
    response = mobile_login(client, world)
    client.headers.clear()
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"

    result = client.post(
        "/api/v1/invoices",
        data={"project_id": str(world["projects"]["a"].id), "note": "مرفوع من الجوال"},
        files={"file": ("mobile.png", png_bytes(), "image/png")},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )

    assert result.status_code == 201, result.text
    assert result.json()["note"] == "مرفوع من الجوال"
    assert result.json()["status"] == "DRAFT"


def test_invalid_bearer_does_not_fall_back_to_valid_browser_cookie(client, world):
    browser = client.post(
        "/api/v1/auth/login",
        json={"email": world["users"]["employee"].email, "password": world["password"]},
    )
    assert browser.status_code == 200

    result = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert result.status_code == 401


def test_mobile_login_rejects_wrong_password_without_token(client, world):
    response = client.post(
        "/api/v1/auth/mobile/login",
        json={"email": world["users"]["employee"].email, "password": "wrong"},
    )

    assert response.status_code == 401
    assert "access_token" not in response.json()
