"""Prepare a project-owned PostgreSQL instance. Run using the backend virtual environment."""

import json
import os
import secrets
import subprocess
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / ".local"
PG = LOCAL / "tools" / "pgsql" / "bin"
BACKEND = ROOT / "04_Source_Code" / "backend"
PORT = 55432
flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def run(args, **kwargs):
    # PostgreSQL children on Windows may inherit pipe handles. A real log file avoids
    # communicate() waiting forever after pg_ctl has already exited successfully.
    with (LOCAL / "bootstrap.log").open("ab") as output:
        result = subprocess.run(
            [str(x) for x in args],
            cwd=BACKEND,
            stdout=output,
            stderr=output,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
            timeout=120,
            **kwargs,
        )
    if result.returncode:
        raise RuntimeError(f"{Path(str(args[0])).name} failed; inspect .local/bootstrap.log")
    return result


def main():
    LOCAL.mkdir(exist_ok=True)
    state_path = LOCAL / "runtime.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        if (ROOT / ".env").exists():
            raise RuntimeError(
                "An .env already exists without runtime.json. Preserve it and configure the existing database manually."
            )
        state = {
            key: secrets.token_urlsafe(36)
            for key in ("admin_password", "app_password", "jwt_secret", "demo_password")
        }
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    if not (PG / "initdb.exe").exists():
        raise RuntimeError(
            "Download the official PostgreSQL binaries into .local/tools/pgsql first; see RUN_LOCAL_AR.md."
        )
    data = LOCAL / "pgdata"
    if not (data / "PG_VERSION").exists():
        password_file = LOCAL / "initdb.password"
        password_file.write_text(state["admin_password"], encoding="utf-8")
        try:
            run(
                [
                    PG / "initdb.exe",
                    "-D",
                    data,
                    "-U",
                    "invoice_admin",
                    "--pwfile",
                    password_file,
                    "--auth-host=scram-sha-256",
                    "--auth-local=scram-sha-256",
                    "--encoding=UTF8",
                    "--locale=C",
                ]
            )
        finally:
            password_file.unlink(missing_ok=True)
        with (data / "postgresql.conf").open("a", encoding="utf-8") as config:
            config.write(
                f"\nlisten_addresses = '127.0.0.1'\nport = {PORT}\nshared_buffers = '128MB'\nmax_connections = 40\n"
            )
    status = subprocess.run(
        [str(PG / "pg_ctl.exe"), "-D", str(data), "status"],
        capture_output=True,
        creationflags=flags,
    )
    if status.returncode:
        run([PG / "pg_ctl.exe", "-D", data, "-l", LOCAL / "postgresql.log", "-w", "start"])
    with psycopg.connect(
        host="127.0.0.1",
        port=PORT,
        dbname="postgres",
        user="invoice_admin",
        password=state["admin_password"],
        autocommit=True,
    ) as connection:
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='invoice_app'").fetchone():
            connection.execute(
                sql.SQL("CREATE ROLE invoice_app LOGIN PASSWORD {}").format(
                    sql.Literal(state["app_password"])
                )
            )
        for database in ("invoice_audit", "invoice_audit_test"):
            if not connection.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
            ).fetchone():
                connection.execute(
                    sql.SQL("CREATE DATABASE {} OWNER invoice_admin").format(
                        sql.Identifier(database)
                    )
                )

    def url(user, password, database):
        return f"postgresql+psycopg://{user}:{password}@127.0.0.1:{PORT}/{database}"

    values = {
        "DATABASE_URL": url("invoice_app", state["app_password"], "invoice_audit"),
        "MIGRATION_DATABASE_URL": url("invoice_admin", state["admin_password"], "invoice_audit"),
        "TEST_DATABASE_URL": url("invoice_app", state["app_password"], "invoice_audit_test"),
        "TEST_MIGRATION_DATABASE_URL": url(
            "invoice_admin", state["admin_password"], "invoice_audit_test"
        ),
        "JWT_SECRET": state["jwt_secret"],
        "APP_ORIGIN": "http://127.0.0.1:3000",
        "COOKIE_SECURE": "false",
    }
    if not (ROOT / ".env").exists():
        (ROOT / ".env").write_text(
            "\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8"
        )
    # Prepare permissions for existing and future migrations; the application is not a database owner.
    for database in ("invoice_audit", "invoice_audit_test"):
        with psycopg.connect(
            host="127.0.0.1",
            port=PORT,
            dbname=database,
            user="invoice_admin",
            password=state["admin_password"],
            autocommit=True,
        ) as connection:
            connection.execute("GRANT USAGE ON SCHEMA public TO invoice_app")
            connection.execute(
                "ALTER DEFAULT PRIVILEGES FOR ROLE invoice_admin IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO invoice_app"
            )
            connection.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO invoice_app"
            )
            if connection.execute("SELECT to_regclass('public.audit_logs')").fetchone()[0]:
                connection.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM invoice_app")
            if connection.execute("SELECT to_regclass('public.procurement_audit_logs')").fetchone()[
                0
            ]:
                connection.execute(
                    "REVOKE UPDATE, DELETE, TRUNCATE ON procurement_audit_logs FROM invoice_app"
                )
            for table in ("approval_limit_audit_logs", "supplier_audit_logs"):
                if connection.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0]:
                    connection.execute(
                        sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON {} FROM invoice_app").format(
                            sql.Identifier(table)
                        )
                    )
            if connection.execute("SELECT to_regclass('public.alembic_version')").fetchone()[0]:
                connection.execute("REVOKE ALL ON alembic_version FROM invoice_app")
    print("Project PostgreSQL is ready on 127.0.0.1:55432. Secrets remain in ignored local files.")


if __name__ == "__main__":
    main()
