# AgenticAI

Local demo app for an AI customer support agent that handles e-commerce refund requests under a deterministic refund policy.

## Status

Current state: `Milestone 2` foundation complete.

Included:

- project structure
- pinned Python dependencies
- local environment template
- synthetic customer and order seed data
- written refund policy with machine-readable YAML front matter
- local developer startup command with `make dev`
- Pydantic schemas for seed, policy, and runtime records
- seed-data loading and runtime SQLite initialization

Not included yet:

- full agent loop
- deterministic policy engine implementation
- runtime write paths for traces and decisions
- refund tool execution

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
```

To force mock mode:

```env
LLM_PROVIDER=mock
```

## Local development

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

Current scaffold starts:

- FastAPI on `http://localhost:8000`
- Streamlit on `http://localhost:8501`

## Python compatibility

Primary target is Python `3.14.5`.

If dependency installation fails because of Python `3.14` package compatibility, use the smallest downgrade first:

1. Python `3.13`
2. Python `3.12`

## Seed data

Milestone 1 includes:

- `15` mock customers
- multiple order histories
- seeded demo cases for:
  - approve
  - deny due to final sale
  - deny due to return window
  - escalate due to amount over `$500`
  - suspicious/inconsistent claim review

## Next milestones

1. deterministic policy engine
2. trace logging
3. protected refund tools
4. provider adapter and mock fallback
5. agent loop
6. API routes
7. chat UI and admin dashboard
