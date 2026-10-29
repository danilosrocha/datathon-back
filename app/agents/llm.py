"""Único ponto de chamada ao LLM: Anthropic (padrão) ou OpenRouter (LLM_PROVIDER=openrouter)."""

import json
import re
from collections.abc import AsyncIterator
from functools import cache
from typing import Literal

import httpx
from anthropic import AsyncAnthropic
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ValidationError

from app.config import get_settings

Effort = Literal["low", "medium"]
REFUSAL = "Desculpe, não consigo ajudar com isso por aqui. Posso seguir com outra pergunta?"
# Fallback do servidor em recusa: só nos modelos que o aceitam (Haiku não tem).
FALLBACK_BETA = "server-side-fallback-2026-07-01"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
# Alguns modelos devolvem o JSON dentro de bloco de código mesmo com response_format.
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


@cache
def get_client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=get_settings().anthropic_api_key, timeout=60.0, max_retries=2)


@cache
def get_openrouter() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=OPENROUTER_URL,
        headers={"Authorization": f"Bearer {get_settings().openrouter_api_key}"},
        timeout=60.0,
        transport=httpx.AsyncHTTPTransport(retries=2),
    )


def _use_openrouter() -> bool:
    return get_settings().llm_provider == "openrouter"


# A API exige que a conversa comece pelo usuário e que a mensagem de sistema do meio venha logo
# depois de uma mensagem do usuário. Turnos sem fala nova (edição de card) usam este marcador.
CONVERSATION_START = "<evento>início da conversa</evento>"
PROFILE_UPDATED = "<evento>o usuário atualizou o perfil pelos cards</evento>"


def to_api_messages(history: list[BaseMessage], context: str | None = None) -> list[dict]:
    """Histórico do grafo → mensagens da API. Texto do usuário vai delimitado (é dado, não ordem);
    o estado volátil do caso entra no fim como mensagem de sistema para não quebrar o cache."""
    messages = []
    for msg in history:
        if msg.type == "human":
            content = f"<mensagem_usuario>\n{msg.content}\n</mensagem_usuario>"
            messages.append({"role": "user", "content": content})
        elif msg.type == "ai":
            messages.append({"role": "assistant", "content": msg.content})
    if messages and messages[0]["role"] == "assistant":
        messages.insert(0, {"role": "user", "content": CONVERSATION_START})
    if not messages or messages[-1]["role"] != "user":
        messages.append(
            {"role": "user", "content": PROFILE_UPDATED if messages else CONVERSATION_START}
        )
    if context:
        messages.append({"role": "system", "content": context})
    return messages


def _system(prompt: str) -> list[dict]:
    return [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]


def _fallback(model: str) -> dict:
    """Parâmetros de fallback do servidor para o modelo; vazio quando ele não aceita."""
    if "haiku" in model:
        return {}
    return {"betas": [FALLBACK_BETA], "fallbacks": "default"}


async def parse[T: BaseModel](
    *,
    model: str,
    system: str,
    messages: list[dict],
    output_format: type[T],
    effort: Effort = "low",
    max_tokens: int = 2048,
) -> T | None:
    """Saída estruturada. Devolve None em recusa (o chamador segue sem o resultado)."""
    if _use_openrouter():
        return await _openrouter_parse(
            model=model, system=system, messages=messages, output_format=output_format,
            effort=effort, max_tokens=max_tokens,
        )  # fmt: skip
    response = await get_client().beta.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=_system(system),
        messages=messages,
        output_format=output_format,
        output_config={"effort": effort},
        **_fallback(model),
    )
    if response.stop_reason == "refusal":
        return None
    return output_format.model_validate(response.parsed_output)


async def stream_text(
    *,
    model: str,
    system: str,
    messages: list[dict],
    effort: Effort = "low",
    max_tokens: int = 1024,
) -> AsyncIterator[str]:
    """Texto exibido ao usuário, em pedaços. Em recusa, emite o texto de template."""
    if _use_openrouter():
        async for text in _openrouter_stream(
            model=model, system=system, messages=messages, effort=effort, max_tokens=max_tokens
        ):
            yield text
        return
    async with get_client().beta.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=_system(system),
        messages=messages,
        output_config={"effort": effort},
        **_fallback(model),
    ) as stream:
        async for text in stream.text_stream:
            yield text
        final = await stream.get_final_message()
    if final.stop_reason == "refusal":
        yield REFUSAL


# --- OpenRouter (API compatível com OpenAI) ---------------------------------------------------
# Sem prompt caching, fallback de servidor nem saída estruturada nativa da Anthropic: o schema vai
# em response_format e a resposta é validada aqui; JSON inválido conta como recusa.


def _openrouter_body(
    model: str, system: str, messages: list[dict], effort: Effort, max_tokens: int
) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, *messages],
        "reasoning": {"effort": effort},
    }


async def _openrouter_parse[T: BaseModel](
    *,
    model: str,
    system: str,
    messages: list[dict],
    output_format: type[T],
    effort: Effort,
    max_tokens: int,
) -> T | None:
    body = _openrouter_body(model, system, messages, effort, max_tokens)
    schema = {"name": output_format.__name__, "schema": output_format.model_json_schema()}
    body["response_format"] = {"type": "json_schema", "json_schema": schema}
    response = await get_openrouter().post("/chat/completions", json=body)
    response.raise_for_status()
    choice = response.json()["choices"][0]
    content = choice["message"].get("content") or ""
    if choice.get("finish_reason") == "content_filter" or not content:
        return None
    try:
        return output_format.model_validate_json(_FENCE.sub("", content.strip()))
    except ValidationError:
        return None


async def _openrouter_stream(
    *, model: str, system: str, messages: list[dict], effort: Effort, max_tokens: int
) -> AsyncIterator[str]:
    body = _openrouter_body(model, system, messages, effort, max_tokens) | {"stream": True}
    refused = False
    async with get_openrouter().stream("POST", "/chat/completions", json=body) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            # Linhas ": ..." são keep-alive do OpenRouter; "[DONE]" fecha o stream.
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            chunk = json.loads(line.removeprefix("data: "))
            if "error" in chunk:
                raise RuntimeError(f"OpenRouter: {chunk['error'].get('message', chunk['error'])}")
            for choice in chunk.get("choices", []):
                if text := choice.get("delta", {}).get("content"):
                    yield text
                refused |= choice.get("finish_reason") == "content_filter"
    if refused:
        yield REFUSAL
