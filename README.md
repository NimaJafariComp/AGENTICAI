# AgenticAI

Local demo app for an AI customer support agent that handles e-commerce refund requests under a deterministic refund policy.

## Status

Current state: core local demo is implemented and validated.

Validated now:

- local FastAPI backend starts successfully
- local Streamlit UI starts successfully
- test suite passes: `27 passed`
- deterministic policy engine is the only authority for refund outcomes
- protected terminal actions require backend-minted `decision_id` values
- direct `MockProvider` mode works
- admin traces now include latency, token usage, and estimated cost fields
- one intentional retry/failure path is visible in admin logs for the retry demo order
- intake flow now explicitly collects full name, email, order ID, item, and issue before evaluation
- local voice-to-text capture is available in the customer chat with transcript review before send
- challenge demo paths exist for:
  - approve
  - deny
  - escalate
  - prompt-injection attempt

Included:

- project structure
- pinned Python dependencies
- local environment template
- synthetic customer and order seed data
- written refund policy with machine-readable YAML front matter
- local developer startup command with `make dev`
- Pydantic schemas for seed, policy, and runtime records
- seed-data loading and runtime SQLite initialization
- deterministic refund policy engine with focused rule tests
- runtime trace/session/tool-call/final-decision persistence layer
- protected refund tools with `decision_id` enforcement
- Ollama default provider adapter with direct mock mode and fallback logging
- simple refund agent loop with tool orchestration
- API routes for chat, policy, lookups, and admin trace reads
- Streamlit customer chat, admin dashboard, and policy viewer
- local ONNX speech-to-text endpoint for WAV voice notes
- demo walkthrough guide and helper make targets

Not in scope:

- production deployment hardening
- non-local hosting requirements

## Planned architecture

- `FastAPI` backend
- `Streamlit` frontend
- `Ollama` as default local LLM provider
- optional Ollama cloud-capable endpoint through config
- `MockProvider` fallback and direct selection
- `SQLite` for runtime sessions, traces, tool calls, and final decisions
- JSON files for seed customers and orders

## Project layout

```text
frontend/
backend/
data/
tests/
```

## Environment

Copy `.env.example` to `.env` when ready:

```bash
cp .env.example .env
```

Four LLM providers are supported via `LLM_PROVIDER`:

| Provider | When to use |
| --- | --- |
| `ollama` (default) | Local inference, no API key required |
| `openai` | OpenAI API (GPT-4o, GPT-4o-mini, etc.) |
| `anthropic` | Anthropic API (Claude Haiku, Sonnet, Opus) |
| `mock` | Deterministic stub for CI and demos |

### Local Ollama (default)

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2:3b
```

- No API key needed — pull the model once: `ollama pull llama3.2:3b`
- The backend health-checks Ollama and verifies the model is present; if Ollama is down or the model is not pulled, it falls back to `MockProvider` and records a `provider_fallback` trace
- Cost display shows `local` (no per-token charge)

### OpenAI

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini   # optional, gpt-4o-mini is the default
```

- Token costs are calculated automatically from the pricing table in `backend/providers/pricing.py` and displayed in the Audit Console
- If `OPENAI_API_KEY` is missing the backend falls back to `MockProvider`

### Anthropic

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001   # optional, Haiku is the default
```

- Same cost calculation and fallback behaviour as OpenAI

### Mock (no LLM)

```env
LLM_PROVIDER=mock
```

Recommended for demos and CI:

```bash
LLM_PROVIDER=mock make dev
```

Voice-to-text notes:

- uses local `onnx-asr` transcription by default
- first transcription may take longer while the model downloads and loads
- v1 accepts short WAV microphone recordings and lets the user edit the transcript before sending

## Quick start

Create a virtual environment and install pinned dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start the app:

```bash
make dev
```

App starts:

- FastAPI on `http://localhost:8000`
- Streamlit on `http://localhost:8501`

Useful helper commands:

```bash
make lint   # ruff static checks
make check  # ruff + test suite
make stop
```

Linting and other dev tools are pinned separately:

```bash
pip install -r requirements-dev.txt
```

## Python compatibility

Primary target is Python `3.14.5`.

If dependency installation fails because of Python `3.14` package compatibility, use the smallest downgrade first:

1. Python `3.13`
2. Python `3.12`

## Seed data

Included:

- `15` mock customers
- multiple order histories
- seeded demo cases for:
  - approve
  - deny due to final sale
  - deny due to return window
  - escalate due to amount over `$500`
  - suspicious/inconsistent claim review

## Demo flow

Fastest walkthrough path:

1. Open Customer chat.
2. Optionally record a short voice note and transcribe it.
3. Run `Approved refund`.
4. Run `Denied: final sale`.
5. Run `Escalated + retry: over $500 threshold`.
6. Run `Prompt injection attempt`.
7. Open Admin dashboard and inspect traces, including `voice_input_received` and `speech_to_text_result`.

Challenge satisfaction summary:

- satisfies the main architecture and safety constraints
- satisfies the required approve / deny / escalate demo branches
- satisfies local-first demo expectations
- satisfies the trace completeness goals for retry visibility and latency/token logging

