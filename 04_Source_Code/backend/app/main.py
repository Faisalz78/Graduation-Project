import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.routes import (
    administration,
    analytics,
    auth,
    budgets,
    extraction,
    governance,
    invoices,
    notifications,
    projects,
    purchase_orders,
    reports,
    suppliers,
)

app = FastAPI(
    title="Invoice Audit API",
    version="0.19.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=get_settings().trusted_host_list,
)


class RequestSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        upload = scope["path"] == "/api/v1/invoices" or (
            scope["path"].startswith("/api/v1/purchase-orders/")
            and scope["path"].endswith("/receipts")
        )
        limit = (
            get_settings().max_upload_bytes + 128 * 1024
            if upload
            else 256 * 1024
            if scope["path"].startswith("/api/v1/invoices/")
            else 64 * 1024
        )
        headers = dict(scope.get("headers", []))
        try:
            too_large = int(headers.get(b"content-length", b"0")) > limit
        except ValueError:
            too_large = True
        if too_large:
            return await JSONResponse({"detail": "حجم الطلب أكبر من المسموح."}, status_code=413)(
                scope, receive, send
            )
        consumed = 0

        async def limited_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > limit:
                raise HTTPException(413, "حجم الطلب أكبر من المسموح.")
            return message

        await self.app(scope, limited_receive, send)


app.add_middleware(RequestSizeLimit)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    preview = (
        request.url.path.startswith("/api/v1/invoices/")
        and request.url.path.endswith("/file")
        and request.query_params.get("inline") == "true"
    )
    response.headers["X-Frame-Options"] = "SAMEORIGIN" if preview else "DENY"
    if preview:
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logging.getLogger(__name__).exception("Request failed: %s", request.url.path)
    return JSONResponse(
        {"detail": "تعذر إكمال العملية. حاول مجددًا."},
        status_code=500,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/v1/health", tags=["Health"])
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "postgresql", "version": "0.19.0"}


app.include_router(auth.router, prefix="/api/v1")
app.include_router(administration.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(budgets.router, prefix="/api/v1")
app.include_router(invoices.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(suppliers.router, prefix="/api/v1")
app.include_router(purchase_orders.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(governance.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(extraction.router, prefix="/api/v1")
