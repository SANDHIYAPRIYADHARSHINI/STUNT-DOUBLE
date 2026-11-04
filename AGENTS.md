# Working on Stunt Double

This is a safety-first AI agent project. Never create code that directly executes unapproved production database changes. Production writes are disabled in this scaffold, even after approval.

Structure: `app/api/` contains HTTP routers; `app/services/` contains privacy, mock agents, diffing, risk, and approval logic; `app/db.py` owns SQLite sandbox copies; `app/models.py` and `app/schemas.py` define contracts; `tests/` verifies core logic; `docs/` describes architecture and ownership.

Commands (Python 3.11+):
- Install: `python -m pip install -r requirements.txt`
- API: `python -m uvicorn app.main:app --reload`
- Tests: `python -m pytest`
- Lint: `python -m ruff check .`
- Format: `python -m ruff format .`

Require type hints and docstrings for public functions, and tests for core logic. Use mock/stub LLM responses in tests. Never commit secrets, API keys, database credentials, or real customer data. Preserve explicit human approval checks. Future production adapters need authentication, durable audit storage, concurrency controls, and transactional rollback before enabling writes.
