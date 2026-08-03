# ORKIO R0.6.3 — Premium Agent Integrity & Wire Evidence

Audit candidate append-only over R0.6.2.

## Implemented

- speaker contract v3;
- headings case-insensitive with colon, hyphen, en dash and em dash;
- cross-agent and repeated-speaker rejection;
- generic refusal status and one controlled retry;
- owner decision contract v3;
- structured contribution envelope with status and evidence;
- truthful SSE versus HTTP JSON evidence;
- local wire event count and last event ID;
- bounded multi-agent history, context, output, latency telemetry and token target;
- read-only versioned knowledge snapshot.

## Honest limitations

- no persistent execution graph;
- no document/artifact runtime;
- no WebRTC voice;
- no live repository/database/log access;
- latency budget is telemetry, not a provider-side hard cancellation;
- total-token target can be exceeded by provider input accounting;
- no migration;
- no commit, merge or deploy.
