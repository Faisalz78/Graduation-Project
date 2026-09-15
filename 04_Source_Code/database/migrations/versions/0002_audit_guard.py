"""Protect persisted audit entries from update and delete."""

from alembic import op

revision = "0002_audit_guard"
down_revision = "433ea88a2305"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION reject_audit_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Audit entries cannot be modified'; END; $$;
        CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION reject_audit_change();
    """)
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='invoice_app') THEN
            REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM invoice_app;
            REVOKE ALL ON alembic_version FROM invoice_app;
        END IF;
    END $$;""")


def downgrade():
    op.execute("DROP TRIGGER audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION reject_audit_change()")
