import json

from fastapi.testclient import TestClient

BASE = "/api/v1/cases"
NO_IMPEDIMENTS = (
    "localizacao_restrita",
    "imovel_tombado_desapropriado_condenado",
    "imovel_em_obra",
    "parede_externa_combustivel",
    "objeto_ja_segurado_bb",
)


def new_case(client: TestClient) -> tuple[str, dict]:
    r = client.post(BASE, json={"consent": True, "channel": "web"})
    assert r.status_code == 201
    body = r.json()
    return body["case_id"], {"X-Case-Token": body["case_token"]}


def events(client: TestClient, case_id: str, headers: dict, after: int = 0) -> list[dict]:
    """Lê o histórico do SSE (follow=false) e devolve [{id, event, data}]."""
    h = headers | ({"Last-Event-ID": str(after)} if after else {})
    text = client.get(f"{BASE}/{case_id}/events?follow=false", headers=h).text
    parsed = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            parsed.append(
                {
                    "id": int(fields["id"]),
                    "event": fields["event"],
                    "data": json.loads(fields["data"]),
                }
            )
    return parsed


def test_create_case_sends_greeting_and_first_question(client) -> None:
    case_id, h = new_case(client)
    evs = events(client, case_id, h)
    assert [e["event"] for e in evs] == ["message.completed", "question", "avatar.state"]
    assert evs[1]["data"]["fact_key"] == "cnae_principal"
    snapshot = client.get(f"{BASE}/{case_id}", headers=h).json()
    assert snapshot["status"] == "em_perfilamento"
    assert snapshot["messages"][0]["role"] == "assistant"


def test_consent_and_token_required(client) -> None:
    assert client.post(BASE, json={"consent": False}).status_code == 422
    case_id, _ = new_case(client)
    assert client.get(f"{BASE}/{case_id}", headers={"X-Case-Token": "errado"}).status_code == 404


def test_message_is_202_and_sse_delivers_turn_in_order(client) -> None:
    case_id, h = new_case(client)
    r = client.post(f"{BASE}/{case_id}/messages", headers=h, json={"text": "tenho uma padaria"})
    assert r.status_code == 202 and r.json()["turn_id"].startswith("turn_")

    evs = events(client, case_id, h)
    ids = [e["id"] for e in evs]
    assert ids == sorted(ids) == list(range(1, len(ids) + 1))
    names = [e["event"] for e in evs[3:]]
    assert names[0] == "turn.started" and names[-1] == "turn.completed"
    assert "message.delta" in names and "message.completed" in names
    assert names.index("message.delta") < names.index("message.completed")
    # Last-Event-ID: só o que veio depois.
    assert [e["id"] for e in events(client, case_id, h, after=3)] == ids[3:]


def test_fact_commands(client) -> None:
    case_id, h = new_case(client)
    assert (
        client.put(
            f"{BASE}/{case_id}/facts/delivery", headers=h, json={"value": "talvez"}
        ).status_code
        == 422
    )
    assert (
        client.put(f"{BASE}/{case_id}/facts/delivery", headers=h, json={"value": True}).status_code
        == 202
    )
    card = next(
        c
        for c in client.get(f"{BASE}/{case_id}", headers=h).json()["cards"]
        if c["key"] == "delivery"
    )
    assert (card["status"], card["source"], card["display_value"]) == (
        "confirmado",
        "usuario_resposta",
        "Sim",
    )

    assert client.delete(f"{BASE}/{case_id}/facts/delivery", headers=h).status_code == 202
    card = next(
        c
        for c in client.get(f"{BASE}/{case_id}", headers=h).json()["cards"]
        if c["key"] == "delivery"
    )
    assert card["status"] == "rejeitado" and card["value"] is None
    assert client.post(f"{BASE}/{case_id}/facts/inexistente/confirm", headers=h).status_code == 404


def test_recommendation_offers_and_personalizar(client) -> None:
    case_id, h = new_case(client)
    assert client.get(f"{BASE}/{case_id}/recommendation", headers=h).status_code == 404
    client.put(f"{BASE}/{case_id}/facts/cnae_principal", headers=h, json={"value": "1091-1/02"})
    for key in NO_IMPEDIMENTS:
        client.put(f"{BASE}/{case_id}/facts/{key}", headers=h, json={"value": False})

    rec = client.get(f"{BASE}/{case_id}/recommendation", headers=h).json()
    assert rec["status"] == "conclusiva" and rec["offers"][0]["offer_id"] == "of_1"
    assert any(e["event"] == "recommendation.ready" for e in events(client, case_id, h))

    graph = client.get(f"{BASE}/{case_id}/explain-graph?offer_id=of_1", headers=h).json()
    assert {n["type"] for n in graph["nodes"]} >= {"cobertura", "regra", "necessidade"}

    # As ofertas da recomendação ficam disponíveis para Personalizar.
    r = client.post(
        f"{BASE}/{case_id}/offers/of_1/customize",
        headers=h,
        json={"coverages": [{"code": "INCENDIO_RAIO_EXPLOSAO_FUMACA", "active": False}]},
    )
    assert r.status_code == 422


def test_review_request(client) -> None:
    case_id, h = new_case(client)
    r = client.post(f"{BASE}/{case_id}/review-request", headers=h, json={"reason": "discordo"})
    assert r.status_code == 202
