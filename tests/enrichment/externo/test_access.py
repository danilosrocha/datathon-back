import pytest

from app.enrichment.externo.access import (
    database_project_ref,
    key_role,
    resolve_access_mode,
    supabase_project_ref,
)

REF = "ewlkkilgtefxchthbaiw"
LOCAL = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
DIRECT = f"postgresql+psycopg://postgres:pw@db.{REF}.supabase.co:5432/postgres"
POOLER = f"postgresql+psycopg://postgres.{REF}:pw@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
URL = f"https://{REF}.supabase.co"


def test_project_ref_from_api_url():
    assert supabase_project_ref(URL) == REF
    assert supabase_project_ref("") is None
    assert supabase_project_ref("http://localhost:54321") is None


@pytest.mark.parametrize("dsn", [DIRECT, POOLER])
def test_project_ref_from_database_url(dsn):
    assert database_project_ref(dsn) == REF


def test_local_database_has_no_project_ref():
    assert database_project_ref(LOCAL) is None


@pytest.mark.parametrize(
    ("key", "role"),
    [
        ("sb_secret_abc", "privileged"),
        ("sb_publishable_abc", "public"),
        ("", "missing"),
        ("not-a-jwt", "unknown"),
    ],
)
def test_key_role_for_new_style_keys(key, role):
    assert key_role(key) == role


def _jwt(role: str) -> str:
    import base64
    import json

    def enc(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    return f"{enc({'alg': 'HS256'})}.{enc({'role': role})}.sig"


def test_key_role_for_legacy_jwt_keys():
    assert key_role(_jwt("service_role")) == "privileged"
    assert key_role(_jwt("anon")) == "public"


def test_same_supabase_database_uses_direct_sql():
    plan = resolve_access_mode(database_url=POOLER, supabase_url=URL, api_key="sb_secret_x")
    assert plan.mode == "sql"


def test_different_database_with_supabase_api_uses_rest():
    plan = resolve_access_mode(database_url=LOCAL, supabase_url=URL, api_key="sb_secret_x")
    assert plan.mode == "rest"
    assert plan.usable


def test_rest_with_public_key_is_not_usable_and_says_why():
    plan = resolve_access_mode(database_url=LOCAL, supabase_url=URL, api_key="sb_publishable_x")
    assert plan.mode == "rest"
    assert not plan.usable
    assert "privilégio" in plan.reason


def test_without_supabase_api_falls_back_to_sql():
    plan = resolve_access_mode(database_url=LOCAL, supabase_url="", api_key="")
    assert plan.mode == "sql"


def test_forced_mode_wins():
    plan = resolve_access_mode(
        database_url=LOCAL, supabase_url=URL, api_key="sb_publishable_x", forced="sql"
    )
    assert plan.mode == "sql"
    assert plan.usable
