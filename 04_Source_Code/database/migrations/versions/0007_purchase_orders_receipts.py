"""Purchase orders, receipt evidence, and invoice line mapping."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_purchase_orders_receipts"
down_revision = "0006_financial_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("supplier_id", sa.UUID(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("number", sa.String(100), nullable=False),
        sa.Column("number_key", sa.String(100), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "currency IN ('SAR','AED','USD','EUR')", name="ck_purchase_order_currency"
        ),
        sa.UniqueConstraint("company_id", "number_key", name="uq_purchase_order_company_number"),
    )
    for column in ("company_id", "project_id", "supplier_id"):
        op.create_index(f"ix_purchase_orders_{column}", "purchase_orders", [column])

    op.create_table(
        "purchase_order_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "purchase_order_id", sa.UUID(), sa.ForeignKey("purchase_orders.id"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("unit", sa.String(40)),
        sa.Column("ordered_quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False),
        sa.CheckConstraint(
            "ordered_quantity > 0 AND unit_price >= 0 AND tax_rate >= 0 AND tax_rate <= 100",
            name="ck_purchase_order_item_values",
        ),
        sa.UniqueConstraint(
            "purchase_order_id", "position", name="uq_purchase_order_item_position"
        ),
    )
    op.create_index(
        "ix_purchase_order_items_purchase_order_id",
        "purchase_order_items",
        ["purchase_order_id"],
    )

    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "purchase_order_id", sa.UUID(), sa.ForeignKey("purchase_orders.id"), nullable=False
        ),
        sa.Column("number", sa.String(100), nullable=False),
        sa.Column("number_key", sa.String(100), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("purchase_order_id", "number_key", name="uq_receipt_order_number"),
    )
    op.create_index("ix_goods_receipts_purchase_order_id", "goods_receipts", ["purchase_order_id"])

    op.create_table(
        "goods_receipt_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "goods_receipt_id", sa.UUID(), sa.ForeignKey("goods_receipts.id"), nullable=False
        ),
        sa.Column(
            "purchase_order_item_id",
            sa.UUID(),
            sa.ForeignKey("purchase_order_items.id"),
            nullable=False,
        ),
        sa.Column("received_quantity", sa.Numeric(14, 4), nullable=False),
        sa.CheckConstraint("received_quantity > 0", name="ck_receipt_item_quantity"),
        sa.UniqueConstraint("goods_receipt_id", "purchase_order_item_id", name="uq_receipt_item"),
    )
    op.create_index(
        "ix_goods_receipt_items_goods_receipt_id",
        "goods_receipt_items",
        ["goods_receipt_id"],
    )
    op.create_index(
        "ix_goods_receipt_items_purchase_order_item_id",
        "goods_receipt_items",
        ["purchase_order_item_id"],
    )

    op.create_table(
        "receipt_attachments",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "goods_receipt_id",
            sa.UUID(),
            sa.ForeignKey("goods_receipts.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("storage_key", sa.String(80), nullable=False, unique=True),
        sa.Column("original_name", sa.String(180), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_receipt_attachments_sha256", "receipt_attachments", ["sha256"])

    op.create_table(
        "procurement_audit_logs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "purchase_order_id", sa.UUID(), sa.ForeignKey("purchase_orders.id"), nullable=False
        ),
        sa.Column("goods_receipt_id", sa.UUID(), sa.ForeignKey("goods_receipts.id")),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
    )
    for column in ("company_id", "purchase_order_id"):
        op.create_index(f"ix_procurement_audit_logs_{column}", "procurement_audit_logs", [column])
    op.execute(
        "CREATE TRIGGER procurement_audit_logs_append_only "
        "BEFORE UPDATE OR DELETE ON procurement_audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_change()"
    )

    op.add_column("invoices", sa.Column("purchase_order_id", sa.UUID()))
    op.create_foreign_key(
        "fk_invoice_purchase_order",
        "invoices",
        "purchase_orders",
        ["purchase_order_id"],
        ["id"],
    )
    op.create_index("ix_invoices_purchase_order_id", "invoices", ["purchase_order_id"])
    op.add_column("invoice_items", sa.Column("purchase_order_item_id", sa.UUID()))
    op.create_foreign_key(
        "fk_invoice_item_purchase_order_item",
        "invoice_items",
        "purchase_order_items",
        ["purchase_order_item_id"],
        ["id"],
    )
    op.create_index(
        "ix_invoice_items_purchase_order_item_id",
        "invoice_items",
        ["purchase_order_item_id"],
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='invoice_app') THEN "
        "REVOKE UPDATE, DELETE, TRUNCATE ON procurement_audit_logs FROM invoice_app; "
        "END IF; END $$;"
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM purchase_orders")):
        raise RuntimeError("Cannot discard purchase orders or receipt evidence.")
    op.drop_index("ix_invoice_items_purchase_order_item_id", table_name="invoice_items")
    op.drop_constraint("fk_invoice_item_purchase_order_item", "invoice_items", type_="foreignkey")
    op.drop_column("invoice_items", "purchase_order_item_id")
    op.drop_index("ix_invoices_purchase_order_id", table_name="invoices")
    op.drop_constraint("fk_invoice_purchase_order", "invoices", type_="foreignkey")
    op.drop_column("invoices", "purchase_order_id")
    op.execute("DROP TRIGGER procurement_audit_logs_append_only ON procurement_audit_logs")
    op.drop_table("procurement_audit_logs")
    op.drop_table("receipt_attachments")
    op.drop_table("goods_receipt_items")
    op.drop_table("goods_receipts")
    op.drop_table("purchase_order_items")
    op.drop_table("purchase_orders")
