"""Deployment check: no user records are inserted, changed, or deleted."""
import json
import os
import secrets
import subprocess

import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo to read the protected dashboard configuration")
    config = dotenv_values("/etc/documate-dashboard/dashboard.env")
    engine = create_engine(config["DASHBOARD_DATABASE_URL"])
    with engine.connect() as db:
        assert db.scalar(text("SHOW default_transaction_read_only")) == "on"
        print("Database transaction default: READ ONLY")
    for statement in [
        "SELECT password_hash FROM public.users LIMIT 0",
        "SELECT token_hash FROM public.refresh_sessions LIMIT 0",
        "EXPLAIN INSERT INTO public.users (username) VALUES ('dashboard_permission_probe')",
        "EXPLAIN UPDATE public.users SET status = 'active' WHERE false",
        "EXPLAIN DELETE FROM public.users WHERE false",
        "EXPLAIN INSERT INTO public.refresh_sessions (user_id) VALUES (1)",
        "EXPLAIN UPDATE public.refresh_sessions SET revoked_at = NOW() WHERE false",
        "EXPLAIN DELETE FROM public.refresh_sessions WHERE false",
    ]:
        try:
            with engine.connect() as db, db.begin():
                # Even if the role overrides its read-only default, grants still deny writes.
                db.execute(text("SET TRANSACTION READ WRITE"))
                db.execute(text(statement))
        except DBAPIError as error:
            assert getattr(error.orig, "sqlstate", None) == "42501"
            print("Permission denied as expected:", statement.split()[0:3])
        else:
            raise AssertionError("Unexpected permission for a sensitive or write operation")
    engine.dispose()
    with httpx.Client(base_url="http://127.0.0.1:8081", timeout=10) as client:
        assert client.get("/api/dashboard").status_code == 401
        assert client.post("/api/login", json={"username":config["DASHBOARD_USERNAME"], "password":config["DASHBOARD_PASSWORD"]}).status_code == 200
        result = client.get("/api/dashboard")
        assert result.status_code == 200, "Live database query failed"
        for forbidden in ["password_hash", "token_hash", "DASHBOARD_DATABASE_URL"]:
            assert forbidden not in result.text
        print("Live dashboard statistics:", json.dumps(result.json()["stats"]))
        password = "dashboard-test-" + secrets.token_urlsafe(16)
        hashed = client.post("/api/password-hash", json={"password":password})
        assert hashed.status_code == 200
        payload = {"hash":hashed.json()["password_hash"],"password":password}
        checked = subprocess.run(
            ["/opt/documate-auth/.venv/bin/python", "-c",
             'import sys,json; sys.path.insert(0,"/opt/documate-auth"); from app.security import verify_password; data=json.load(sys.stdin); assert verify_password(data["hash"],data["password"]); print("verified")'],
            input=json.dumps(payload), text=True, capture_output=True,
        )
        assert checked.returncode == 0 and checked.stdout.strip() == "verified"
        after_hash = client.get("/api/dashboard").json()
        for field in ["stats","users","sessions"]:
            assert result.json()[field] == after_hash[field]
        print("Hash accepted by deployed auth-service; database unchanged")
        assert client.get("/api/dashboard", params={"q":"no_such_user_permission_check"}).json()["users"]["total"] == 0
        assert client.get("/api/dashboard", params={"page_size":1,"user_page":2}).status_code == 200
        first = result.json()["updated_at"]
        second = client.get("/api/dashboard").json()["updated_at"]
        assert first != second
        for method in ["POST", "PUT", "PATCH", "DELETE"]:
            assert client.request(method,"/api/dashboard").status_code == 405
        assert client.post("/api/logout").status_code == 200
        assert client.get("/api/dashboard").status_code == 401
        print("Live login, refresh, search, pagination, write rejection and logout passed")


if __name__ == "__main__":
    main()
