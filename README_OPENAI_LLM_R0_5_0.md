# ORKIO R0.5.0 — OpenAI Responses Provider

## Scope

This release replaces the deterministic chat content generator with an
injectable LLM provider while preserving:

- tenant-scoped thread history;
- explicit agent ownership;
- atomic user/assistant persistence;
- idempotent execution replay;
- SSE terminal `error + done` and `agent_done + done`;
- current database schema.

The OpenAI integration uses the official Python SDK and the Responses API.
The provider call is buffered in R0.5.0: the ORKIO SSE endpoint emits the
completed model response as one `agent_chunk`. Token-by-token upstream
streaming is intentionally deferred to a separate governed patch.

## Provider modes

### deterministic

Default and test-safe. No external network request and no API key required.

### openai_responses

Requires all of:

```text
PLATFORM_LLM_PROVIDER=openai_responses
OPENAI_API_KEY=<manual backend secret>
OPENAI_DEFAULT_MODEL=<approved model id>
```

Optional controls:

```text
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_ORGANIZATION_ID=
OPENAI_PROJECT_ID=
OPENAI_TIMEOUT_SECONDS=120
OPENAI_MAX_RETRIES=2
OPENAI_MAX_OUTPUT_TOKENS=4096
OPENAI_STORE_RESPONSES=false
PLATFORM_LLM_HISTORY_MESSAGES=20
PLATFORM_LLM_MAX_CONTEXT_CHARS=100000
```

The API key is represented by Pydantic `SecretStr` and is never included in
health, readiness, governance responses, provider metadata, or logs.

## Safe Railway order

Do not switch the provider first.

1. Deploy the code to an isolated branch/environment.
2. Add all non-secret OpenAI variables.
3. Manually add and seal `OPENAI_API_KEY` in the backend service.
4. Keep `PLATFORM_LLM_PROVIDER=deterministic` and verify boot.
5. Set `PLATFORM_LLM_PROVIDER=openai_responses` last.
6. Restart and verify `/api/health` reports `real_llm_enabled=true`.
7. Send a synthetic tenant chat request.
8. Confirm persistence and SSE terminal events.
9. On failure, revert only `PLATFORM_LLM_PROVIDER=deterministic`.

## Data handling

- Conversation history is loaded only through `(tenant_id, thread_id)`.
- Error and cancelled assistant messages are excluded from model context.
- The oldest eligible messages are removed when the configured context
  character limit is reached.
- Tenant IDs, user IDs and thread IDs are not sent in the OpenAI API payload.
- `store=false` is the default.
- Raw upstream error bodies are not exposed to users or persisted.

## Error contract

Provider failures are mapped to safe codes:

```text
LLM_PROVIDER_TIMEOUT
LLM_PROVIDER_UNAVAILABLE
LLM_PROVIDER_RATE_LIMITED
LLM_PROVIDER_AUTH_FAILED
LLM_PROVIDER_REQUEST_FAILED
LLM_PROVIDER_EMPTY_RESPONSE
LLM_PROVIDER_SDK_MISSING
```

All streaming failures still terminate with:

```text
event: error
event: done
```

## Schema

```text
schema_change=false
new_migration=false
migration_execution_required=false
```

## Known limitations

- Real OpenAI network execution was not performed in the artifact-generation
  environment because no API key was supplied.
- The official SDK dependency must be resolved by the controlled build.
- Upstream token-by-token streaming is not implemented in this patch.
- Provider token usage is returned in the live response and execution log, but
  is not stored in the current database schema; idempotent replay can therefore
  return `token_usage=null`.
