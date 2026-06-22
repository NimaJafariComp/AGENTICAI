# Prefer the project virtualenv so `make dev` runs the same interpreter the
# README sets up (and the same one `make check` already uses). Override with
# `make dev VENV=/path/to/venv` if needed.
VENV ?= .venv
BIN := $(VENV)/bin
OLLAMA_BASE_URL ?= http://localhost:11434

.PHONY: dev stop check lint ollama-start

ollama-start:
	@provider="$$(grep -E '^LLM_PROVIDER=' .env 2>/dev/null | tail -n1 | cut -d= -f2)"; \
	provider="$${provider:-$${LLM_PROVIDER}}"; \
	provider="$${provider:-ollama}"; \
	ollama_url="$$(grep -E '^OLLAMA_BASE_URL=' .env 2>/dev/null | tail -n1 | cut -d= -f2)"; \
	ollama_url="$${ollama_url:-$${OLLAMA_BASE_URL}}"; \
	ollama_url="$${ollama_url:-$(OLLAMA_BASE_URL)}"; \
	ollama_model="$$(grep -E '^OLLAMA_MODEL=' .env 2>/dev/null | tail -n1 | cut -d= -f2)"; \
	ollama_model="$${ollama_model:-$${OLLAMA_MODEL}}"; \
	ollama_model="$${ollama_model:-llama3.2:3b}"; \
	if [ "$$provider" = "ollama" ]; then \
		if curl -fsS "$$ollama_url/api/tags" >/dev/null 2>&1; then \
			echo "Ollama already running at $$ollama_url."; \
		elif command -v ollama >/dev/null 2>&1; then \
			echo "Starting Ollama at $$ollama_url..."; \
			mkdir -p .dev; \
			(ollama serve > .dev/ollama.log 2>&1) & \
			for i in 1 2 3 4 5; do \
				sleep 1; \
				curl -fsS "$$ollama_url/api/tags" >/dev/null 2>&1 && break; \
			done; \
			curl -fsS "$$ollama_url/api/tags" >/dev/null 2>&1 || echo "Ollama did not become ready yet; continuing with backend fallback."; \
		else \
			echo "Ollama CLI not found; backend will use fallback provider."; \
		fi; \
		if command -v ollama >/dev/null 2>&1 && curl -fsS "$$ollama_url/api/tags" >/dev/null 2>&1; then \
			if curl -fsS "$$ollama_url/api/tags" | grep -q "\"name\":\"$$ollama_model\""; then \
				echo "Ollama model $$ollama_model already available."; \
			else \
				echo "Pulling Ollama model $$ollama_model..."; \
				ollama pull "$$ollama_model"; \
			fi; \
		fi; \
	fi

dev: ollama-start
	@test -f backend/main.py || (echo "Missing backend/main.py. Build backend first."; exit 1)
	@test -f frontend/app.py || (echo "Missing frontend/app.py. Build frontend first."; exit 1)
	@test -x $(BIN)/uvicorn || (echo "Missing $(BIN)/uvicorn. Create the venv and install deps: python3 -m venv $(VENV) && $(BIN)/pip install -r requirements.txt"; exit 1)
	@mkdir -p .dev
	@($(BIN)/uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 > .dev/fastapi.log 2>&1) & \
	($(BIN)/streamlit run frontend/app.py --server.port 8501 --server.headless true)

stop:
	@pkill -f "uvicorn backend.main:app" >/dev/null 2>&1 || true
	@pkill -f "streamlit run frontend/app.py" >/dev/null 2>&1 || true
	@pkill -f "ollama serve" >/dev/null 2>&1 || true
	@echo "Stopped local backend/frontend and Ollama server if running."

lint:
	@test -x $(BIN)/ruff || (echo "Missing $(BIN)/ruff. Install dev deps: $(BIN)/pip install -r requirements-dev.txt"; exit 1)
	@$(BIN)/ruff check .

check: lint
	@$(BIN)/pytest -q
