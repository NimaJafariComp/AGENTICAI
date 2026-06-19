from fastapi import FastAPI

from backend.data_store import DataStore
from backend.trace import TraceService


app = FastAPI(title="AgenticAI Backend", version="0.1.0")
data_store = DataStore()
trace_service = TraceService(data_store)


@app.on_event("startup")
def startup() -> None:
    data_store.init_runtime_db()


@app.get("/health")
def health() -> dict[str, object]:
    summary = data_store.summary()
    return {
        "status": "ok",
        "milestone": "4",
        "seed_data": summary.model_dump(),
        "runtime_tables": data_store.runtime_table_counts(),
    }
