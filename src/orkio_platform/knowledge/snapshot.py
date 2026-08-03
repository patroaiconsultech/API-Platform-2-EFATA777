from __future__ import annotations

from typing import Final


KNOWLEDGE_SNAPSHOT_VERSION: Final = "orkio-platform-r065-v1"

KNOWLEDGE_SNAPSHOT: Final[dict[str, object]] = {
    "version": KNOWLEDGE_SNAPSHOT_VERSION,
    "release_id": "ORKIO-PREMIUM-RESPONSIVE-TENANT-TRUTH-R0-6-5",
    "generated_at": "2026-08-03",
    "source_documents": (
        "PROTOCOLO MESTRE DANIEL",
        "MEMÓRIA TÉCNICA INICIAL — AGENTE DANIEL",
        "R0.6.3 runtime speaker-contract and SSE evidence",
        "AO-01 superseding audit verdict",
        "R0.6.4 runtime golden-demo and task-decomposition evidence",
        "R0.6.5 responsive containment and tenant-truth patch evidence",
    ),
    "source_commit": "NOT_PROVEN",
    "facts": (
        "Explicit agent selection wins over inference.",
        "ownership_locked=true makes the turn owner immutable.",
        "Auxiliary context cannot assume final authorship.",
        "Persistence, SSE and frontend must share canonical identity.",
        "Every SSE flow ends with done or error plus done.",
        "Current multiagent modes are single, team_synthesis and roundtable.",
        "The current known ORKIO stack is React/Vite, FastAPI, PostgreSQL, OpenAI Responses and textual SSE.",
        "Tenant A being unable to read, rename or mutate tenant B is an expected security invariant, not a defect.",
        "A member being denied administrative access and a request without a valid tenant failing are expected security controls.",
        "R0.6.4 and later candidates isolate explicit tasks with task_slice_v1.",
        "R0.6.4 and later candidates use adaptive owner contracts by intent.",
        "A failed owner synthesis may preserve contributors as partial.",
        "The current execution trace is trace_lite, not a persistent graph.",
        "Assisted evolution is proposal_only and disabled by default.",
        "Tenant isolation and human approval cannot be weakened silently.",
    ),
    "planned_not_connected": (
        "WebRTC voice-to-voice",
        "document analysis runtime",
        "DOCX/XLSX/PPTX/PDF artifact runtime",
        "persistent execution graph",
        "Architecture Indexer",
        "Market Intelligence plane",
        "extended governed core-agent runtime",
    ),
    "limitations": (
        "This snapshot is read-only and may be stale.",
        "It is not live repository, database, log or deployment access.",
        "Current runtime evidence overrides this snapshot.",
        "R0.6.5 features are local candidate capabilities until deployed.",
        "source_commit is not proven in this local artifact.",
    ),
}


def platform_knowledge_prompt() -> str:
    facts = "; ".join(KNOWLEDGE_SNAPSHOT["facts"])
    planned = "; ".join(KNOWLEDGE_SNAPSHOT["planned_not_connected"])
    limitations = "; ".join(KNOWLEDGE_SNAPSHOT["limitations"])
    return (
        "Versioned ORKIO platform snapshot "
        f"{KNOWLEDGE_SNAPSHOT_VERSION}: {facts}. "
        f"Planned or not connected: {planned}. "
        f"Snapshot limitations: {limitations}."
    )
