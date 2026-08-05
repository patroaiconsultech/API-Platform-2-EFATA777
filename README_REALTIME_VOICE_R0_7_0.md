
# ORKIO R0.7.0 — Premium Realtime Voice Core

## Scope

This candidate adds an Orkio-only realtime voice call while preserving the
canonical ORKIO text runtime:

```text
browser microphone
→ WebRTC media plane
→ browser-delivered final transcript
→ backend canonical voice turn
→ PlatformService.complete_chat
→ canonical Orkio ResponseEnvelope
→ persisted user and assistant messages
→ provider audio delivery of the canonical text
```

The provider does not own tenant, thread, user, agent selection, turn ownership,
governance, persistence or canonical ordering.

## New API

```text
POST /api/voice/sessions
POST /api/voice/sessions/{session_id}/calls
POST /api/voice/sessions/{session_id}/resume
POST /api/voice/sessions/{session_id}/events
POST /api/voice/sessions/{session_id}/turns
POST /api/voice/sessions/{session_id}/turns/{turn_id}/audio
POST /api/voice/sessions/{session_id}/close
GET  /api/voice/sessions/{session_id}
```

## Database

Additive migration chain:

```text
004_realtime_voice_core
→ 005_realtime_voice_premium_identity
```

Tables:

```text
voice_sessions
voice_turns
voice_events
voice_resume_tokens
```

The event identity contract separates:

```text
source_delivery_id
→ one concrete browser/provider delivery

semantic_operation_id
→ stable across retry and reconnect

canonical_event_id
→ allocated once by the canonical journal
```

Semantic dedupe excludes `session_generation`:

```text
tenant_id + session_id + source + semantic_operation_id
```

The session row is locked by the backend canonical journal before sequence
allocation. Reconnect uses a short-lived HMAC-signed resume token bound to
tenant, user, thread, session and session generation. Only the non-secret JTI
is persisted. Consumption of the JTI and session-generation transition occur
in the same store transaction. Closing and closed journal events plus the
terminal session row update also share one database transaction.

## Feature gates

Safe defaults:

```dotenv
PLATFORM_REALTIME_VOICE_ENABLED=false
PLATFORM_VOICE_ACTIONS_ENABLED=false
PLATFORM_MULTIAGENT_VOICE_ENABLED=false
PLATFORM_VOICE_PROVIDER=disabled
```

Voice activation fails closed unless:

```text
provider=openai_realtime
OPENAI_API_KEY is present on the backend
provider retention is explicitly confirmed
PLATFORM_VOICE_RESUME_TOKEN_SECRET is present and at least 32 characters
```

## Limits

- voice is Orkio-only and single-agent in R0.7.0;
- actions by voice are disabled;
- multiagent voice is disabled;
- raw audio retention defaults to none;
- transcript content is not logged;
- real OpenAI/WebRTC/mobile runtime evidence is not included in this package;
- production remains NO-GO until migration, browser matrix and real provider
  smoke tests pass.
