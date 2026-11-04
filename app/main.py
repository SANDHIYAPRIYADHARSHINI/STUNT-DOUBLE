"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api import routes_approval, routes_diffs, routes_risk, routes_sandbox, routes_tasks

app = FastAPI(
    title="Stunt Double",
    version="0.1.0",
    description=(
        "Local synthetic-data demo. Create a task with POST /tasks, copy its id to "
        "POST /sandbox/run, then use the returned run id with GET /sandbox/runs/{run_id} "
        "or GET /sandbox/runs/{run_id}/summary. Two mock agents delete inactive customers; "
        "a third deliberately deletes more rows in its own sandbox. Production writes are disabled."
    ),
)
for module in (routes_tasks, routes_sandbox, routes_diffs, routes_risk, routes_approval):
    app.include_router(module.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Report API liveness without connecting to any source database."""
    return {"status": "ok"}
