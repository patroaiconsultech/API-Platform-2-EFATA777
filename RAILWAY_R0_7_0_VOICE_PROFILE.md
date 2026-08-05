
# Railway R0.7.0 Voice Profile

## Existing variables to preserve

```dotenv
PLATFORM_ENVIRONMENT=rc1-test
PLATFORM_RELEASE_SHA=${{RAILWAY_GIT_COMMIT_SHA}}
PLATFORM_AUTH_MODE=demo_headers
DATABASE_URL=${{Postgres.DATABASE_URL}}

PLATFORM_LLM_PROVIDER=openai_responses
OPENAI_API_KEY=<PRESERVE_EXISTING_BACKEND_SECRET>
OPENAI_DEFAULT_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_STORE_RESPONSES=false

PLATFORM_REALTIME_STREAMING_ENABLED=true
PLATFORM_MULTIAGENT_ENABLED=true
PLATFORM_ASSISTED_EVOLUTION_ENABLED=false
```

Never expose the provider key through `VITE_*` or browser code.

## Deployment-safe first stage

Upload backend and frontend code with voice disabled:

```dotenv
PLATFORM_REALTIME_VOICE_ENABLED=false
PLATFORM_VOICE_ACTIONS_ENABLED=false
PLATFORM_MULTIAGENT_VOICE_ENABLED=false
PLATFORM_VOICE_PROVIDER=disabled

PLATFORM_VOICE_RAW_AUDIO_RETENTION=none
PLATFORM_VOICE_TRANSCRIPT_RETENTION=thread_policy
PLATFORM_VOICE_PROVIDER_RETENTION_CONFIRMED=false
PLATFORM_VOICE_CONSENT_REQUIRED=true
PLATFORM_VOICE_LOG_TRANSCRIPT_CONTENT=false
PLATFORM_VOICE_AUDIT_CONTENT=metadata_only
```

Run and validate migration `004_realtime_voice_core` before activation.

## RC voice activation

Only after provider retention is reviewed and accepted. Generate a new
backend-only resume-token signing secret; do not reuse or expose the OpenAI key:

```dotenv
PLATFORM_REALTIME_VOICE_ENABLED=true
PLATFORM_VOICE_PROVIDER=openai_realtime
PLATFORM_VOICE_PROVIDER_RETENTION_CONFIRMED=true

OPENAI_REALTIME_MODEL=gpt-realtime
OPENAI_REALTIME_VOICE=marin
OPENAI_REALTIME_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe

PLATFORM_VOICE_MAX_SESSION_SECONDS=1800
PLATFORM_VOICE_IDLE_TIMEOUT_SECONDS=120
PLATFORM_VOICE_MAX_RECONNECT_ATTEMPTS=3
PLATFORM_VOICE_RECONNECT_DEADLINE_SECONDS=30
PLATFORM_VOICE_RESUME_TOKEN_TTL_SECONDS=120
PLATFORM_VOICE_RESUME_TOKEN_SECRET=<GENERATE_BACKEND_ONLY_RANDOM_SECRET_MIN_32_CHARS>
PLATFORM_VOICE_MAX_ACTIVE_SESSIONS_PER_USER=1
```

Keep unavailable capabilities disabled:

```dotenv
PLATFORM_VOICE_ACTIONS_ENABLED=false
PLATFORM_MULTIAGENT_VOICE_ENABLED=false
```

## Rollback

```text
1. Set PLATFORM_REALTIME_VOICE_ENABLED=false.
2. Set PLATFORM_VOICE_PROVIDER=disabled.
3. Redeploy backend.
4. Text HTTP/SSE remains available.
5. Roll back application commits if required.
6. Downgrade migration 004 only after voice writes are stopped and reviewed.
```
