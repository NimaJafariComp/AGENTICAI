# Production Readiness Checklist

The local demo is intentionally scoped to prove the core architecture and safety constraints. The items below represent the gap between this demo and a production deployment.

| # | Area | Status | Recommendation |
|---|------|--------|----------------|
| 1 | **Auth** | Not in scope | Add OAuth2/JWT for the chat and admin endpoints. Gate the admin trace endpoint to internal staff only. |
| 2 | **Rate limiting** | Not in scope | Add per-IP and per-session throttles at the API gateway on `/api/chat`. |
| 3 | **Secrets** | Not in scope | Move API keys out of `.env` into a secrets manager (AWS Secrets Manager, GCP Secret Manager, or Azure Key Vault) and inject at runtime. |
| 4 | **PII redaction** | Not in scope | Redact or hash customer emails and names before writing to the trace store or forwarding to external observability tools. |
| 5 | **Observability** | Partial | Emit structured spans and logs to an external stack (Datadog, Honeycomb, OpenTelemetry). The trace schema already captures latency, tokens, and cost per event — it is ready to forward. |
| 6 | **Persistent storage** | Not in scope | Replace the local SQLite file with a managed PostgreSQL instance with backups and Alembic migrations. |
| 7 | **Model monitoring** | Not in scope | Pin the LLM to a specific model ID and log provider response headers per decision for an immutable audit trail. |
| 8 | **Human-review workflow** | Partial | Integrate escalated cases with a ticketing system (Zendesk, Intercom) and add a resolution state to `final_decisions`. |
| 9 | **HA / containerization** | Not in scope | Containerize with Docker and deploy behind a load balancer with health-check probes. |
| 10 | **LLM resilience** | Partial | Add exponential backoff with jitter and a circuit breaker for provider 429/5xx responses. |
| 11 | **GDPR / CCPA** | Not in scope | Implement a data subject delete path that scrubs PII from the trace store on request. |

## What is already production-ready in this demo

The following design decisions were made deliberately to be production-safe from day one:

- **Deterministic policy engine** — the policy layer is the sole authority for refund outcomes; the LLM cannot override it
- **`decision_id` enforcement** — protected terminal actions (approve, deny, escalate) require a backend-minted token; replay and spoofing are blocked
- **Session guard** — hard denials, escalated cases, and approved sessions are locked; the agent cannot re-evaluate them regardless of what the user says
- **Prompt injection resistance** — the session guard runs before intake on every turn; injected instructions cannot alter a final decision
- **Immutable audit trail** — every turn, tool call, and final decision is persisted with timestamps, latency, token usage, and cost
- **Retry / fallback visibility** — provider failures are logged as `provider_fallback` traces, not silently swallowed
- **Policy-as-code** — the refund policy lives in a versioned YAML-fronted Markdown file; changes are auditable in git
