"""Project and user administration with immutable audit history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_project_user_administration"
down_revision = "0009_project_budgets"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            "SELECT company_id, code FROM projects GROUP BY company_id, code "
            "HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate:
        raise RuntimeError("Duplicate project codes must be resolved before this migration.")

    for table in ("users", "projects"):
        op.add_column(
            table,
            sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        )
        op.add_column(
            table,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_check_constraint(f"ck_{table[:-1]}_revision", table, "revision > 0")
    op.create_unique_constraint("uq_project_company_code", "projects", ["company_id", "code"])

    op.create_table(
        "administration_audit_logs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_user_id", sa.UUID(), sa.ForeignKey("users.id")),
        sa.Column("target_project_id", sa.UUID(), sa.ForeignKey("projects.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
    )
    for column in ("company_id", "target_user_id", "target_project_id"):
        op.create_index(
            f"ix_administration_audit_logs_{column}",
            "administration_audit_logs",
            [column],
        )
    op.execute(
        "CREATE TRIGGER administration_audit_logs_append_only "
        "BEFORE UPDATE OR DELETE ON administration_audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_change()"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='invoice_app') THEN "
        "REVOKE UPDATE, DELETE, TRUNCATE ON administration_audit_logs FROM invoice_app; "
        "END IF; END $$;"
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM administration_audit_logs")):
        raise RuntimeError("Cannot discard project and user administration audit history.")
    op.execute("DROP TRIGGER administration_audit_logs_append_only ON administration_audit_logs")
    op.drop_table("administration_audit_logs")
    op.drop_constraint("uq_project_company_code", "projects", type_="unique")
    for table in ("projects", "users"):
        op.drop_constraint(f"ck_{table[:-1]}_revision", table, type_="check")
        op.drop_column(table, "updated_at")
        op.drop_column(table, "revision")
