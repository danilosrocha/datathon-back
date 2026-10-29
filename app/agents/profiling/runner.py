"""Executa um turno do grafo de perfilamento e publica os eventos de UI (CONTRATOS_API §7).

Recebe `publish(case_id, event, data)` para não depender da camada de API."""

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.domain.decision import Decision
from app.domain.facts import Fact
from app.engine.catalog import Catalog
from app.engine.profile_cards import fact_card

Publish = Callable[[str, str, Any], Any]
OnDecision = Callable[[str, Decision, dict[str, Fact]], Awaitable[None] | None]


def thread_config(case_id: str) -> dict:
    return {"configurable": {"thread_id": f"profile:{case_id}"}}


def _avatar(decision: Decision | None) -> str:
    if decision is None:
        return "ouvindo"
    if decision.eligibility.status == "inelegivel":
        return "preocupado"
    return "explicando" if decision.offers and decision.status == "conclusiva" else "ouvindo"


class TurnRunner:
    def __init__(
        self, graph: CompiledStateGraph, catalog: Catalog, publish: Publish, on_decision: OnDecision
    ) -> None:
        self.graph, self.catalog = graph, catalog
        self.publish, self.on_decision = publish, on_decision

    async def state(self, case_id: str) -> dict:
        return (await self.graph.aget_state(thread_config(case_id))).values

    async def run(self, case_id: str, turn_id: str, update: dict) -> None:
        publish, config = self.publish, thread_config(case_id)
        before = await self.state(case_id)
        message_id = f"msg_{turn_id}"
        publish(case_id, "turn.started", {"turn_id": turn_id})
        publish(case_id, "avatar.state", {"state": "pensando"})
        try:
            async for chunk in self.graph.astream(
                {"case_id": case_id, **update}, config, stream_mode="custom"
            ):
                if chunk.get("event") == "message.delta":
                    publish(
                        case_id, "message.delta", {"message_id": message_id, "delta": chunk["text"]}
                    )
            after = await self.state(case_id)
            await self._publish_changes(case_id, message_id, before, after)
        except Exception as error:  # o turno falha, o caso continua; o front pode reenviar
            publish(
                case_id, "error", {"code": "turn_failed", "message": str(error), "retryable": True}
            )
        finally:
            publish(case_id, "turn.completed", {"turn_id": turn_id})

    async def _publish_changes(
        self, case_id: str, message_id: str, before: dict, after: dict
    ) -> None:
        publish = self.publish
        messages = after.get("messages", [])
        if messages and messages[-1].type == "ai":
            text = messages[-1].content
            publish(
                case_id,
                "message.completed",
                {"message_id": message_id, "role": "assistant", "text": text},
            )

        old, new = before.get("facts", {}), after.get("facts", {})
        changed = [new[k] for k in sorted(new) if old.get(k) != new[k]]
        if changed:
            cards = [fact_card(f, self.catalog) for f in changed]
            publish(case_id, "profile.patch", {"upsert": cards, "remove": []})

        question = after.get("question")
        publish(case_id, "question", question.model_dump(mode="json") if question else None)

        decision: Decision | None = after.get("decision")
        previous: Decision | None = before.get("decision")
        if decision is not None:
            if previous is None or previous.eligibility != decision.eligibility:
                publish(
                    case_id, "eligibility.updated", decision.eligibility.model_dump(mode="json")
                )
            if decision.offers:
                result = self.on_decision(case_id, decision, new)
                if inspect.isawaitable(result):
                    await result
        publish(case_id, "avatar.state", {"state": _avatar(decision)})
