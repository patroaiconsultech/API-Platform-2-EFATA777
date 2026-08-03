from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


AgentOutputStatus = Literal[
    "success",
    "refused",
    "contract_violation",
    "failed",
]

_AGENT_HEADING_RE = re.compile(
    r"(?im)^[ \t]{0,3}"
    r"(?P<markdown>#{1,6}[ \t]+)?"
    r"(?:\*\*|__)?"
    r"(?P<agent>Orkio|Orion|Chris|Laura|Team)"
    r"(?:\*\*|__)?"
    r"[ \t]*"
    r"(?:(?P<separator>:|[-–—])[ \t]*(?P<suffix>[^\n]*))?"
    r"[ \t]*$"
)
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")
_GENERIC_REFUSAL_RE = re.compile(
    r"(?is)^\s*(?:"
    r"(?:i(?:'|’)?m\s+sorry(?:[,:;]?\s+but)?[,:;]?\s*)?"
    r"(?:i\s+(?:can(?:not|'t|’t)|am\s+unable\s+to)\s+"
    r"(?:assist|help|comply|continue|provide|do)\b)"
    r"|(?:desculpe(?:[,:;]?\s+mas)?[,:;]?\s*)?"
    r"(?:(?:eu\s+)?(?:não|nao)\s+(?:posso|consigo)\s+"
    r"(?:ajudar|auxiliar|atender|continuar|fornecer|fazer)\b)"
    r"|(?:(?:não|nao)\s+posso\s+atender\s+(?:a|à)\s+"
    r"(?:essa|esta)\s+solicita)"
    r")"
)
_OWNER_LABELS = {
    "decision": re.compile(
        r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?"
        r"(?:\*\*|__)?(?:DECISION|DECISÃO)(?:\*\*|__)?"
        r"[ \t]*(?::|[-–—])?"
    ),
    "priority": re.compile(
        r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?"
        r"(?:\*\*|__)?(?:PRIORITY|PRIORIDADE)(?:\*\*|__)?"
        r"[ \t]*(?::|[-–—])?"
    ),
    "next_step": re.compile(
        r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?"
        r"(?:\*\*|__)?"
        r"(?:NEXT[ \t]+STEP|PRÓXIMO[ \t]+PASSO|PROXIMO[ \t]+PASSO)"
        r"(?:\*\*|__)?[ \t]*(?::|[-–—])?"
    ),
}


@dataclass(frozen=True, slots=True)
class AgentOutputAssessment:
    content: str
    status: AgentOutputStatus
    reason: str | None
    normalized: bool
    cross_agent_headings: tuple[str, ...]
    generic_refusal: bool
    truncated: bool
    contract_version: str = "speaker_contract_v3"

    @property
    def retryable_contract_failure(self) -> bool:
        return self.status in {"refused", "contract_violation"}


@dataclass(frozen=True, slots=True)
class _ParsedSection:
    agent_id: str
    content: str


def _clean_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _EXCESS_BLANK_LINES_RE.sub("\n\n", normalized)
    return normalized.strip()


def _inline_content(match: re.Match[str]) -> str:
    """Preserve plain ``Agent: content`` while treating markdown suffixes as titles."""

    if match.group("markdown"):
        return ""
    if match.group("separator") != ":":
        return ""
    return _clean_text(match.group("suffix") or "")


def _sections(
    cleaned: str,
) -> tuple[str, list[_ParsedSection], list[re.Match[str]]]:
    matches = list(_AGENT_HEADING_RE.finditer(cleaned))
    if not matches:
        return cleaned, [], []

    prefix = _clean_text(cleaned[: matches[0].start()])
    sections: list[_ParsedSection] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(cleaned)
        )
        body = _clean_text(cleaned[start:end])
        inline = _inline_content(match)
        content = _clean_text(
            "\n".join(part for part in (inline, body) if part)
        )
        sections.append(
            _ParsedSection(
                agent_id=match.group("agent"),
                content=content,
            )
        )
    return prefix, sections, matches


def _extract_viewpoint(
    content: str,
    agent_id: str,
) -> tuple[str, tuple[str, ...], bool, int]:
    cleaned = _clean_text(content)
    if not cleaned:
        return "", (), False, 0

    prefix, sections, matches = _sections(cleaned)
    if not matches:
        return cleaned, (), False, 0

    own_sections = [
        section.content
        for section in sections
        if section.agent_id.casefold() == agent_id.casefold()
        and section.content
    ]
    cross = tuple(
        dict.fromkeys(
            section.agent_id
            for section in sections
            if section.agent_id.casefold() != agent_id.casefold()
        )
    )

    if own_sections:
        selected = own_sections[0]
    elif prefix:
        selected = prefix
    else:
        selected = ""

    selected = _AGENT_HEADING_RE.sub("", selected)
    return _clean_text(selected), cross, True, len(own_sections)


