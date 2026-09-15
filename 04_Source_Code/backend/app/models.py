import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('EMPLOYEE','PROJECT_MANAGER','FINANCE_MANAGER')", name="ck_user_role"
        ),
        CheckConstraint("revision > 0", name="ck_user_revision"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApprovalLimit(Base):
    __tablename__ = "approval_limits"
    __table_args__ = (
        UniqueConstraint("user_id", "currency", name="uq_approval_limit_user_currency"),
        CheckConstraint("currency IN ('SAR','AED','USD','EUR')", name="ck_approval_limit_currency"),
        CheckConstraint("amount >= 0", name="ck_approval_limit_amount"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(22, 2))
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApprovalLimitAuditLog(Base):
    __tablename__ = "approval_limit_audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    approval_limit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_limits.id"))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_project_company_code"),
        CheckConstraint("revision > 0", name="ck_project_revision"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    membership_role: Mapped[str] = mapped_column(String(30))


class AdministrationAuditLog(Base):
    __tablename__ = "administration_audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    target_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_expense_category_company_code"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectBudget(Base):
    __tablename__ = "project_budgets"
    __table_args__ = (
        UniqueConstraint("project_id", "currency", name="uq_project_budget_currency"),
        CheckConstraint("currency IN ('SAR','AED','USD','EUR')", name="ck_project_budget_currency"),
        CheckConstraint("total_amount >= 0", name="ck_project_budget_total"),
        CheckConstraint("revision > 0", name="ck_project_budget_revision"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(22, 2))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectBudgetLine(Base):
    __tablename__ = "project_budget_lines"
    __table_args__ = (
        CheckConstraint("position > 0", name="ck_project_budget_line_position"),
        CheckConstraint(
            "allocated_amount >= 0 AND "
            "((planned_quantity IS NULL AND planned_unit_price IS NULL) OR "
            "(planned_quantity > 0 AND planned_unit_price >= 0))",
            name="ck_project_budget_line_values",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_budgets.id"), index=True
    )
    expense_category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("expense_categories.id"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(500))
    unit: Mapped[str | None] = mapped_column(String(40))
    planned_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    planned_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(22, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BudgetAuditLog(Base):
    __tablename__ = "budget_audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','PROJECT_REVIEW','FINANCE_REVIEW',"
            "'CHANGES_REQUESTED','APPROVED','REJECTED')",
            name="ck_invoice_status",
        ),
        CheckConstraint(
            "(status = 'DRAFT' AND submitted_revision IS NULL AND submitted_at IS NULL) OR "
            "(status <> 'DRAFT' AND submitted_revision IS NOT NULL AND submitted_at IS NOT NULL "
            "AND submitted_revision > 0 AND submitted_revision <= revision)",
            name="ck_invoice_submission",
        ),
        CheckConstraint(
            "(status IN ('FINANCE_REVIEW','APPROVED') AND project_approved_by IS NOT NULL "
            "AND project_approved_revision IS NOT NULL AND project_approved_revision = submitted_revision) OR "
            "(status NOT IN ('FINANCE_REVIEW','APPROVED') AND project_approved_by IS NULL "
            "AND project_approved_revision IS NULL)",
            name="ck_invoice_project_approval",
        ),
        CheckConstraint(
            "(document_type = 'INVOICE' AND related_invoice_id IS NULL) OR "
            "(document_type IN ('CREDIT_NOTE','DEBIT_NOTE') AND related_invoice_id IS NOT NULL)",
            name="ck_invoice_document_relation",
        ),
        Index("ix_invoice_owner_created", "created_by", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_orders.id", name="fk_invoice_purchase_order"), index=True
    )
    related_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoices.id", name="fk_invoice_related_invoice"), index=True
    )
    document_type: Mapped[str] = mapped_column(String(20), default="INVOICE")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    submitted_revision: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    project_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", name="fk_invoice_project_approver")
    )
    project_approved_revision: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", name="fk_invoice_supplier"), index=True
    )
    supplier_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(22, 2))
    discount_total: Mapped[Decimal | None] = mapped_column(Numeric(22, 2))
    tax_total: Mapped[Decimal | None] = mapped_column(Numeric(22, 2))
    grand_total: Mapped[Decimal | None] = mapped_column(Numeric(22, 2))
    document_subtotal: Mapped[Decimal | None] = mapped_column(Numeric(22, 2))
    document_tax_total: Mapped[Decimal | None] = mapped_column(Numeric(22, 2))
    document_grand_total: Mapped[Decimal | None] = mapped_column(Numeric(22, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), unique=True)
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)
    original_name: Mapped[str] = mapped_column(String(180))
    media_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','STALE')",
            name="ck_extraction_status",
        ),
        CheckConstraint("language IN ('ar','en')", name="ck_extraction_language"),
        CheckConstraint(
            "base_revision > 0 AND attempts >= 0 AND attempts <= 2", name="ck_extraction_attempts"
        ),
        Index("ix_extraction_invoice_created", "invoice_id", "created_at"),
        Index(
            "uq_extraction_active",
            "invoice_id",
            unique=True,
            postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    attachment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attachments.id"))
    source_sha256: Mapped[str] = mapped_column(String(64))
    base_revision: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(2))
    status: Mapped[str] = mapped_column(String(12), default="QUEUED")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("user_id", "operation", "key", name="uq_idempotency_user_operation_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    operation: Mapped[str] = mapped_column(String(40))
    key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("company_id", "name_key", name="uq_supplier_company_name"),
        CheckConstraint(
            "verification_status IN ('UNVERIFIED','PENDING','VERIFIED','REJECTED')",
            name="ck_supplier_verification_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(240))
    tax_number: Mapped[str | None] = mapped_column(String(40))
    region_code: Mapped[str | None] = mapped_column(String(30), index=True)
    verification_status: Mapped[str] = mapped_column(String(12), default="UNVERIFIED")
    verification_note: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", name="fk_supplier_verified_by")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupplierAuditLog(Base):
    __tablename__ = "supplier_audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "recipient_user_id", "dedupe_key", name="uq_notification_recipient_dedupe"
        ),
        Index("ix_notification_recipient_created", "recipient_user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("company_id", "number_key", name="uq_purchase_order_company_number"),
        CheckConstraint("currency IN ('SAR','AED','USD','EUR')", name="ck_purchase_order_currency"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    number: Mapped[str] = mapped_column(String(100))
    number_key: Mapped[str] = mapped_column(String(100))
    order_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        UniqueConstraint("purchase_order_id", "position", name="uq_purchase_order_item_position"),
        CheckConstraint(
            "ordered_quantity > 0 AND unit_price >= 0 AND tax_rate >= 0 AND tax_rate <= 100",
            name="ck_purchase_order_item_values",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(500))
    unit: Mapped[str | None] = mapped_column(String(40))
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4))


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint("purchase_order_id", "number_key", name="uq_receipt_order_number"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id"), index=True
    )
    number: Mapped[str] = mapped_column(String(100))
    number_key: Mapped[str] = mapped_column(String(100))
    received_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoodsReceiptItem(Base):
    __tablename__ = "goods_receipt_items"
    __table_args__ = (
        UniqueConstraint("goods_receipt_id", "purchase_order_item_id", name="uq_receipt_item"),
        CheckConstraint("received_quantity > 0", name="ck_receipt_item_quantity"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goods_receipts.id"), index=True)
    purchase_order_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_items.id"), index=True
    )
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))


class ReceiptAttachment(Base):
    __tablename__ = "receipt_attachments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("goods_receipts.id"), unique=True
    )
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)
    original_name: Mapped[str] = mapped_column(String(180))
    media_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcurementAuditLog(Base):
    __tablename__ = "procurement_audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id"), index=True
    )
    goods_receipt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goods_receipts.id"))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    __table_args__ = (
        UniqueConstraint("invoice_id", "position", name="uq_invoice_item_position"),
        CheckConstraint(
            "quantity > 0 AND unit_price >= 0 AND discount_amount >= 0 AND tax_rate >= 0 AND tax_rate <= 100",
            name="ck_item_values",
        ),
        CheckConstraint(
            "net_amount >= 0 AND tax_amount >= 0 AND total_amount >= 0", name="ck_item_totals"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    purchase_order_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_order_items.id", name="fk_invoice_item_purchase_order_item"),
        index=True,
    )
    project_budget_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_budget_lines.id", name="fk_invoice_item_project_budget_line"),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(500))
    unit: Mapped[str | None] = mapped_column(String(40))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(22, 2))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(22, 2))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(22, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(22, 2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(22, 2))
