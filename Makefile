.PHONY: dev

dev:
	@test -f backend/main.py || (echo "Missing backend/main.py. Build backend first."; exit 1)
	@test -f frontend/app.py || (echo "Missing frontend/app.py. Build frontend first."; exit 1)
	@mkdir -p .dev
	@(uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 > .dev/fastapi.log 2>&1) & \
	(streamlit run frontend/app.py --server.port 8501 --server.headless true)
