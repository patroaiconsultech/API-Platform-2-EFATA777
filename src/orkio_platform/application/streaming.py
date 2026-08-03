from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from orkio_platform.domain.models import ResponseEnvelope


TurnStreamKind = Literal["execution", "delta", "terminal"]


@dataclass(frozen=True, slots=True)
class TurnStreamSignal:
    kind: TurnStreamKind
    payload: dict[str, Any]
    response: ResponseEnvelope | None = None
