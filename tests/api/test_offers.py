from fastapi.testclient import TestClient

from app.engine.decide import decide
from app.main import create_app
from tests.engine.conftest import NO_IMPEDIMENTS, make_facts

H = {"X-Case-Token": "tok"}
URL = "/api/v1/cases/c1/offers"


def make_client() -> TestClient:
    app = create_app()
    facts = make_facts(**NO_IMPEDIMENTS, possui_estoque=True)
    offers = decide(facts, app.state.catalog, app.state.graph).offers
    app.state.offers.save("c1", "tok", offers, facts)
    return TestClient(app)


def test_cards_and_customize_flow() -> None:
    client = make_client()
    cards = client.get(f"{URL}/of_1/coverage-cards", headers=H).json()
    assert {c["status"] for c in cards} >= {"incluida", "disponivel"}

    r = client.post(
        f"{URL}/of_1/customize",
        headers=H,
        json={"coverages": [{"code": "TUMULTOS_GREVES_LOCAUTES", "active": True}]},
    )
    assert r.status_code == 200 and r.json()["offer_id"] == "of_1_p"
    # Cumulativo: o próximo clique vale sobre a personalizada.
    r = client.post(
        f"{URL}/of_1_p/customize",
        headers=H,
        json={"coverages": [{"code": "VENDAVAL_GRANIZO", "active": False}]},
    )
    assert len(r.json()["diff_vs_best"]) == 2
    assert client.get(f"{URL}/of_1_p", headers=H).json()["base_offer_id"] == "of_1"

    r = client.post(f"{URL}/of_1/customize", headers=H, json={"reset": True})
    assert r.json()["kind"] == "melhor_ajuste"
    assert client.get(f"{URL}/of_1_p", headers=H).status_code == 404


def test_violations_and_token() -> None:
    client = make_client()
    r = client.post(
        f"{URL}/of_1/customize",
        headers=H,
        json={"coverages": [{"code": "DANOS_ELETRICOS", "active": False}]},
    )
    violation = r.json()["violations"][0]
    assert r.status_code == 422
    assert (violation["code"], violation["coverage_code"]) == (
        "fixa_nao_removivel",
        "DANOS_ELETRICOS",
    )
    assert client.get(f"{URL}/of_1", headers={"X-Case-Token": "x"}).status_code == 404
