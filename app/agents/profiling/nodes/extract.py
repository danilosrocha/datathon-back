"""Extrator (LLM rápido): fatos do texto livre do usuário, com evidência literal."""

from datetime import UTC, datetime
from functools import cache

from pydantic import BaseModel

from app.agents import llm
from app.agents.profiling.state import ProfileState
from app.agents.prompts import load_prompt
from app.config import get_settings
from app.domain.fact_keys import FactKey, fact_keys
from app.domain.facts import Fact, FactSource, FactStatus

# Confiança de fato declarado em texto livre (peso de "observado" em CONTRATOS_API §9.5).
TEXT_CONFIDENCE = 0.8


class ExtractedFact(BaseModel):
    key: str
    value: bool | int | float | str | list[str]
    evidence: str


class Extraction(BaseModel):
    facts: list[ExtractedFact]


def _describe(spec: FactKey) -> str:
    kind = f"{spec.type}: {', '.join(spec.options)}" if spec.options else spec.type
    pattern = f", formato {spec.pattern}" if spec.pattern else ""
    return f"- {spec.key} ({kind}{pattern}) — {spec.label}"


@cache
def extractor_system() -> str:
    """Prompt + lista de chaves extraíveis: estável, então fica no system e entra no cache."""
    keys = "\n".join(_describe(s) for s in fact_keys().values() if s.extractable)
    return f"{load_prompt('profiling', 'extractor')}\n\n## Chaves permitidas\n\n{keys}\n"


async def extract(state: ProfileState) -> dict:
    messages = state.get("messages", [])
    if not messages or messages[-1].type != "human":
        return {}
    result = await llm.parse(
        model=get_settings().llm_model_fast,
        system=extractor_system(),
        messages=llm.to_api_messages(messages),
        output_format=Extraction,
    )
    if result is None:
        return {}
    now = datetime.now(UTC)
    facts = {}
    for f in result.facts:
        spec = fact_keys().get(f.key)
        # Chave inexistente, não extraível ou valor fora do tipo → descartado.
        if spec is None or not spec.extractable:
            continue
        try:
            facts[f.key] = Fact(
                key=f.key,
                value=f.value,
                status=FactStatus.OBSERVADO,
                source=FactSource.USUARIO_TEXTO,
                confidence=TEXT_CONFIDENCE,
                evidence=f.evidence,
                updated_at=now,
                updated_by="agente:extrator",
            )
        except ValueError:
            continue
    return {"facts": facts}
