# ORKIO Backend R0.6.0 — Multi-Agent Realtime Core

## Purpose

This RC1 backend successor adds:

- incremental OpenAI Responses streaming;
- upstream stream close on cancellation;
- deterministic multi-agent routing;
- Team orchestration under immutable Orkio ownership;
- explicit specialist contributions;
- canonical final synthesis;
- trace_lite execution metadata;
- central capability registry;
- assisted-evolution proposal mode with no execution.

## Safety and governance

The new runtime is feature-gated. Defaults remain disabled:

```text
PLATFORM_REALTIME_STREAMING_ENABLED=false
PLATFORM_MULTIAGENT_ENABLED=false
PLATFORM_ASSISTED_EVOLUTION_ENABLED=false
```

Enable them only in an isolated RC1 environment after the backend starts,
database persistence is confirmed, the OpenAI provider is validated, and the
frontend production build is reproducible.

`Team` is a meta-selection. It does not own the final response. Orkio remains
the canonical turn owner while Orion, Chris and Laura contribute. Explicitly
selected specialists remain immutable owners.

The execution graph is intentionally reported as `trace_lite`. No persistent
execution-node tables or migrations were added.

Assisted evolution produces proposals only. It does not edit files, commit,
push, merge, migrate or deploy. Human approval remains mandatory.

## Realtime contract

Success:

```text
status
execution
agent_started
execution(node_started/node_completed)*
agent_chunk+
agent_done
done
```

Error:

```text
error
done
```

Cancellation:

```text
cancelled
done
```

The persisted assistant message and `agent_done.message` share the same
canonical identity.

## Activation order

1. Apply on an isolated branch at the exact official base commit.
2. Run a clean dependency install and all tests.
3. Keep all new feature gates disabled.
4. Boot and validate deterministic chat and PostgreSQL.
5. Configure the OpenAI key manually in the backend.
6. Enable `PLATFORM_REALTIME_STREAMING_ENABLED=true`.
7. Validate incremental chunks and cancellation.
8. Enable `PLATFORM_MULTIAGENT_ENABLED=true`.
9. Validate Team and explicit-owner cases.
10. Enable `PLATFORM_ASSISTED_EVOLUTION_ENABLED=true`.
11. Validate proposal-only flags and absence of remote writes.
12. Execute rollback by disabling the three flags.

## Known limitations

- specialist contribution calls are buffered;
- only the final owner answer streams token-by-token;
- cancellation can close the owner stream between received events, but cannot
  preempt a buffered specialist call already in progress;
- execution nodes are not persisted;
- token usage is returned and logged but not stored in database columns;
- no frontend execution-graph visualization was added;
- no real OpenAI network call, Docker build or Railway RC1 was executed in the
  artifact-generation environment.
