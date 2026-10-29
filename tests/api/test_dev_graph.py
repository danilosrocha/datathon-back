from fastapi.testclient import TestClient

from tests.api.test_cases import BASE, NO_IMPEDIMENTS, new_case


def test_confirmed_fact_feeds_graph_after_publish(client) -> None:
    case_id, h = new_case(client)
    client.put(f"{BASE}/{case_id}/facts/cnae_principal", headers=h, json={"value": "1091-1/02"})
    for key in NO_IMPEDIMENTS:
        client.put(f"{BASE}/{case_id}/facts/{key}", headers=h, json={"value": False})
    client.put(f"{BASE}/{case_id}/facts/possui_estoque", headers=h, json={"value": True})

    r = client.post("/api/v1/dev/graph/rebuild")
    body = r.json()
    assert body["status"] == "rascunho" and body["kg_version"] == 2
    assert body["changed_edges"] == [
        {
            "src": "CNAE:1091-1/02",
            "dst": "possui_estoque",
            "before": [1.0, 1.0],
            "after": [2.0, 1.0],
        }
    ]
    # Rascunho não muda a versão em uso.
    assert client.get("/health?deep=1").json()["kg_version"] == 1

    assert client.post("/api/v1/dev/graph/publish/2").json()["status"] == "publicada"
    assert client.get("/health?deep=1").json()["kg_version"] == 2
    assert client.post("/api/v1/dev/graph/publish/99").status_code == 404


def test_health() -> None:
    from app.main import create_app

    assert TestClient(create_app()).get("/health").json() == {"status": "ok"}


def test_psycopg_conninfo_encodes_password() -> None:
    from psycopg.conninfo import conninfo_to_dict

    from app.main import psycopg_conninfo

    url = "postgresql+psycopg://user:p%25ss@host:5432/db"  # senha "p%ss" já codificada
    assert conninfo_to_dict(psycopg_conninfo(url))["password"] == "p%ss"
    raw = "postgresql://user:a£b%c@host:5432/db"  # senha crua com caracteres especiais
    assert conninfo_to_dict(psycopg_conninfo(raw))["password"] == "a£b%c"
