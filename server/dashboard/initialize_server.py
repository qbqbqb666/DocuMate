"""One-time setup, executed as root with psycopg available. No existing roles are changed."""
import os
import secrets
import subprocess
from pathlib import Path

from psycopg import sql


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo")
    env = Path("/etc/documate-dashboard/dashboard.env")
    if env.exists():
        raise SystemExit("Dashboard configuration already exists; refusing to overwrite")
    existing = subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-At", "-d", "documate_auth", "-c",
         "SELECT 1 FROM pg_roles WHERE rolname = 'documate_dashboard'"],
        check=True, capture_output=True, text=True,
    )
    if existing.stdout.strip():
        raise SystemExit("Database role already exists; refusing to change it")
    password = secrets.token_hex(32)
    statement = sql.SQL("""
        BEGIN;
        CREATE ROLE documate_dashboard LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
        ALTER ROLE documate_dashboard SET default_transaction_read_only = on;
        ALTER ROLE documate_dashboard SET statement_timeout = '5s';
        GRANT CONNECT ON DATABASE documate_auth TO documate_dashboard;
        GRANT USAGE ON SCHEMA public TO documate_dashboard;
        GRANT SELECT (id, username, status, seen_welcome, created_at) ON public.users TO documate_dashboard;
        GRANT SELECT (id, user_id, created_at, expires_at, revoked_at) ON public.refresh_sessions TO documate_dashboard;
        COMMIT;
    """).format(sql.Literal(password)).as_string()
    result = subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-q", "-v", "ON_ERROR_STOP=1", "-d", "documate_auth"],
        input=statement, capture_output=True, text=True,
    )
    if result.returncode:
        raise SystemExit("Read-only role setup failed; transaction rolled back")
    env.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Credentials are generated here, never printed or copied into the repository.
    descriptor = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(
            "DASHBOARD_USERNAME=qbqb\n"
            "DASHBOARD_PASSWORD=qbqb\n"
            f"DASHBOARD_SESSION_SECRET={secrets.token_hex(32)}\n"
            f"DASHBOARD_DATABASE_URL=postgresql+psycopg://documate_dashboard:{password}@127.0.0.1:5432/documate_auth\n"
        )
    print("Read-only database role and protected dashboard configuration created")


if __name__ == "__main__":
    main()