def is_generic_refusal(content: str) -> bool:
    cleaned = _clean_text(content)
    if not cleaned or len(cleaned) > 1_200:
        return False
    return bool(_GENERIC_REFUSAL_RE.search(cleaned))


def assess_agent_output(
    content: str,
    agent_id: str,
    *,
    max_chars: int = 4_000,
) -> AgentOutputAssessment:
    """Validate one model output against the canonical speaker contract."""

    cleaned = _clean_text(content)
    selected, cross, heading_found, own_count = _extract_viewpoint(
        content,
        agent_id,
    )

    if not cleaned:
        return AgentOutputAssessment(
            content="",
            status="contract_violation",
            reason="empty_contribution",
            normalized=False,
            cross_agent_headings=(),
            generic_refusal=False,
            truncated=False,
        )

    if cross:
        return AgentOutputAssessment(
            content="",
            status="contract_violation",
            reason="cross_agent_heading",
            normalized=True,
            cross_agent_headings=cross,
            generic_refusal=False,
            truncated=False,
        )

    if own_count > 1:
        return AgentOutputAssessment(
            content="",
            status="contract_violation",
            reason="repeated_canonical_speaker_heading",
            normalized=True,
            cross_agent_headings=(),
            generic_refusal=False,
            truncated=False,
        )

    if heading_found and own_count == 0:
        return AgentOutputAssessment(
            content="",
            status="contract_violation",
            reason="canonical_speaker_missing",
            normalized=True,
            cross_agent_headings=(),
            generic_refusal=False,
            truncated=False,
        )

    if not selected:
        return AgentOutputAssessment(
            content="",
            status="contract_violation",
            reason="empty_contribution",
            normalized=heading_found,
            cross_agent_headings=(),
            generic_refusal=False,
            truncated=False,
        )

    refusal = is_generic_refusal(selected)
    if refusal:
        return AgentOutputAssessment(
            content=selected,
            status="refused",
            reason="generic_refusal",
            normalized=heading_found,
            cross_agent_headings=(),
            generic_refusal=True,
            truncated=False,
        )

    truncated = len(selected) > max_chars
    if truncated:
        selected = selected[:max_chars].rstrip()
        selected += "\n\n[Contribuição limitada pelo runtime.]"

    return AgentOutputAssessment(
        content=selected,
        status="success",
        reason=None,
        normalized=heading_found or truncated,
        cross_agent_headings=(),
        generic_refusal=False,
        truncated=truncated,
    )


def assess_owner_output(
    content: str,
    agent_id: str,
    *,
    max_chars: int = 4_000,
) -> AgentOutputAssessment:
    """Validate speaker isolation plus the minimum coordinator decision shape."""

    assessment = assess_agent_output(
        content,
        agent_id,
        max_chars=max_chars,
    )
    if assessment.status != "success":
        return assessment

    missing = [
        label
        for label, pattern in _OWNER_LABELS.items()
        if not pattern.search(assessment.content)
    ]
    if missing:
        return AgentOutputAssessment(
            content="",
            status="contract_violation",
            reason="owner_decision_fields_missing:" + ",".join(missing),
            normalized=assessment.normalized,
            cross_agent_headings=(),
            generic_refusal=False,
            truncated=assessment.truncated,
            contract_version="owner_decision_v3",
        )

    return AgentOutputAssessment(
        content=assessment.content,
        status="success",
        reason=None,
        normalized=assessment.normalized,
        cross_agent_headings=(),
        generic_refusal=False,
        truncated=assessment.truncated,
        contract_version="owner_decision_v3",
    )


def normalize_agent_viewpoint(
    content: str,
    agent_id: str,
    *,
    max_chars: int = 8_000,
) -> str:
    """Best-effort legacy extractor; new orchestration uses assessment APIs."""

    selected, _cross, _heading_found, _own_count = _extract_viewpoint(
        content,
        agent_id,
    )
    if len(selected) > max_chars:
        selected = selected[:max_chars].rstrip()
        selected += "\n\n[Contribuição limitada pelo runtime.]"
    return selected


def contains_cross_agent_heading(content: str, agent_id: str) -> bool:
    return any(
        match.group("agent").casefold() != agent_id.casefold()
        for match in _AGENT_HEADING_RE.finditer(content)
    )
