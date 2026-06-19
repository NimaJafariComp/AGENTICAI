# Prefer the project virtualenv so `make dev` runs the same interpreter the
# README sets up (and the same one `make check` already uses). Override with
# `make dev VENV=/path/to/venv` if needed.
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: dev stop check

dev:
	@test -f backend/main.py || (echo "Missing backend/main.py. Build backend first."; exit 1)
	@test -f frontend/app.py || (echo "Missing frontend/app.py. Build frontend first."; exit 1)
	@test -x $(BIN)/uvicorn || (echo "Missing $(BIN)/uvicorn. Create the venv and install deps: python3 -m venv $(VENV) && $(BIN)/pip install -r requirements.txt"; exit 1)
	@mkdir -p .dev
	@($(BIN)/uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 > .dev/fastapi.log 2>&1) & \
	($(BIN)/streamlit run frontend/app.py --server.port 8501 --server.headless true)

stop:
	@pkill -f "uvicorn backend.main:app" >/dev/null 2>&1 || true
	@pkill -f "streamlit run frontend/app.py" >/dev/null 2>&1 || true
	@echo "Stopped local backend/frontend if running."

check:
	@$(BIN)/pytest -q
