# ORKIO Backend R0.6.1 — Premium Experience

## Scope

This release extends the R0.6.0 multi-agent realtime core with an explicit
interaction contract:

- `single`
- `team_synthesis`
- `roundtable`

It emits typed user-visible contribution events while preserving canonical
turn ownership. `Team` remains owned by Orkio. Explicitly selected specialists
remain the final owner when ownership is locked.

## Realtime contract

Success:

1. `status`
2. `execution`
3. `agent_started`
4. zero or more `agent_contribution_started`
5. zero or more `agent_contribution_done`
6. one or more `agent_chunk`
7. `agent_done`
8. `done`

Failure remains `error + done`; cancellation remains `cancelled + done`.

## Persistence

No schema change is introduced. Roundtable content is persisted as one
canonical Orkio-owned assistant message with visible agent sections. This is
intentional for RC1 and does not claim a persistent execution graph.

## Governance

`POST /api/governance/evolution/proposals` now requires an administrative
principal before evaluating the feature flag. The endpoint remains
proposal-only and executes no commit, merge, migration or deploy.

## Deployment

Apply by diff to an isolated branch. Run migrations already present in the
baseline with `alembic upgrade head`; this release adds no migration.

Do not deploy directly to public production without:

- exact repository/commit adaptation;
- clean dependency installation;
- backend test suite;
- frontend production build;
- real OpenAI RC1 smoke;
- tenant-negative tests;
- terminal SSE tests;
- persistence/reload validation;
- rollback drill.
