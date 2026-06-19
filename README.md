# AgenticAI

Local demo app for an AI customer support agent that handles e-commerce refund requests under a deterministic refund policy.

## Status

Current state: core local demo is implemented and validated.

Validated now:

- local FastAPI backend starts successfully
- local Streamlit UI starts successfully
- test suite passes: `26 passed`
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

See [plan.md](/Users/nimajafari/Programming/git_repos/AgenticAI/plan.md:1) for the full implementation plan.

## Environment

Copy `.env.example` to `.env` when ready:

```bash
cp .env.example .env
```

Default provider config:

```env
LLM_PROVIDER=ollama
OLLAMA_MODE=local
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
BACKEND_BASE_URL=http://localhost:8000
STT_PROVIDER=onnx_asr
STT_MODEL=nemo-parakeet-tdt-0.6b-v3
STT_LANGUAGE=en
STT_MAX_DURATION_SECONDS=20
STT_ENABLED=true
```

To force mock mode:

```env
LLM_PROVIDER=mock
```

Recommended demo mode:

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
make check
make stop
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
5. Run `Escalate + retry: amount over $500`.
6. Run `Prompt injection attempt`.
7. Open Admin dashboard and inspect traces, including `voice_input_received` and `speech_to_text_result`.

Challenge satisfaction summary:

- satisfies the main architecture and safety constraints
- satisfies the required approve / deny / escalate demo branches
- satisfies local-first demo expectations
- satisfies the trace completeness goals for retry visibility and latency/token logging

Detailed script:

- see [DEMO.md](/Users/nimajafari/Programming/git_repos/AgenticAI/DEMO.md:1)

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
