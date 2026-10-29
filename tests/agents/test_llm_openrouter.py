import json

import httpx
import pytest

from app.agents import llm
from app.agents.profiling.nodes.explain import Explanation
from app.agents.profiling.nodes.extract import Extraction
from app.config import get_settings

MESSAGES = [{"role": "user", "content": "Tenho uma padaria"}, {"role": "system", "content": "ctx"}]


@pytest.fixture
def openrouter(monkeypatch):
    """LLM_PROVIDER=openrouter com transporte falso: guarda os corpos enviados, nenhuma rede."""
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    get_settings.cache_clear()
    sent: list[dict] = []
    reply: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return reply["response"]

    client = httpx.AsyncClient(base_url=llm.OPENROUTER_URL, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(llm, "get_openrouter", lambda: client)
    yield sent, reply
    get_settings.cache_clear()


def completion(content: str | None, finish_reason: str = "stop") -> httpx.Response:
    choice = {"message": {"content": content}, "finish_reason": finish_reason}
    return httpx.Response(200, json={"choices": [choice]})


def stream(*chunks: dict) -> httpx.Response:
    lines = [": OPENROUTER PROCESSING"] + [f"data: {json.dumps(c)}" for c in chunks]
    return httpx.Response(200, text="\n\n".join([*lines, "data: [DONE]"]) + "\n\n")


async def test_parse_sends_schema_and_validates(openrouter) -> None:
    sent, reply = openrouter
    payload = {"facts": [{"key": "cnae_principal", "value": "1091-1/02", "evidence": "padaria"}]}
    reply["response"] = completion(json.dumps(payload))

    result = await llm.parse(
        model="google/gemini-x", system="sys", messages=MESSAGES, output_format=Extraction
    )

    assert result.facts[0].value == "1091-1/02"
    body = sent[0]
    assert body["model"] == "google/gemini-x"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["messages"][1:] == MESSAGES
    assert body["response_format"]["json_schema"]["schema"] == Extraction.model_json_schema()
    assert body["reasoning"] == {"effort": "low"}


async def test_parse_accepts_fenced_json(openrouter) -> None:
    _, reply = openrouter
    reply["response"] = completion('```json\n{"texto": "ok"}\n```')
    result = await llm.parse(model="m", system="s", messages=MESSAGES, output_format=Explanation)
    assert result.texto == "ok"


@pytest.mark.parametrize(
    "response",
    [completion("não é json"), completion(None), completion('{"texto": "x"}', "content_filter")],
)
async def test_parse_invalid_or_refused_returns_none(openrouter, response) -> None:
    _, reply = openrouter
    reply["response"] = response
    assert (
        await llm.parse(model="m", system="s", messages=MESSAGES, output_format=Explanation) is None
    )


async def test_parse_http_error_raises(openrouter) -> None:
    _, reply = openrouter
    reply["response"] = httpx.Response(401, json={"error": {"message": "No auth"}})
    with pytest.raises(httpx.HTTPStatusError):
        await llm.parse(model="m", system="s", messages=MESSAGES, output_format=Explanation)


async def test_stream_text_yields_deltas(openrouter) -> None:
    sent, reply = openrouter
    reply["response"] = stream(
        {"choices": [{"delta": {"content": "Qual é "}}]},
        {"choices": [{"delta": {"content": "a atividade?"}, "finish_reason": "stop"}]},
    )
    chunks = [t async for t in llm.stream_text(model="m", system="s", messages=MESSAGES)]
    assert "".join(chunks) == "Qual é a atividade?"
    assert sent[0]["stream"] is True


async def test_stream_text_refusal_emits_template(openrouter) -> None:
    _, reply = openrouter
    reply["response"] = stream({"choices": [{"delta": {}, "finish_reason": "content_filter"}]})
    chunks = [t async for t in llm.stream_text(model="m", system="s", messages=MESSAGES)]
    assert chunks == [llm.REFUSAL]


async def test_stream_text_midstream_error_raises(openrouter) -> None:
    _, reply = openrouter
    reply["response"] = stream({"error": {"message": "Provider returned error"}})
    with pytest.raises(RuntimeError, match="Provider returned error"):
        [t async for t in llm.stream_text(model="m", system="s", messages=MESSAGES)]
