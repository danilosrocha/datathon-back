"""Decide como o backend lê o schema `externo`: SQL direto ou API REST do Supabase."""

import base64
import json
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.engine import make_url

Mode = Literal["sql", "rest"]
KeyRole = Literal["privileged", "public", "unknown", "missing"]


def supabase_project_ref(supabase_url: str) -> str | None:
    host = (make_url_host(supabase_url) or "").lower()
    if host.endswith(".supabase.co") and host.count(".") == 2:
        return host.split(".")[0]
    return None


def make_url_host(url: str) -> str | None:
    from urllib.parse import urlparse

    return urlparse(url).hostname if url else None


def database_project_ref(database_url: str) -> str | None:
    """Identifica o projeto Supabase no DATABASE_URL (conexão direta ou pooler)."""
    try:
        url = make_url(database_url)
    except Exception:
        return None
    host = (url.host or "").lower()
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return host.split(".")[1]
    if host.endswith(".pooler.supabase.com") and url.username and "." in url.username:
        return url.username.split(".", 1)[1]
    return None


def key_role(key: str) -> KeyRole:
    """Classifica a chave da API sem validá-la: só `privileged` pode ler o schema `externo`."""
    if not key:
        return "missing"
    if key.startswith("sb_secret_"):
        return "privileged"
    if key.startswith("sb_publishable_"):
        return "public"
    parts = key.split(".")
    if len(parts) == 3:
        try:
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            role = json.loads(base64.urlsafe_b64decode(payload)).get("role")
        except (ValueError, UnicodeDecodeError):
            return "unknown"
        if role == "service_role":
            return "privileged"
        if role in {"anon", "authenticated"}:
            return "public"
    return "unknown"


@dataclass(frozen=True)
class AccessPlan:
    mode: Mode
    usable: bool
    reason: str


def resolve_access_mode(
    *, database_url: str, supabase_url: str, api_key: str, forced: str = "auto"
) -> AccessPlan:
    """Prioriza SQL direto quando o DATABASE_URL é o Postgres do Supabase; senão usa REST."""
    privileged = key_role(api_key) == "privileged"
    if forced == "sql":
        return AccessPlan("sql", True, "modo forçado por EXTERNAL_DATA_MODE=sql")
    if forced == "rest":
        ok = bool(supabase_url) and privileged
        return AccessPlan("rest", ok, "modo forçado por EXTERNAL_DATA_MODE=rest" if ok else
                          "REST exige SUPABASE_URL e chave com privilégio de serviço")  # fmt: skip

    db_ref, api_ref = database_project_ref(database_url), supabase_project_ref(supabase_url)
    if db_ref and (api_ref is None or api_ref == db_ref):
        return AccessPlan("sql", True, f"DATABASE_URL aponta para o projeto Supabase {db_ref}")
    if api_ref:
        if privileged:
            return AccessPlan("rest", True, "DATABASE_URL não é o Supabase; usando a API REST")
        return AccessPlan(
            "rest",
            False,
            "DATABASE_URL não é o Supabase e a chave da API não tem privilégio de serviço "
            "(use a chave secreta no backend, ou defina DATABASE_URL do Supabase)",
        )
    return AccessPlan("sql", True, "sem API do Supabase configurada; usando DATABASE_URL")
