from __future__ import annotations

import re


_AGENT_NAMES = ("Orkio", "Orion", "Chris", "Laura", "Team")
_AGENT_HEADING_RE = re.compile(
    r"(?im)^[ \t]{0,3}(?:#{1,6}[ \t]*)?"
    r"(Orkio|Orion|Chris|Laura|Team)[ \t]*:?[ \t]*$"
)
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _clean_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _EXCESS_BLANK_LINES_RE.sub("\n\n", normalized)
    return normalized.strip()


def normalize_agent_viewpoint(
    content: str,
    agent_id: str,
    *,
    max_chars: int = 8_000,
) -> str:
    """Keep only the named speaker when a model emits nested agent sections.

    Plain text is preserved. If the model emits headings for ORKIO agents,
    the section belonging to ``agent_id`` wins. This prevents a contributor
    or the roundtable owner from impersonating other speakers.
    """

    cleaned = _clean_text(content)
    if not cleaned:
        return ""

    matches = list(_AGENT_HEADING_RE.finditer(cleaned))
    selected = cleaned

    if matches:
        sections: list[tuple[str, str]] = []
        prefix = _clean_text(cleaned[: matches[0].start()])
        for index, match in enumerate(matches):
            start = match.end()
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(cleaned)
            )
            sections.append(
                (
                    match.group(1),
                    _clean_text(cleaned[start:end]),
                )
            )

        own_sections = [
            section
            for name, section in sections
            if name.casefold() == agent_id.casefold() and section
        ]
        if own_sections:
            selected = own_sections[-1]
        elif prefix:
            selected = prefix
        else:
            selected = (
                "Contribuição removida porque a saída não respeitou "
                "o contrato de autoria do agente."
            )

    selected = _AGENT_HEADING_RE.sub("", selected)
    selected = _clean_text(selected)

    if len(selected) > max_chars:
        selected = selected[:max_chars].rstrip()
        selected += "\n\n[Contribuição limitada pelo runtime.]"

    return selected


def contains_cross_agent_heading(content: str, agent_id: str) -> bool:
    return any(
        match.group(1).casefold() != agent_id.casefold()
        for match in _AGENT_HEADING_RE.finditer(content)
    )
