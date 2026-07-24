"""Explicit serialization mapper, kept separate from the pure entity definitions."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, get_type_hints

from . import entities


_ENTITY_TYPES = {name: value for name, value in vars(entities).items() if isinstance(value, type) and hasattr(value, "__dataclass_fields__")}


def entity_to_dict(entity: object) -> dict[str, Any]:
    """Map a domain entity to a JSON-compatible tagged dictionary."""
    if not is_dataclass(entity):
        raise TypeError("entity_to_dict accepts a domain dataclass")
    return {"type": type(entity).__name__, **{item.name: _encode(getattr(entity, item.name)) for item in fields(entity)}}


def entity_from_dict(data: dict[str, Any]) -> object:
    """Restore an entity and let its constructor enforce all invariants."""
    type_name = data.get("type")
    entity_type = _ENTITY_TYPES.get(type_name)
    if entity_type is None:
        raise ValueError("unknown domain entity type")
    annotations = get_type_hints(entity_type)
    return entity_type(**{key: _decode(value, annotations[key]) for key, value in data.items() if key != "type"})


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if is_dataclass(value):
        return {item.name: _encode(getattr(value, item.name)) for item in fields(value)}
    # ``NewType`` values are runtime strings, so their annotation rather than
    # an ``isinstance`` check is used by the decoding side.
    return value


def _decode(value: Any, annotation: Any) -> Any:
    if annotation is entities.EntityId:
        return entities.EntityId(value)
    if annotation is datetime:
        return datetime.fromisoformat(value["$datetime"])
    if annotation in (entities.ClaimStatus, entities.HypothesisStatus, entities.EvidenceRelation):
        return annotation(value)
    if annotation is entities.Locator:
        return value if isinstance(value, entities.Locator) else entities.Locator(value["value"] if isinstance(value, dict) else value)
    if annotation == tuple[str, ...]:
        return tuple(value)
    return value
