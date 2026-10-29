"""Serializador do checkpointer: libera só os tipos do domínio guardados no estado do grafo."""

import inspect
from enum import Enum

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

from app.domain import case, decision, facts


def domain_types() -> list[type]:
    types = []
    for module in (decision, facts, case):
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ == module.__name__ and issubclass(obj, BaseModel | Enum):
                types.append(obj)
    return types


def serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=domain_types())
