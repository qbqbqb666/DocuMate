import importlib.util
import importlib
import os
import sys
from pathlib import Path
import secrets
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.database import create_session_factory
from app.main import create_app
from app.security import hash_password, verify_password
from test_auth import service


@pytest.mark.skipif(not os.getenv("DOCUMATE_TEST_DATABASE_URL"), reason="Requires isolated PostgreSQL test database")
def test_upgrade_preserves_data_readonly_permissions_and_code_rollback(service, tmp_path):
    url = os.environ["DOCUMATE_TEST_DATABASE_URL"]
    assert make_url(url).database == "documate_email_test"
    admin = create_engine(url)
    schema = "migration_" + secrets.token_hex(8)
    role = "readonly_" + secrets.token_hex(8)
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
        db.execute(text('CREATE ROLE documate_auth NOLOGIN'))
        db.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
        db.execute(text(f'GRANT ALL ON SCHEMA "{schema}" TO documate_auth'))
        db.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
    test_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    engine = create_engine(test_url)
    original = subprocess.check_output(["git", "show", "HEAD:server/auth-service/app/database.py"], text=True)
    # Old metadata creates the exact pre-upgrade tables in a separate test schema.
    namespace = {"__name__": "legacy_database"}
    exec(compile(original, "legacy_database.py", "exec"), namespace)
    namespace["Base"].metadata.create_all(engine)
    with engine.begin() as db:
        db.execute(text("ALTER TABLE users OWNER TO documate_auth"))
        db.execute(text("ALTER TABLE refresh_sessions OWNER TO documate_auth"))
    password_hash = hash_password("legacy-secret")
    with engine.begin() as db:
        db.execute(text("INSERT INTO users (id, username, password_hash, status, seen_welcome, created_at) "
                        "VALUES (7, 'legacy_user', :password, 'active', TRUE, NOW())"), {"password": password_hash})
        db.execute(text("INSERT INTO refresh_sessions (id, user_id, token_hash, expires_at, created_at) "
                        "VALUES (11, 7, :token, NOW() + INTERVAL '1 day', NOW())"), {"token": "a" * 64})
        db.execute(text(f'GRANT SELECT ON users, refresh_sessions TO "{role}"'))
        before_user = dict(db.execute(text("SELECT * FROM users WHERE id=7")).mappings().one())
        before_session = dict(db.execute(text("SELECT * FROM refresh_sessions WHERE id=11")).mappings().one())
    migration = Path(__file__).parents[1] / "migrations/005_email_auth.sql"
    try:
        with engine.connect() as connection:
            raw = connection.connection.driver_connection
            raw.autocommit = True
            with raw.cursor() as cursor:
                cursor.execute(migration.read_text())
                cursor.execute(migration.read_text())
            raw.autocommit = False
        with engine.begin() as db:
            after = dict(db.execute(text("SELECT * FROM users WHERE id=7")).mappings().one())
            assert {key: after[key] for key in before_user} == before_user
            assert after["email"] is None and after["email_verified_at"] is None and after["auth_version"] == 0
            assert dict(db.execute(text("SELECT * FROM refresh_sessions WHERE id=11")).mappings().one()) == before_session
            assert verify_password(after["password_hash"], "legacy-secret")
            assert db.execute(text("SELECT tableowner FROM pg_tables WHERE schemaname=current_schema() "
                                   "AND tablename='email_challenges'")).scalar() == "documate_auth"
            db.execute(text(f'SET LOCAL ROLE "{role}"'))
            assert db.execute(text("SELECT COUNT(*) FROM users")).scalar() == 1
            assert not db.execute(text("SELECT has_table_privilege(current_user, 'users', 'INSERT')")).scalar()
            assert not db.execute(text("SELECT has_table_privilege(current_user, 'email_challenges', 'SELECT')")).scalar()
        sessions = create_session_factory(test_url)
        with TestClient(create_app(service[3], sessions, mailer=service[2])) as api:
            assert api.post("/api/auth/login", json={"username": "legacy_user", "password": "legacy-secret"}).status_code == 200
        sessions.kw["bind"].dispose()
        # Rolling the application back keeps additive schema and new data intact.
        legacy = tmp_path / "legacy_auth"
        legacy.mkdir()
        for filename in ["__init__.py", "main.py", "database.py", "schemas.py", "config.py", "security.py"]:
            (legacy / filename).write_bytes(subprocess.check_output([
                "git", "show", "HEAD:server/auth-service/app/" + filename]))
        spec = importlib.util.spec_from_file_location("migration_legacy_auth", legacy / "__init__.py",
                                                     submodule_search_locations=[str(legacy)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = package
        spec.loader.exec_module(package)
        old_main = importlib.import_module("migration_legacy_auth.main")
        old_sessions = namespace["sessionmaker"](bind=engine, expire_on_commit=False)
        with TestClient(old_main.create_app(service[3], old_sessions)) as old_api:
            logged_in = old_api.post("/api/auth/login", json={"username": "legacy_user", "password": "legacy-secret"})
            assert logged_in.status_code == 200
            refresh = old_api.post("/api/auth/refresh", json={"refresh_token": logged_in.json()["refresh_token"]})
            assert refresh.status_code == 200

    finally:
        engine.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            db.execute(text(f'DROP ROLE "{role}"'))
            db.execute(text('DROP ROLE documate_auth'))
        admin.dispose()
