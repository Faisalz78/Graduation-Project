import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import (
    COOKIE,
    Db,
    Identity,
    clear_login_failures,
    dummy_hash,
    issue_token,
    passwords,
    rate_limit_login,
    record_login_failure,
    require_csrf,
    require_origin,
)
from app.models import AuthSession, User

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def session_result(user, session):
    return {
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
        "csrf_token": session.csrf_token,
        "expires_at": session.expires_at,
    }


def authenticate(data: LoginInput, request: Request, db: Db):
    email = data.email.strip().casefold()
    client_key = request.client.host if request.client else "local"
    rate_limit_login(client_key)
    user = db.scalar(select(User).where(User.email == email))
    valid = passwords.verify(data.password, user.password_hash if user else dummy_hash)
    if not user or not valid or not user.is_active:
        record_login_failure(client_key)
        raise HTTPException(401, "البريد أو كلمة المرور غير صحيحة.")
    clear_login_failures(client_key)
    session = AuthSession(
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=get_settings().session_minutes),
    )
    db.add(session)
    db.commit()
    return user, session


@router.post("/login", dependencies=[Depends(require_origin)])
def login(data: LoginInput, request: Request, response: Response, db: Db):
    user, session = authenticate(data, request, db)
    response.set_cookie(
        COOKIE,
        issue_token(user, session),
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
        max_age=get_settings().session_minutes * 60,
    )
    return session_result(user, session)


@router.post("/mobile/login")
def mobile_login(data: LoginInput, request: Request, db: Db):
    user, session = authenticate(data, request, db)
    return {
        **session_result(user, session),
        "access_token": issue_token(user, session),
        "token_type": "bearer",
    }


@router.get("/session")
def get_session(identity: Identity):
    return session_result(*identity)


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(response: Response, identity: Identity, db: Db):
    identity[1].revoked_at = datetime.now(timezone.utc)
    db.commit()
    response.delete_cookie(
        COOKIE, path="/", secure=get_settings().cookie_secure, httponly=True, samesite="lax"
    )
    return {"message": "تم تسجيل الخروج."}
