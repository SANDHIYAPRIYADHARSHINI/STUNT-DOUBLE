# Stunt Double

An AI agent safety sandbox for rehearsing database operations before human review.

AI-generated database operations can delete the wrong rows, expose personal data, or follow malicious instructions. Stunt Double compares three independent sandbox observations so a reviewer can inspect changes and risk before considering production execution.

## Status

Local backend scaffold using synthetic fixtures and deterministic mock agents. No API keys, production connections, production writes, real LLM calls, or frontend are used. Approval is recorded, but **apply and rollback are non-writing stubs**. Review state is process-local and disappears on restart; use one API worker. This is a local demo without authentication.

## Architecture and workflow

FastAPI routers call modular privacy, sandbox, diff, risk, and approval services. Pydantic models define API contracts; SQLAlchemy validates SQLite URLs; SQLite backs a persistent fake demo source and three independent rehearsal files.

1. Submit a natural-language task.
2. Reset three sandbox files from the demo source and mask sensitive fields in the copies.
3. Run three mock agents on three separate SQLite copies.
4. Capture inserted, updated, and deleted rows by primary key.
5. Compare unanimous, partial, and conflicting changes.
6. Score SQL, affected rows, disagreement, and suspicious instructions.
7. Record a human approve/reject decision.
8. Check approval at apply; return an explicit disabled status without writing.

The mocks support `Delete inactive customers`: agents 1 and 2 delete only inactive customers; agent 3 deliberately runs an unbounded delete in its own sandbox. With the default fixture, their affected row counts are 1, 1, and 3. The comparison exposes two additional deletions from agent 3 and the risk report is critical. Other descriptions return `skipped` results with an explanation and no SQL. Model reasoning is mocked.

## Features

- A seeded demo SQLite source and three independent files, reset before each rehearsal
- Deterministic masking of common sensitive fields
- Row-level diffs and consensus classification
- Heuristic risk reports and prompt-injection flags
- Explicit approval checks and a process-local audit log
- Non-writing apply/rollback endpoints
- Tests and Docker Compose with three sandbox volumes

## Local setup

Install Python 3.11 or newer, then from this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.db
python -m uvicorn app.main:app --reload
```

On macOS/Linux activate with `source .venv/bin/activate` and copy with `cp .env.example .env`. Open http://127.0.0.1:8000/docs for interactive API calls; health is at http://127.0.0.1:8000/health.

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Or run `docker compose up --build`. Compose binds only localhost and mounts three separate SQLite sandbox volumes. SQLite is embedded, so no database server services are needed. These volumes separate files, not OS security boundaries; real agents need isolated workers.

## Environment

See `.env.example` for every supported setting. All URLs must use file-backed `sqlite:///` paths. The demo source and all three sandbox locations must be distinct from one another and from `DATABASE_URL`, which remains reserved and is never opened. `DEMO_SOURCE_DATABASE_URL` points only to the fake demo source.

```dotenv
DEMO_SOURCE_DATABASE_URL=sqlite:///./data/demo_source.db
DATABASE_URL=sqlite:///./data/demo.db
SANDBOX_DATABASE_URL_1=sqlite:///./data/sandbox1/sandbox.db
SANDBOX_DATABASE_URL_2=sqlite:///./data/sandbox2/sandbox.db
SANDBOX_DATABASE_URL_3=sqlite:///./data/sandbox3/sandbox.db
GEMMA_API_KEY=
OPENAI_API_KEY=
AGENT_TIMEOUT_SECONDS=30
MAX_AFFECTED_ROWS=100
REQUIRE_HUMAN_APPROVAL=true
```

API keys are placeholders for future integrations. `AGENT_TIMEOUT_SECONDS` currently sets SQLite lock wait, not a hard worker execution deadline. `MAX_AFFECTED_ROWS` affects risk scoring, not production authorization. Setting `REQUIRE_HUMAN_APPROVAL=false` never bypasses the approval check or enables writes.

## Demo databases and reset

Run `python -m app.db` to create `data/demo_source.db` and the three configured sandbox files. The command is safe to repeat: it keeps the existing owned demo source and resets all three sandboxes. The runner also initializes missing files and resets them before every rehearsal.

