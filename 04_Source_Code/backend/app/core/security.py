import secrets
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import AuthSession, User

passwords = PasswordHash.recommended()
dummy_hash = passwords.hash(secrets.token_urlsafe(32))
COOKIE = "invoice_session"
Db = Annotated[Session, Depends(get_db)]
_attempts: dict[str, deque] = defaultdict(deque)
_lock = Lock()


def rate_limit_login(key: str):
    now = monotonic()
    with _lock:
        # This local demo limiter resets on restart; shared deployments need a shared store.
        if len(_attempts) > 2000:
            for old in list(_attempts):
                if not _attempts[old] or _attempts[old][-1] < now - 60:
                    del _attempts[old]
            if len(_attempts) > 2000:
                raise HTTPException(
                    429, "محاولات كثيرة، حاول بعد دقيقة.", headers={"Retry-After": "60"}
                )
        attempts = _attempts[key]
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= get_settings().login_attempts:
            raise HTTPException(
                429, "محاولات كثيرة، حاول بعد دقيقة.", headers={"Retry-After": "60"}
            )


def record_login_failure(key: str):
    with _lock:
        _attempts[key].append(monotonic())


def clear_login_failures(key: str):
    with _lock:
        _attempts.pop(key, None)


def require_origin(request: Request):
    if request.headers.get("origin", "").rstrip("/") != get_settings().app_origin.rstrip("/"):
        raise HTTPException(403, "مصدر الطلب غير مسموح.")


def issue_token(user: User, session: AuthSession) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user.id),
            "jti": str(session.id),
            "iat": now,
            "exp": session.expires_at,
            "iss": "invoice-audit",
            "aud": "invoice-app",
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )


def current_session(request: Request, db: Db) -> tuple[User, AuthSession]:
    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    bearer = credential.strip() if scheme.casefold() == "bearer" else ""
    token = bearer or request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "سجّل الدخول للمتابعة.")
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            audience="invoice-app",
            issuer="invoice-audit",
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
        session = db.get(AuthSession, uuid.UUID(payload["jti"]))
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(401, "انتهت الجلسة. سجّل الدخول مجددًا.") from None
    if (
        not session
        or not user
        or session.user_id != user.id
        or session.revoked_at
        or not user.is_active
    ):
        raise HTTPException(401, "الجلسة غير صالحة.")
    if session.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(401, "انتهت الجلسة. سجّل الدخول مجددًا.")
    request.state.auth_transport = "bearer" if bearer else "cookie"
    return user, session


Identity = Annotated[tuple[User, AuthSession], Depends(current_session)]


def require_csrf(request: Request, identity: Identity):
    if request.state.auth_transport == "bearer":
        return
    require_origin(request)
    if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), identity[1].csrf_token):
        raise HTTPException(403, "تعذر التحقق من الطلب. حدّث الصفحة وحاول مجددًا.")
