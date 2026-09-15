import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.core.security import Db, Identity, require_csrf
from app.models import Notification, utcnow
from app.services.notifications import mark_all_read, notification_result

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("")
def list_notifications(
    db: Db,
    identity: Identity,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    unread_only: bool = False,
):
    user = identity[0]
    scope = (
        Notification.company_id == user.company_id,
        Notification.recipient_user_id == user.id,
    )
    query = select(Notification).where(*scope)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    unread_count = (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(*scope, Notification.read_at.is_(None))
        )
        or 0
    )
    notifications = db.scalars(
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [notification_result(item) for item in notifications],
        "total": total,
        "unread_count": unread_count,
        "page": page,
        "page_size": page_size,
    }


@router.post("/read-all", dependencies=[Depends(require_csrf)])
def read_all_notifications(db: Db, identity: Identity):
    return {"updated": mark_all_read(db, identity[0])}


@router.post("/{notification_id}/read", dependencies=[Depends(require_csrf)])
def read_notification(notification_id: uuid.UUID, db: Db, identity: Identity):
    user = identity[0]
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.company_id == user.company_id,
            Notification.recipient_user_id == user.id,
        )
    )
    if not notification:
        raise HTTPException(404, "التنبيه غير موجود أو غير متاح لك.")
    if notification.read_at is None:
        notification.read_at = utcnow()
        db.commit()
    return notification_result(notification)