The source has three fake customers with `id`, `name`, `email`, `phone`, `status`, `created_at`, and `last_active_at`. Names start with `Demo`, email addresses use `example.invalid`, and phones use fictional 555 numbers. Timestamps are stored as ISO 8601 UTC text.

`create_demo_database(path)` seeds a new source; `create_sandbox_databases(source, destinations)` creates exactly three independent SQLite backups; `reset_sandboxes(source, destinations)` restores their complete schema and data. Initialization and reset copy identical source values. During rehearsal, the privacy shield masks the copies before agents see them, and mock changes are committed only to these sandbox files. Reset restores the original fake source values.

Files carry a SQLite application ID ownership marker. Existing unmarked files are refused, including old scaffold sandbox files; choose new empty paths for those files. Symlink and hard-link aliases between demo files or to the reserved production path are rejected. The marker prevents accidental adoption, not malicious file replacement.

Rehearsals and resets share a process lock. Use a single API worker and stop the API before running the reset CLI; concurrent processes or external SQLite writers are unsupported. The three-file reset is sequential, not one atomic transaction. Sandbox files persist for inspection; API review metadata remains in memory.
## Try the API

Use `/docs` to make these calls in sequence:

1. `POST /tasks` with `{"description":"Delete inactive customers"}`; copy `id`.
2. `POST /sandbox/run` with `{"task_id":"<id>"}`; copy the rehearsal `id`.
3. Inspect `GET /sandbox/runs/<id>`, `GET /diffs/<id>`, and `GET /risk/<id>`.
4. `POST /approval` with `{"run_id":"<id>","decision":"approve","reviewer":"local-reviewer"}`.
5. `POST /approval/apply` with `{"run_id":"<id>"}` returns `disabled_no_production_writes`. Before approval it returns 403.
6. `POST /approval/rollback` returns `nothing_applied`.

`GET /tasks/<id>` returns status and linked agent IDs. The rehearsal response contains all three agent records and the run ID used by review endpoints. Unknown IDs return 404.

## Agent results and configuration

`POST /sandbox/run` runs the rehearsal synchronously and returns all three normalized `RunResult` objects in `agents`. `GET /sandbox/runs/{run_id}` returns the same stored results, diffs and risk report.

Each result includes `id` (unique execution ID), `agent_id` (stable provider identity), `task_id`, `status`, `raw_output`, `error`, and `sql_operations`. Each SQL operation records its SQL, transaction status, row changes and error. `inserted_rows` contains postimages, `updated_rows` contains before/after pairs, and `deleted_rows` contains preimages. `affected_row_count` counts distinct rows touched by committed operations. Statement observations preserve an insert/update/delete sequence even when its final net effect is zero. Legacy `agent`, `sql`, and `changes` remain available; `changes` is the committed net diff used for consensus.

A failed statement rolls back that agent's entire transaction. Earlier operations remain in the audit result as `rolled_back`; committed row collections and affected count are empty. The remaining agents still run. Provider errors produce `failed` results, and incomplete rehearsals receive a critical risk warning. Unsupported tasks are `skipped`.

To configure behavior in Python, pass exactly three uniquely named `RehearsalAgent` implementations to `run_agents(task, settings, agents=providers)`. A provider implements `plan(task) -> AgentPlan`, returning SQL strings and raw output without receiving a database connection. `MockAgent(agent_id, dangerous_delete=False)` configures the supplied mocks. The API uses the `get_agents` FastAPI dependency; override it server-side to install other providers. Tests use stub providers exclusively.

The local executor currently allows only customer-table SELECT/INSERT/UPDATE/DELETE operations. SQLite authorization denies ATTACH, PRAGMA, DDL, explicit transaction commands and SQL functions; this restricts the demo executor but is not a hardened worker boundary. TODO: Gemma adapters, vetted SQL policy, hard deadlines and isolated Vultr workers before running real model-generated plans.
## Next steps

TODO: Gemma plan generation and privacy classification; Vultr worker isolation; durable authenticated review/audit storage; policy-validated SQL; transaction-bound approved diffs and rollback preimages; frontend dashboard. Heuristic SQL scanning and deterministic hashes are demo aids, not comprehensive injection detection or anonymization guarantees.

See [architecture](docs/architecture.md) and the [two-developer work split](docs/work-split.md).
