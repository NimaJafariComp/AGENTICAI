from fastapi import FastAPI

from backend.agent import RefundAgent
from backend.data_store import DataStore
from backend.llm_client import LLMClient
from backend.policy_engine import PolicyEngine
from backend.tools import RefundTools
from backend.trace import TraceService


app = FastAPI(title="AgenticAI Backend", version="0.1.0")
data_store = DataStore()
trace_service = TraceService(data_store)
llm_client = LLMClient.from_env(trace_service=trace_service)
refund_tools = RefundTools(data_store, PolicyEngine(), trace_service)
refund_agent = RefundAgent(llm_client, refund_tools, trace_service)


@app.on_event("startup")
def startup() -> None:
    data_store.init_runtime_db()


@app.get("/health")
def health() -> dict[str, object]:
    summary = data_store.summary()
    return {
        "status": "ok",
        "milestone": "7",
        "seed_data": summary.model_dump(),
        "runtime_tables": data_store.runtime_table_counts(),
        "provider": llm_client.provider_info(),
    }