Detailed script:

- see [DEMO.md](DEMO.md)

## Session decision hierarchy

Every incoming user message is evaluated against the current session state before any intake or policy evaluation runs. The guard reads the latest final decision, classifies it, and either allows the turn to proceed or returns a blocked response explaining why.

### Session chip statuses

| Status | Condition |
| --- | --- |
| `APPROVE` | Latest final decision is APPROVE |
| `DENY` | Latest final decision is DENY |
| `ESCALATE` | Latest final decision is ESCALATE |
| `ERRORED` | No final decision; at least one tool call failed |
| `INCOMPLETE` | No final decision; tool calls or non-message traces exist |
| `NO ACTIVITY` | No final decision, no tool calls, no traces |

### Allowed actions by state

#### APPROVE — terminal

The refund has been approved. No further evaluation is allowed in this session.

- Allowed: explain approval, show details, open a new session.
- Blocked: re-evaluation, approval of a different request.

#### ESCALATE — auto-decision locked

The case is pending human review. No automatic approve or deny can be issued.

- Allowed: add notes, add evidence, explain escalation reason, check status.
- Blocked: automatic approval or denial.

#### DENY — depends on denial category

Every DENY includes reason codes. The guard classifies the codes as one of three categories:

**HARD_DENIAL** — policy is final; cannot be reversed automatically.

Reason codes: `FINAL_SALE_ITEM`, `OUTSIDE_RETURN_WINDOW`, `DAMAGED_DEFECTIVE_NOT_ELIGIBLE`, `DAMAGED_DEFECTIVE_OUTSIDE_SPECIAL_WINDOW`, `NON_REFUNDABLE_ITEM`, `DUPLICATE_REFUND_ALREADY_PROCESSED`.

- Allowed: explain denial reason, escalate for human review.
- Blocked: re-evaluation, automatic approval.
- If the customer disputes data: escalate rather than approve without verification.

**CORRECTABLE_DENIAL** — missing information; re-evaluation is allowed.

Reason codes: `MISSING_RECEIPT`, `MISSING_ORDER_ID`, `MISSING_ITEM_CONDITION`, `MISSING_PURCHASE_DATE`, `UNCLEAR_REQUEST`, `MISSING_DAMAGE_EVIDENCE`.

- Allowed: provide missing information, re-evaluate after correction.
- Approval is issued only if the corrected information satisfies policy.
- If the information is conflicting or suspicious: escalate instead of approving.

**ESCALATABLE_DENIAL** — borderline or exception case; no auto-decision.

Reason codes: `POLICY_EXCEPTION_REQUESTED`, `CUSTOMER_DISPUTES_POLICY_DATA`, `BORDERLINE_RETURN_WINDOW`, `HIGH_VALUE_ORDER`, `CONFLICTING_INFORMATION`, `POSSIBLE_FRAUD`, `SUSPICIOUS_OR_INCONSISTENT_CLAIM`.

**Note:** A final sale item reported as damaged or defective bypasses the `FINAL_SALE_ITEM` hard denial and produces an immediate ESCALATE decision (`FINAL_SALE_ITEM_DAMAGE_CLAIM`). Final sale covers buyer's remorse, not manufacturer defects.

- Allowed: escalate, add notes, explain reason.
- Blocked: automatic approval or denial.

#### INCOMPLETE — continue evaluation

Tool calls or traces exist but no final decision was reached. The user may provide additional information and evaluation continues normally.

#### ERRORED — allow retry

At least one tool call failed. This is an execution error, not a policy denial. The user may retry. If retry fails again, escalate. Never issue a business decision without valid tool results.

#### NO ACTIVITY — normal first evaluation

No prior activity. Proceed with standard intake and policy evaluation.

### Classification priority

When a denial contains multiple reason codes, the guard applies this priority:

```text
HARD_DENIAL  >  ESCALATABLE_DENIAL  >  CORRECTABLE_DENIAL
```

Unknown reason codes default to `HARD_DENIAL` (conservative).

### Key invariants

- An approved session cannot be approved again.
- An escalated session cannot be automatically approved or denied.
- A hard-denied session cannot become approved just because the user asks again.
- Execution errors (ERRORED) are never treated as policy denials.
- The guard runs before intake extraction on every turn.

### Implementation

| File | Role |
| --- | --- |
| `backend/session_guard.py` | `SessionGuard`, `SessionGate`, `classify_denial`, reason-code sets |
| `backend/schemas.py` | `DenialCategory` enum (`HARD`, `CORRECTABLE`, `ESCALATABLE`) |
| `backend/prompting.py` | `build_blocked_response_prompt` — generates the LLM context for each block type |
| `backend/agent.py` | Guard is evaluated at the top of `process_user_message` before any intake runs |

## Troubleshooting

### Backend not reachable

```bash
curl http://localhost:8000/health
```

### Clean local restart

```bash
make stop
make dev
```

### Reset to deterministic demo mode

```bash
export LLM_PROVIDER=mock
make stop
make dev
```
