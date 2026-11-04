# Two-developer work split

## Team Member A

Own core backend, database models, sandbox execution and diff engine.

Deliverables: FastAPI application and task/sandbox/diff routes; typed domain contracts; SQLite fixture and fresh-copy helpers; mock agent execution with row snapshots; consensus comparison and core tests. Next, design durable metadata tables, immutable run digests and worker contracts.

## Team Member B

Own privacy shield, risk analysis, approval workflow and future frontend/dashboard.

Deliverables: deterministic sensitive-field masking; heuristic risk reports and injection flags; explicit decision storage with non-writing apply/rollback stubs; privacy/risk/approval tests; dashboard wireframes and a future review interface displaying masked before/after rows, agreement and risk. The frontend is optional and not included in the current backend scaffold.

## Shared responsibilities

Agree on schemas before parallel implementation. Review every privacy and approval boundary together. Keep fixtures synthetic and LLM responses mocked. Maintain README, environment examples, Docker setup and tests. Both members review any proposal that could enable production writes. Do not introduce production writes during this milestone.

## Integration points

- `Task` and `AgentRun`: A produces task IDs, agent IDs and immutable observations; B consumes them for review.
- `mask_record`: B provides deterministic masking; A calls it before fixture data enters any agent copy.
- `DatabaseChange` and `DiffComparison`: A produces before/after images and consensus groups; B renders them and uses disagreement in risk scoring.
- `RiskReport`: B produces score, level, warnings, blast radius and injection flags; A attaches it to the rehearsal response.
- `ApprovalDecision`: B binds review to the rehearsal ID; future A-owned adapters must require a durable approved digest and verify source preconditions.

## Milestones and acceptance

1. Shared contracts and synthetic fixtures agreed by both developers.
2. A completes three-copy execution and diff tests; B completes masking and risk tests.
3. Integrate task -> rehearsal -> risk -> review, with approval bypass and no-write regression tests.
4. Run pytest, Ruff and local Uvicorn health checks; review Docker configuration and documentation together.
5. Plan dashboard and real integrations separately after agreeing on authentication, privacy boundaries and production safeguards.
