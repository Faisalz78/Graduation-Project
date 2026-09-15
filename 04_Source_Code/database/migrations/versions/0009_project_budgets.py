"""Expense categories, project budgets, and invoice line allocation."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_project_budgets"
down_revision = "0008_governance_documents"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "expense_categories",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "code", name="uq_expense_category_company_code"),
    )
    op.create_index("ix_expense_categories_company_id", "expense_categories", ["company_id"])

    op.create_table(
        "project_budgets",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total_amount", sa.Numeric(22, 2), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "currency IN ('SAR','AED','USD','EUR')", name="ck_project_budget_currency"
        ),
        sa.CheckConstraint("total_amount >= 0", name="ck_project_budget_total"),
        sa.CheckConstraint("revision > 0", name="ck_project_budget_revision"),
        sa.UniqueConstraint("project_id", "currency", name="uq_project_budget_currency"),
    )
    for column in ("company_id", "project_id"):
        op.create_index(f"ix_project_budgets_{column}", "project_budgets", [column])

    op.create_table(
        "project_budget_lines",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "project_budget_id",
            sa.UUID(),
            sa.ForeignKey("project_budgets.id"),
            nullable=False,
        ),
        sa.Column(
            "expense_category_id",
            sa.UUID(),
            sa.ForeignKey("expense_categories.id"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("unit", sa.String(40)),
        sa.Column("planned_quantity", sa.Numeric(14, 4)),
        sa.Column("planned_unit_price", sa.Numeric(18, 4)),
        sa.Column("allocated_amount", sa.Numeric(22, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("position > 0", name="ck_project_budget_line_position"),
        sa.CheckConstraint(
            "allocated_amount >= 0 AND "
            "((planned_quantity IS NULL AND planned_unit_price IS NULL) OR "
            "(planned_quantity > 0 AND planned_unit_price >= 0))",
            name="ck_project_budget_line_values",
        ),
    )
    op.create_index(
        "ix_project_budget_lines_project_budget_id",
        "project_budget_lines",
        ["project_budget_id"],
    )
    op.create_index(
        "ix_project_budget_lines_expense_category_id",
        "project_budget_lines",
        ["expense_category_id"],
    )

    op.create_table(
        "budget_audit_logs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id")),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_budget_audit_logs_company_id", "budget_audit_logs", ["company_id"])
    op.create_index("ix_budget_audit_logs_project_id", "budget_audit_logs", ["project_id"])
    op.execute(
        "CREATE TRIGGER budget_audit_logs_append_only "
        "BEFORE UPDATE OR DELETE ON budget_audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_change()"
    )

    op.add_column("invoice_items", sa.Column("project_budget_line_id", sa.UUID()))
    op.create_foreign_key(
        "fk_invoice_item_project_budget_line",
        "invoice_items",
        "project_budget_lines",
        ["project_budget_line_id"],
        ["id"],
    )
    op.create_index(
        "ix_invoice_items_project_budget_line_id",
        "invoice_items",
        ["project_budget_line_id"],
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='invoice_app') THEN "
        "REVOKE UPDATE, DELETE, TRUNCATE ON budget_audit_logs FROM invoice_app; "
        "END IF; END $$;"
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM project_budgets")):
        raise RuntimeError("Cannot discard project budgets or their audit history.")
    op.drop_index("ix_invoice_items_project_budget_line_id", table_name="invoice_items")
    op.drop_constraint("fk_invoice_item_project_budget_line", "invoice_items", type_="foreignkey")
    op.drop_column("invoice_items", "project_budget_line_id")
    op.execute("DROP TRIGGER budget_audit_logs_append_only ON budget_audit_logs")
    op.drop_table("budget_audit_logs")
    op.drop_table("project_budget_lines")
    op.drop_table("project_budgets")
    op.drop_table("expense_categories")
