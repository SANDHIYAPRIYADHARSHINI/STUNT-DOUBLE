"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api import routes_approval, routes_diffs, routes_risk, routes_sandbox, routes_tasks

app = FastAPI(
    title="Stunt Double",
    version="0.1.0",
    description="Synthetic database rehearsals; production writes disabled.",
)
for module in (routes_tasks, routes_sandbox, routes_diffs, routes_risk, routes_approval):
    app.include_router(module.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Report API liveness without connecting to any source database."""
    return {"status": "ok"}
