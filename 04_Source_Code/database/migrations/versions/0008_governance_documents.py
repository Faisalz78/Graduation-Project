"""Approval limits, related financial documents, and supplier verification."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_governance_documents"
down_revision = "0007_purchase_orders_receipts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "approval_limits",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(22, 2), nullable=False),
        sa.Column("updated_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "currency IN ('SAR','AED','USD','EUR')", name="ck_approval_limit_currency"
        ),
        sa.CheckConstraint("amount >= 0", name="ck_approval_limit_amount"),
        sa.UniqueConstraint("user_id", "currency", name="uq_approval_limit_user_currency"),
    )
    op.create_index("ix_approval_limits_company_id", "approval_limits", ["company_id"])
    op.create_index("ix_approval_limits_user_id", "approval_limits", ["user_id"])
    op.create_table(
        "approval_limit_audit_logs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "approval_limit_id",
            sa.UUID(),
            sa.ForeignKey("approval_limits.id"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_approval_limit_audit_logs_company_id",
        "approval_limit_audit_logs",
        ["company_id"],
    )
    op.execute(
        "CREATE TRIGGER approval_limit_audit_logs_append_only "
        "BEFORE UPDATE OR DELETE ON approval_limit_audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_change()"
    )

    op.add_column(
        "suppliers",
        sa.Column(
            "verification_status",
            sa.String(12),
            nullable=False,
            server_default="UNVERIFIED",
        ),
    )
    op.add_column("suppliers", sa.Column("verification_note", sa.Text()))
    op.add_column("suppliers", sa.Column("verified_by", sa.UUID()))
    op.add_column("suppliers", sa.Column("verified_at", sa.DateTime(timezone=True)))
    op.create_foreign_key("fk_supplier_verified_by", "suppliers", "users", ["verified_by"], ["id"])
    op.create_check_constraint(
        "ck_supplier_verification_status",
        "suppliers",
        "verification_status IN ('UNVERIFIED','PENDING','VERIFIED','REJECTED')",
    )
    op.create_table(
        "supplier_audit_logs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("supplier_id", sa.UUID(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_supplier_audit_logs_company_id", "supplier_audit_logs", ["company_id"])
    op.create_index("ix_supplier_audit_logs_supplier_id", "supplier_audit_logs", ["supplier_id"])
    op.execute(
        "CREATE TRIGGER supplier_audit_logs_append_only BEFORE UPDATE OR DELETE ON supplier_audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_change()"
    )

    op.add_column(
        "invoices",
        sa.Column("document_type", sa.String(20), nullable=False, server_default="INVOICE"),
    )
    op.add_column("invoices", sa.Column("related_invoice_id", sa.UUID()))
    op.create_foreign_key(
        "fk_invoice_related_invoice",
        "invoices",
        "invoices",
        ["related_invoice_id"],
        ["id"],
    )
    op.create_index("ix_invoices_related_invoice_id", "invoices", ["related_invoice_id"])
    op.create_check_constraint(
        "ck_invoice_document_relation",
        "invoices",
        "(document_type = 'INVOICE' AND related_invoice_id IS NULL) OR "
        "(document_type IN ('CREDIT_NOTE','DEBIT_NOTE') AND related_invoice_id IS NOT NULL)",
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='invoice_app') THEN "
        "REVOKE UPDATE, DELETE, TRUNCATE ON approval_limit_audit_logs, supplier_audit_logs "
        "FROM invoice_app; END IF; END $$;"
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM invoices WHERE document_type <> 'INVOICE'")):
        raise RuntimeError("Cannot discard linked credit or debit notes.")
    if connection.scalar(sa.text("SELECT count(*) FROM supplier_audit_logs")):
        raise RuntimeError("Cannot discard supplier verification history.")
    if connection.scalar(sa.text("SELECT count(*) FROM approval_limit_audit_logs")):
        raise RuntimeError("Cannot discard approval limit history.")
    op.drop_constraint("ck_invoice_document_relation", "invoices", type_="check")
    op.drop_index("ix_invoices_related_invoice_id", table_name="invoices")
    op.drop_constraint("fk_invoice_related_invoice", "invoices", type_="foreignkey")
    op.drop_column("invoices", "related_invoice_id")
    op.drop_column("invoices", "document_type")
    op.execute("DROP TRIGGER supplier_audit_logs_append_only ON supplier_audit_logs")
    op.drop_table("supplier_audit_logs")
    op.drop_constraint("ck_supplier_verification_status", "suppliers", type_="check")
    op.drop_constraint("fk_supplier_verified_by", "suppliers", type_="foreignkey")
    op.drop_column("suppliers", "verified_at")
    op.drop_column("suppliers", "verified_by")
    op.drop_column("suppliers", "verification_note")
    op.drop_column("suppliers", "verification_status")
    op.execute("DROP TRIGGER approval_limit_audit_logs_append_only ON approval_limit_audit_logs")
    op.drop_table("approval_limit_audit_logs")
    op.drop_table("approval_limits")
