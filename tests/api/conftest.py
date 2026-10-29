import pytest
from fastapi.testclient import TestClient

from app.agents import llm
from app.main import create_app
from tests.agents.conftest import FakeLLM


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """App com LLM falso: nenhum teste chama a API real da Anthropic."""
    fake = FakeLLM()
    monkeypatch.setattr(llm, "parse", fake.parse)
    monkeypatch.setattr(llm, "stream_text", fake.stream_text)
    return TestClient(create_app())
