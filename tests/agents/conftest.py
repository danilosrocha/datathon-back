import json
from pathlib import Path

import pytest

from app.agents import llm

FIXTURES = Path(__file__).parents[1] / "fixtures" / "llm"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeLLM:
    """Substitui llm.parse / llm.stream_text: respostas prontas (fixtures) e registro das chamadas.
    Nenhum teste chama a API real da Anthropic."""

    def __init__(self) -> None:
        self.parsed: dict[type, object] = {}
        self.text = "Pergunta de teste?"
        self.calls: list[dict] = []

    def respond(self, output_format: type, fixture: str) -> None:
        self.parsed[output_format] = output_format.model_validate(load_fixture(fixture))

    async def parse(self, *, output_format, **kwargs):
        self.calls.append({"output_format": output_format, **kwargs})
        return self.parsed.get(output_format)

    async def stream_text(self, **kwargs):
        self.calls.append(kwargs)
        for word in self.text.split(" "):
            yield word + " "


@pytest.fixture
def fake_llm(monkeypatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr(llm, "parse", fake.parse)
    monkeypatch.setattr(llm, "stream_text", fake.stream_text)
    return fake
