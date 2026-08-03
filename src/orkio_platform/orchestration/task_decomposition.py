from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal


OwnerContract = Literal[
    "decision_v1",
    "classification_v1",
    "factual_summary_v1",
    "short_ack_v1",
    "risk_assessment_v1",
]

_TASK_SLICE_VERSION = "task_slice_v1"
_AGENT_IDS = ("Orion", "Chris", "Laura", "Orkio")
_AGENT_LINE_RE = re.compile(
    r"(?im)^[ \t]{0,3}"
    r"(?:#{1,6}[ \t]*)?"
    r"(?:\*\*|__)?"
    r"@?(?P<agent>Orkio|Orion|Chris|Laura)"
    r"(?:\*\*|__)?"
    r"(?P<rest>[^\n]*)$"
)
_LEADING_SEPARATOR_RE = re.compile(r"^[ \t]*(?::|[-–—])[ \t]*")
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class TaskSlice:
    agent_id: str
    user_message: str
    explicit_assignment: bool
    shared_objective: str
    assigned_task: str
    version: str = _TASK_SLICE_VERSION


@dataclass(frozen=True, slots=True)
class TaskDecomposition:
    shared_objective: str
    owner_contract: OwnerContract
    slices: tuple[TaskSlice, ...]
    version: str = _TASK_SLICE_VERSION

    def for_agent(self, agent_id: str) -> TaskSlice:
        for item in self.slices:
            if item.agent_id.casefold() == agent_id.casefold():
                return item
        raise KeyError(agent_id)


_ROLE_TASKS = {
    "Orion": (
        "Analyze only the technical, architectural, security, governance, "
        "operational-risk, testing and rollback aspects relevant to the user "
        "objective."
    ),
    "Chris": (
        "Analyze only the business, positioning, market, monetization, "
        "commercial trade-off and growth aspects relevant to the user objective."
    ),
    "Laura": (
        "Analyze only the product, UX, onboarding, adoption, communication, "
        "trust and customer-journey aspects relevant to the user objective."
    ),
    "Orkio": (
        "Coordinate only the validated specialist contributions and deliver the "
        "response required by the selected owner contract."
    ),
}

_OWNER_DIRECTIVES = {
    "decision_v1": (
        "Deliver only the executive decision using DECISION, PRIORITY and "
        "NEXT STEP. MAIN RISK and VERDICT are optional."
    ),
    "classification_v1": (
        "Deliver one concise classification table or list. Keep the requested "
        "categories distinct and state uncertainty explicitly. Do not repeat "
        "the specialists agent by agent."
    ),
    "factual_summary_v1": (
        "Deliver one concise factual synthesis. Separate verified facts, "
        "limitations and the next useful action. Do not repeat the specialists "
        "agent by agent."
    ),
    "short_ack_v1": (
        "Return only the short coordinator response explicitly requested by the "
        "user. Do not repeat contributor names or their acknowledgements."
    ),
    "risk_assessment_v1": (
        "Deliver one concise risk assessment with material risk, impact, "
        "mitigation and verdict. Do not reproduce specialist sections."
    ),
}


def _clean(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _EXCESS_BLANK_LINES_RE.sub("\n\n", normalized)
    return normalized.strip()


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return without_marks.casefold()


def classify_owner_contract(content: str) -> OwnerContract:
    folded = _fold(content)

    if (
        re.search(r"\bclassific", folded)
        or (
            "comprovado" in folded
            and (
                "planejado" in folded
                or "nao conectado" in folded
                or "nao comprovado" in folded
            )
        )
    ):
        return "classification_v1"

    if (
        "somente com seu nome" in folded
        or "palavra ok" in folded
        or "responda somente" in folded
        or "responda apenas" in folded
        or "finalize exatamente" in folded
    ):
        return "short_ack_v1"

    if (
        re.search(r"\bauditor", folded)
        or re.search(r"\brisco", folded)
        or "go/no-go" in folded
        or "no-go" in folded
    ):
        return "risk_assessment_v1"

    if (
        re.search(r"\bdecis", folded)
        or re.search(r"\bprioridade", folded)
        or "proximo passo" in folded
        or "o que vcs preferem" in folded
        or "o que voces preferem" in folded
        or re.search(r"\bescolh", folded)
        or re.search(r"\bcompare", folded)
    ):
        return "decision_v1"

    return "factual_summary_v1"


def owner_contract_directive(contract: OwnerContract) -> str:
    return _OWNER_DIRECTIVES[contract]


def _parse_agent_sections(
    content: str,
) -> tuple[str, dict[str, list[str]]]:
    cleaned = _clean(content)
    matches = list(_AGENT_LINE_RE.finditer(cleaned))
    if not matches:
        return cleaned, {}

    shared = _clean(cleaned[: matches[0].start()])
    sections: dict[str, list[str]] = {}

    for index, match in enumerate(matches):
        agent_id = match.group("agent")
        rest = _LEADING_SEPARATOR_RE.sub(
            "",
            match.group("rest") or "",
        ).strip()
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(cleaned)
        )
        body = _clean(cleaned[start:end])
        block = _clean(
            "\n".join(part for part in (rest, body) if part)
        )
        sections.setdefault(agent_id, []).append(block)

    return shared, sections



def _implicit_assignment(
    agent_id: str,
    owner_contract: OwnerContract,
) -> str:
    if owner_contract == "short_ack_v1" and agent_id != "Orkio":
        return (
            "Return only OK. The runtime renders your agent identity; "
            "do not write any agent name, heading or additional analysis."
        )
    if agent_id == "Orkio":
        return owner_contract_directive(owner_contract)
    return _ROLE_TASKS[agent_id]

def _render_slice(
    *,
    agent_id: str,
    shared: str,
    assigned: str,
    explicit: bool,
    owner_contract: OwnerContract,
) -> TaskSlice:
    shared_text = shared or "Coordinate the current user objective."
    assigned_text = assigned or _implicit_assignment(
        agent_id,
        owner_contract,
    )

    user_message = _clean(
        "\n\n".join(
            (
                f"SHARED USER OBJECTIVE:\n{shared_text}",
                f"EXCLUSIVE ASSIGNMENT FOR {agent_id}:\n{assigned_text}",
                (
                    "SCOPE LIMIT: answer only this assignment. Do not execute, "
                    "quote or restate tasks assigned to another agent."
                ),
            )
        )
    )

    return TaskSlice(
        agent_id=agent_id,
        user_message=user_message,
        explicit_assignment=explicit,
        shared_objective=shared_text,
        assigned_task=assigned_text,
    )


def decompose_user_request(content: str) -> TaskDecomposition:
    cleaned = _clean(content)
    shared, sections = _parse_agent_sections(cleaned)
    owner_blocks = [
        block
        for block in sections.get("Orkio", [])
        if block
    ]
    contract_source = (
        _clean("\n\n".join(owner_blocks))
        if owner_blocks
        else cleaned
    )
    contract = classify_owner_contract(contract_source)

    if not sections:
        shared = cleaned

    slices: list[TaskSlice] = []
    for agent_id in _AGENT_IDS:
        explicit_blocks = [
            block
            for block in sections.get(agent_id, [])
            if block
        ]
        assigned = _clean("\n\n".join(explicit_blocks))
        slices.append(
            _render_slice(
                agent_id=agent_id,
                shared=shared,
                assigned=assigned,
                explicit=bool(explicit_blocks),
                owner_contract=contract,
            )
        )

    return TaskDecomposition(
        shared_objective=shared or cleaned,
        owner_contract=contract,
        slices=tuple(slices),
    )
