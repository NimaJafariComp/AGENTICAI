# Build an AI refund support agent

This project must deliver a finished local web application that can process e-commerce refund requests, enforce a written refund policy, and show operators how the agent reached each outcome.

## Product goal

Build an AI Customer Support Agent for e-commerce refunds. A customer can ask for a refund in a web interface. The backend agent must inspect customer and order data, apply the refund policy as the source of truth, and either approve, deny, or escalate the request.

## Required components

### 1. Synthetic data storage

The app must include local synthetic data:

- 15 customer profiles
- Customer order histories
- A written corporate refund policy document
- Machine-readable policy rules for deterministic enforcement
- Strict examples such as final-sale denial and refunds over $500 requiring human escalation

### 2. Backend and agent layer

The app must include a local API server and agent loop:

- Run a local API server with FastAPI, Express, or an equivalent framework
- Host an agent loop using raw function calling, LangGraph, CrewAI, or an equivalent orchestration pattern
- Dynamically call tools to query customer and order data
- Validate refund requests against the written policy
- Treat the written policy as the source of truth
- Resist customer pleading, arguing, and prompt-injection attempts
- Preserve policy outcomes even when the language model is persuaded or unreliable

### 3. Frontend UI

The app must include a clean web interface:

- Customer chat window for testing refund requests
- Admin dashboard or audit console for internal reasoning logs
- Policy view or equivalent reference surface
- Clear display of final outcomes: approve, deny, or escalate

## Finished deliverables

### Loom walkthrough

Record a Loom video with a maximum length of 5 minutes. The video must show:

- The live user interface
- A successful agent run
- At least one trace walkthrough
- Tool input and output
- Retry or failed step evidence
- Token usage or cost
- Latency
- A brief debugging explanation from the logs
- What should be added before production

### Live URL

A deployed URL is optional. If no deployed URL exists, the app must run locally without configuration errors and be ready for a live walkthrough.

## Evaluation criteria

The project will be evaluated on:

- **Product completeness**: the system runs out of the box without configuration errors
- **Agent resilience**: the agent handles edge cases, policy violations, and prompt-injection attempts
- **System architecture**: the UI, API, data layer, policy layer, and LLM orchestration are separated cleanly
- **Traceability**: the admin view exposes enough detail to debug tool calls, retries, latency, token usage, and cost
- **Demo readiness**: the repo includes clear startup instructions and deterministic demo paths

## Acceptance checklist

- [x] Local synthetic data includes 15 customers and order histories
- [x] Refund policy exists as a written document
- [x] Policy rules are enforced outside the language model
- [x] Backend exposes chat, policy, lookup, and trace endpoints
- [x] Agent dynamically calls tools for lookup and policy validation
- [x] Final-sale requests are denied
- [x] Refunds over $500 are escalated
- [x] Prompt-injection attempts are escalated or blocked
- [x] UI includes a customer chat or support-desk test surface
- [x] UI includes an admin trace or audit surface
- [x] Trace view shows tool input and output
- [x] Trace view shows failed or retried steps
- [x] Trace view shows token usage, cost, and latency
- [x] App starts locally with one documented command
- [x] Tests validate policy outcomes and key API behavior
- [ ] Loom walkthrough is recorded
- [ ] Production gaps are documented in a demo-ready checklist

## Current implementation evaluation

As of 2026-06-21, the project meets the core application requirements and is ready for a local walkthrough. The remaining completion gaps are deliverable-focused: record the Loom video and add a concise production-readiness checklist for the video close.

### Evidence

- Synthetic data: `data/customers.json` includes 15 customers, and `data/orders.json` includes order histories.
- Written policy: `data/refund_policy.md` defines both human-readable policy text and machine-readable rules.
- Backend/API: `backend/main.py` exposes chat, policy, lookup, health, transcription, session, and admin trace endpoints.
- Agent layer: `backend/agent.py` orchestrates intake, lookup tools, policy validation, protected terminal actions, and LLM response wording.
- Policy enforcement: `backend/policy_engine.py` makes approve, deny, and escalate decisions without relying on the language model.
- Tool safety: `backend/tools.py` requires backend-minted `decision_id` values before approve, deny, or escalate actions.
- Traceability: `backend/trace.py`, `backend/data_store.py`, and `frontend/pages/audit_console.py` expose tool I/O, failed calls, retries, token usage, estimated cost, and latency.
- Frontend: `frontend/pages/support_desk.py`, `frontend/pages/audit_console.py`, and `frontend/pages/policy.py` provide the customer chat, admin audit console, and policy view.
- Tests: the current suite validates policy outcomes, prompt-injection escalation, protected tool authorization, API behavior, trace persistence, LLM provider behavior, and transcription flow.

### Remaining work

- Record a Loom walkthrough under 5 minutes.
- In the walkthrough, show at least one successful run and one failed or retried trace step.
- Add or present a short production checklist covering auth, rate limits, secrets, PII redaction, observability, persistent storage, model monitoring, and human-review workflow.
