# AGENTS.md

## Setup
- Use `uv` for environment management in this repo. Python is pinned to `3.14` via `.python-version`, and `uv.lock` is present.
- Install deps with `uv sync`.

## Commands
- Run tests with `uv run python -m unittest discover -s tests -p 'test_*.py'`.
- Run one test with `uv run python -m unittest tests.test_api.AnswerCryptApiTests.test_store_question_and_retrieve_secret`.
- `uv run python -m unittest` from the repo root discovers `0` tests here; use `discover` or a fully qualified test path instead.

## App Wiring
- The FastAPI entrypoint is `app.main:app`.
- Startup calls `init_db()`, which creates `data/` and the SQLite database at `data/app.db` if missing.
- `data/` is local state and is gitignored; avoid relying on its contents in tests or review.

## Behavior That Tests Lock In
- `/store` requires an `X-API-Key` header that matches a row in the `api_key` table. The app creates tables on startup, but it does not seed an API key.
- Tests avoid `data/app.db`: they override `get_db` and use a temporary SQLite database per test case.
- Rate limiting is based on audit rows: `10` failed `/retrieve` attempts within `6` hours, counted only since the most recent `store_succeeded` audit. A new successful `/store` resets the effective limit by timestamp, not by deleting audit rows.
