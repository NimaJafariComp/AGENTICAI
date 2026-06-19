from fastapi import FastAPI


app = FastAPI(title="AgenticAI Backend", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "milestone": "1"}
