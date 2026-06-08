# Code Coverage

This repository tracks three different coverage views. They answer different
questions, so the team should avoid collapsing them into a single number.

## Coverage Metrics

Last validated artifacts: `2026-06-02`

| Metric | Current baseline | What it includes | Source of truth |
|---|---:|---|---|
| Maintained Python coverage gate | `88.77%` | Python modules included by [`.coveragerc`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/.coveragerc) after legacy omissions | [`docs/CODE_COVERAGE.md`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/docs/CODE_COVERAGE.md), [`.coveragerc`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/.coveragerc) |
| Raw all-source Python coverage | `25.89%` | Full Python surface measured by the latest [`coverage.json`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/coverage.json) artifact | [`coverage.json`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/coverage.json), [`docs/COVERAGE_ROADMAP.md`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/docs/COVERAGE_ROADMAP.md) |
| Frontend coverage | `0%` lines/statements, `5.45%` functions/branches | Current Vitest frontend report in [`frontend/coverage/coverage-summary.json`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/coverage/coverage-summary.json) | [`frontend/coverage/coverage-summary.json`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/coverage/coverage-summary.json) |

## How To Read The Numbers

- Use the maintained Python gate to protect day-to-day backend work.
- Use raw all-source Python coverage to measure real progress against legacy
  drag and refactoring work.
- Use frontend coverage as its own stream until the UI test surface is large
  enough to contribute meaningfully to a combined repo-level target.

The current combined repo picture is still dragged down by excluded legacy
backend files and near-zero frontend coverage. Until those are addressed, the
maintained Python gate should not be treated as equivalent to full-project
coverage.

## Python

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run coverage:

```powershell
python -m pytest --cov=chat_server --cov=intelligence --cov=mcp_server --cov=services --cov=streaming --cov=airflow --cov=data_quality_dag --cov-report=term-missing --cov-report=html --cov-report=xml
```

The Python coverage gate is configured in [`.coveragerc`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/.coveragerc)
with `fail_under = 70`.

As of `2026-06-02`, the maintained unit-testable surface reports `88.77%`
coverage with `450 passed`. Legacy monoliths and side-effect-heavy orchestration
modules are excluded from the gate and tracked separately in
[`docs/COVERAGE_ROADMAP.md`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/docs/COVERAGE_ROADMAP.md).

Artifacts:

- `htmlcov/`
- `coverage.xml`
- `coverage.json`

Configuration lives in:

- `pytest.ini`
- `.coveragerc`

## Frontend

Install dependencies:

```powershell
cd frontend
npm install
```

Run frontend tests:

```powershell
npm run test
```

Run frontend coverage:

```powershell
npm run coverage
```

Artifacts:

- `frontend/coverage/`

Configuration lives in:

- `frontend/vitest.config.ts`

## Shared Test Infrastructure

Reusable test doubles now live under [`tests/fakes/`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/tests/fakes):

- `fake_clock.py` for deterministic time control
- `fake_db.py` for cursor/connection execution history
- `fake_http.py` for async HTTP request capture
- `fake_mt5.py` for configurable MT5 connector responses
- `fake_repository.py` for in-memory repository-style tests

Unit-test bootstrap now imports shared runtime stubs from
[`tests/fakes/runtime_stubs.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/tests/fakes/runtime_stubs.py)
through [`tests/unit/conftest.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/tests/unit/conftest.py).

## Run both

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\run_coverage.ps1
```

Optional flags:

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\run_coverage.ps1 -PythonOnly
powershell -ExecutionPolicy Bypass -File .\\scripts\\run_coverage.ps1 -FrontendOnly
```
