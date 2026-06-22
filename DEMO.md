# Demo Walkthrough

This file is shortest path to a clean 5-minute walkthrough.

## Goal

Show that:

1. refund decisions are enforced by deterministic backend policy
2. tool calls and traces are visible
3. prompt injection does not bypass policy
4. app runs locally with Ollama or MockProvider

## Before recording

```bash
source .venv/bin/activate
make dev
```

Open:

- `http://localhost:8501`
- `http://localhost:8000/health`

Recommended demo mode:

```bash
export LLM_PROVIDER=mock
make stop
make dev
```

## Suggested flow

### 1. Architecture truth

Say:

- “LLM handles conversation only.”
- “Deterministic policy engine is final authority.”
- “Protected terminal actions require a valid `decision_id`.”

Show:

- health endpoint
- provider info
- policy tab

### 2. Approved refund

Run:

- `Approved refund`

Expected:

- final decision `APPROVE`
- `check_refund_eligibility` followed by `approve_refund`

### 3. Denied refund

Run:

- `Denied: final sale`

Expected:

- final decision `DENY`
- visible reason code for final sale

### 4. Human escalation

Run:

- `Escalated + retry: over $500 threshold`

Expected:

- final decision `ESCALATE`

### 5. Prompt injection attempt

Run:

- `Prompt injection attempt`

Expected:

- no approval
- final decision `ESCALATE`
- traces still show normal policy path

### 6. Close in Admin dashboard

Point out:

- user message
- trace events
- tool inputs
- tool outputs
- final decision record
- decision `used` state

## Recovery

Backend check:

```bash
curl http://localhost:8000/health
```

Clean local restart:

```bash
make stop
make dev
```
