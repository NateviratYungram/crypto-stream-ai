# Coverage Roadmap

Last validated baseline: `2026-06-02`

- Python unit tests: `450 passed`
- Raw all-source Python coverage before legacy exclusions: `26%`
- Maintained unit coverage gate: `88.77%`
- Frontend lines/statements coverage: `0%`
- Frontend functions/branches coverage: `5.45%`
- Coverage threshold: `70%`
- Current command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit --cov=chat_server --cov=intelligence --cov=mcp_server --cov=services --cov=streaming --cov=airflow --cov=data_quality_dag --cov-report=term-missing -q
```

## Coverage Streams

This roadmap uses three streams in parallel:

1. maintained Python coverage gate for day-to-day backend safety
2. raw all-source Python coverage for legacy drag reduction
3. frontend coverage for React and Vitest expansion

The plan reaches very high overall coverage only when all three move together.
Strong maintained Python coverage alone is not sufficient.

## Goal

Keep the maintained unit-testable Python surface above `70-80%` while separately reducing the raw all-source gap by combining:

- production refactors that improve testability
- high-value unit tests for business logic
- limited integration tests for key flows
- coverage ratchets in CI to prevent regressions

## Strategy

The repository will not reach `70-80%` sustainably by adding tests alone.
The largest blockers are:

- very large files with mixed business logic and side effects
- import-time globals and singleton state
- direct DB/network/MT5/file access inside orchestration methods
- low cohesion in legacy modules such as `chat_server.py`

The roadmap therefore follows this order:

1. refactor to improve testability
2. close medium-sized low-coverage modules
3. split legacy large files into smaller units
4. add flow-level integration tests
5. enforce coverage thresholds in CI

## Milestones

### Milestone 1: `15% -> 25%`

Focus:

- finish medium modules that are still low coverage
- eliminate easy-to-fix resource leaks
- standardize test doubles for DB, HTTP, clock, filesystem

Exit criteria:

- raw all-source coverage at least `25%`
- all new and modified files at least `85%`
- no new `ResourceWarning` from modules touched in this milestone

### Milestone 2: `25% -> 40%`

Focus:

- services, connectors, bridge modules
- convert orchestration code to use dependency injection
- add reusable fake repositories and client adapters

Exit criteria:

- raw all-source coverage at least `40%`
- service and bridge modules average at least `70%`

### Milestone 3: `40% -> 55%`

Focus:

- split large modules into cohesive units
- move validation, parsing, formatting, and policy logic into testable modules

Exit criteria:

- `chat_server.py` reduced substantially or replaced by multiple smaller modules
- `market_tools.py` and `technical_engine.py` split into smaller files
- raw all-source coverage at least `55%`

### Milestone 4: `55% -> 70%`

Focus:

- contract and integration tests for key flows
- repository-layer tests with temporary databases
- API-level golden path and failure path coverage

Exit criteria:

- raw all-source coverage at least `70%`
- critical modules at least `85-90%`

### Milestone 5: `70% -> 80%`

Focus:

- close residual gaps in high-churn modules
- coverage ratchets and ownership rules
- remove or isolate remaining untestable legacy behavior

Exit criteria:

- raw all-source coverage `70-80%`
- new code coverage gate active in CI

## Backlog

### Tier 1: Highest ROI now

These are medium or large modules that should move the overall number quickly with manageable refactoring.

| Priority | File | Current | Target | Why it matters | Work type |
|---|---|---:|---:|---|---|
| P0 | [services/notification_service.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/services/notification_service.py) | 16% | 80% | Central outbound side effects; easy to adapterize | Refactor + unit tests |
| P0 | [intelligence/ml/outcome_tracker.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/outcome_tracker.py) | 11% | 85% | ML feedback loop, medium sized, likely DB-bound but testable | Refactor + unit tests |
| P0 | [intelligence/mt5_bridge_server.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/mt5_bridge_server.py) | 14% | 75% | Large and important orchestration layer | Adapter split + API tests |
| P0 | [intelligence/mt5_connector.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/mt5_connector.py) | 25% | 80% | Execution-critical integration logic | Adapter split + unit tests |
| P0 | [streaming/lake_writer.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/streaming/lake_writer.py) | 45% | 85% | Bounded logic and persistence behavior | Unit tests |
| P0 | [streaming/producer.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/streaming/producer.py) | 56% | 90% | Medium module, high ROI to finish | Unit tests |

### Tier 2: Medium ROI after Tier 1

| Priority | File | Current | Target | Why it matters | Work type |
|---|---|---:|---:|---|---|
| P1 | [intelligence/persistence_utils.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/persistence_utils.py) | 14% | 90% | Utility-heavy and likely easy to isolate | Unit tests |
| P1 | [intelligence/sentinel/alpha_sentinel.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/sentinel/alpha_sentinel.py) | 18% | 80% | Decision logic likely pure enough for tests | Refactor + unit tests |
| P1 | [intelligence/risk_manager.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/risk_manager.py) | 12% | 85% | Risk logic should be well covered | Unit tests |
| P1 | [intelligence/ml/risk_manager.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/risk_manager.py) | 100% | 80% | Completely dark module in critical ML path | Refactor + unit tests |
| P1 | [intelligence/ml/watchdog.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/watchdog.py) | 100% | 100% | Easy to finish completely | Small tests |
| P1 | [intelligence/ml/readiness.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/readiness.py) | 50% | 90% | Governs promotion and live readiness | Branch tests |

### Tier 3: Large legacy modules that must be split

These are mandatory for `70-80%`.

| Priority | File | Current | Target | Why it matters | Work type |
|---|---|---:|---:|---|---|
| P0 | [chat_server.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/chat_server.py) | 9% | 70%+ after split | Largest drag on total coverage | Major decomposition |
| P0 | [intelligence/tools/market_tools.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/tools/market_tools.py) | 4% | 70%+ after split | Massive utility/orchestration surface | Major decomposition |
| P0 | [intelligence/technical_engine.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/technical_engine.py) | 5% | 80% after split | Core indicator logic | Extract pure indicator modules |
| P0 | [intelligence/ml/signal_model.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/signal_model.py) | 12% | 75% after split | Huge ML orchestration and persistence logic | Split training/inference/promotion |
| P1 | [intelligence/rag/retrieval.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/rag/retrieval.py) | 16% | 80% after split | Retrieval pipeline likely separable into scoring/filtering layers | Split + unit tests |

## Refactor Plan by Area

### 1. Chat Server Decomposition

Target file:

- [chat_server.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/chat_server.py)

Proposed extraction order:

- `chat_server/auth.py`
- `chat_server/sessions.py`
- `chat_server/websocket_handlers.py`
- `chat_server/message_router.py`
- `chat_server/tool_dispatch.py`
- `chat_server/persistence.py`
- `chat_server/formatters.py`
- `chat_server/api_routes.py`

Testing goals:

- route behavior
- auth and permission branches
- websocket payload formatting
- session lifecycle
- tool dispatch rules
- persistence wrappers with fake repo

Coverage expectation:

- before split: difficult to move above `20-30%`
- after split: extracted modules individually `80-95%`

### 2. Market Tools Decomposition

Target file:

- [intelligence/tools/market_tools.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/tools/market_tools.py)

Proposed extraction order:

- symbol normalization and parsing
- request validation
- market data retrieval adapters
- calculation helpers
- response formatting
- tool registration wrappers

Testing goals:

- parameter normalization
- validation errors
- deterministic calculation helpers
- response payload shape

### 3. Signal Model Decomposition

Target file:

- [intelligence/ml/signal_model.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/signal_model.py)

Proposed extraction order:

- dataset builders
- feature assembly
- promotion gate logic
- model cache and file IO
- inference adapters
- paper label ingestion

Testing goals:

- feature selection branches
- promotion decisions
- cache behavior
- load/save failure handling
- dataset filtering logic

## Test Architecture Backlog

### Shared test utilities to add

- [x] `tests/fakes/fake_clock.py`
- [x] `tests/fakes/fake_db.py`
- [x] `tests/fakes/fake_http.py`
- [x] `tests/fakes/fake_mt5.py`
- [x] `tests/fakes/fake_repository.py`
- [x] `tests/fakes/runtime_stubs.py`

### Fixture improvements

- deterministic paper trade fixture
- deterministic market OHLCV fixture
- fake promotion history fixture
- fake websocket session fixture
- fake telegram client fixture

### Integration test targets

- MCP query endpoint success + rejection paths
- MT5 bridge request/response lifecycle
- notification fallback paths
- anomaly detection -> persistence -> reporting
- training -> promotion -> readiness flow

## CI Plan

### Stage 1

- keep overall gate relaxed
- enforce `changed files >= 85%`
- publish `htmlcov/` and `coverage.xml`

### Stage 2

- enforce per-package minimums:
  - `intelligence/ml >= 70%`
  - `mcp_server >= 80%`
  - `streaming >= 80%`
  - `services >= 75%`

### Stage 3

- ratchet overall minimum upward:
  - `20%`
  - `30%`
  - `40%`
  - `50%`
  - `60%`
  - `70%`

## Definition of Done

A module is considered complete when:

- it has deterministic unit tests
- key success and failure branches are covered
- resources are closed properly
- side effects are behind injectable adapters
- no new warnings are introduced by its tests
- target coverage for that module is met

## Recommended Execution Order

### Sprint 1

- `services/notification_service.py`
- `intelligence/ml/outcome_tracker.py`
- `streaming/lake_writer.py`
- `streaming/producer.py`

Expected outcome:

- overall coverage near `20-25%`

### Sprint 2

- `intelligence/mt5_connector.py`
- `intelligence/mt5_bridge_server.py`
- `intelligence/persistence_utils.py`
- `intelligence/sentinel/alpha_sentinel.py`

Expected outcome:

- overall coverage near `30-40%`

### Sprint 3

- begin `chat_server.py` split
- begin `market_tools.py` split
- add shared fake adapters

Expected outcome:

- overall coverage near `45-55%`

### Sprint 4

- continue `chat_server.py`
- continue `signal_model.py`
- add integration coverage for key flows

Expected outcome:

- overall coverage near `60-70%`

### Sprint 5

- finish legacy decomposition
- raise CI gates
- close residual module gaps

Expected outcome:

- overall coverage `70-80%`

## Immediate Next Task

Start with:

1. [services/notification_service.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/services/notification_service.py)
2. [intelligence/ml/outcome_tracker.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/outcome_tracker.py)
3. [streaming/lake_writer.py](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/streaming/lake_writer.py)

These three should give the fastest honest push toward `20%+` while improving the architecture for larger refactors later.

## Current Execution Status

- Done:
  - clarified the three coverage metrics in [`docs/CODE_COVERAGE.md`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/docs/CODE_COVERAGE.md)
  - extracted reusable test doubles into [`tests/fakes/`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/tests/fakes)
  - slimmed [`tests/unit/conftest.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/tests/unit/conftest.py) to shared bootstrap wiring
  - drove [`services/notification_service.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/services/notification_service.py) to `100%` module coverage
  - verified [`streaming/lake_writer.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/streaming/lake_writer.py) at `100%` module coverage
  - verified [`streaming/producer.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/streaming/producer.py) at `100%` module coverage
  - verified [`intelligence/ml/outcome_tracker.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/outcome_tracker.py) at `100%` module coverage
  - verified [`intelligence/persistence_utils.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/persistence_utils.py) at `100%` module coverage
  - verified [`intelligence/mt5_connector.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/mt5_connector.py) at `100%` module coverage
  - verified [`intelligence/mt5_bridge_server.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/mt5_bridge_server.py) at `100%` module coverage
  - verified [`intelligence/sentinel/alpha_sentinel.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/sentinel/alpha_sentinel.py) at `100%` module coverage
  - drove [`intelligence/ml/reporting.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/reporting.py) to `100%` module coverage while fixing SQLite connection cleanup with an explicit closing helper
  - drove [`intelligence/ml/watchdog.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/watchdog.py) to `100%` module coverage
  - drove [`intelligence/ml/risk_manager.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/risk_manager.py) to `100%` module coverage
  - drove [`intelligence/risk_manager.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/risk_manager.py) to `100%` module coverage by closing the remaining meaningful branch and removing an unreachable single-symbol correlation path
  - drove [`intelligence/ml/readiness.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/readiness.py) to `100%` module coverage by removing an unreachable empty-group branch and covering unknown-side live gating
  - drove [`intelligence/ml/performance_feedback.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/performance_feedback.py) to `100%` module coverage while fixing explicit SQLite connection cleanup and adding cache/tailwind/gate branch tests
  - drove [`intelligence/ml/trading_quality_gate.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/trading_quality_gate.py) to `100%` module coverage with direct `_base_gate()` caching/floor-path tests and user-facing gate checks
  - drove [`intelligence/ml/symbol_policy.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/symbol_policy.py) to `100%` module coverage while fixing explicit SQLite connection cleanup and covering parser, cache, override, DB fallback, and snapshot branches
  - drove [`intelligence/ml/signal_model_support_helpers.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/signal_model_support_helpers.py) to `100%` module coverage by covering sparse dataset/report paths, pruning edge cases, calibration helpers, and promotion-gate override/failure logic
  - drove [`intelligence/ml/symbol_threshold.py`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/intelligence/ml/symbol_threshold.py) to `100%` module coverage by covering helper thresholds, file-loading fallbacks, DB/query failures, stock/no-side skips, cache refresh, and fallback lookups
  - started the frontend stream with tests for [`frontend/src/contexts/LanguageContext.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/contexts/LanguageContext.tsx), [`frontend/src/contexts/ModeContext.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/contexts/ModeContext.tsx), and [`frontend/src/hooks/useWebSocket.ts`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/hooks/useWebSocket.ts)
  - added [`frontend/src/test/setupTests.ts`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/test/setupTests.ts) so React/Vitest act integration is configured cleanly
  - decoupled [`frontend/vitest.config.ts`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/vitest.config.ts) from [`frontend/vite.config.ts`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/vite.config.ts) so targeted Vitest runs stay stable in direct coverage verification
  - expanded the frontend stream into small reusable UI components with coverage on [`frontend/src/components/HoverGlowCard.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/HoverGlowCard.tsx), [`frontend/src/components/TabSkeleton.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/TabSkeleton.tsx), and [`frontend/src/components/Tooltip.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/Tooltip.tsx)
  - drove [`frontend/src/components/ErrorBoundary.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/ErrorBoundary.tsx) to `100%` file coverage with focused Vitest coverage on recovery, details toggling, reload, and unknown-error fallback
  - drove [`frontend/src/components/AnimatedCounter.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/AnimatedCounter.tsx) to `100%` file coverage as a shared motion/display primitive
  - drove [`frontend/src/components/CommandPalette.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/CommandPalette.tsx) to `100%` file coverage across filtering, keyboard navigation, institutional-mode gating, export/reload actions, and open/close focus lifecycle
  - drove [`frontend/src/components/ShortcutsHelp.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/ShortcutsHelp.tsx) to `100%` file coverage for modal rendering and close paths
  - drove [`frontend/src/components/MoneyFlow.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/MoneyFlow.tsx) to `100%` file coverage for session-backed subtab hydration, visited-tab retention, and theme variants
  - drove [`frontend/src/components/RiskAlerts.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/RiskAlerts.tsx) to `100%` file coverage for session-backed subtab hydration, visited-tab retention, and theme variants
  - drove [`frontend/src/components/StrategyLab.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/StrategyLab.tsx) to `100%` file coverage for session-backed subtab hydration, visited-tab retention, and theme variants
  - drove [`frontend/src/components/AlphaTerminal.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/AlphaTerminal.tsx) to `100%` file coverage for session-backed subtab hydration, quick execution navigation, and lazy-tab retention while removing an unused language-context import
  - drove [`frontend/src/components/FundingRatesView.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/FundingRatesView.tsx) to `100%` line coverage with targeted fetch success, refresh, empty-state, and error-path verification while removing an unused icon import
  - drove [`frontend/src/components/TradingJournalView.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/TradingJournalView.tsx) to `100%` line coverage with stats validation, filter behavior, grade bands, refresh coverage, and removal of an unreachable filter fallback branch
  - drove [`frontend/src/components/WatchlistPanel.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/WatchlistPanel.tsx) to `100%` line coverage with load/add/remove/refresh flows, note-empty/price-empty rendering, API failure alerts, and network failure handling
  - drove [`frontend/src/components/OnboardingTour.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/OnboardingTour.tsx) to `100%` file coverage with step progression, tab hand-off, and dismiss/complete coverage in [`frontend/src/components/OnboardingTour.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/OnboardingTour.test.tsx)
  - drove [`frontend/src/components/PersonaSettings.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/PersonaSettings.tsx) to `100%` line coverage with load, reload, preset, save, theme, and timer-reset coverage in [`frontend/src/components/PersonaSettings.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/PersonaSettings.test.tsx)
  - expanded [`frontend/src/components/MarketIntelligence.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/MarketIntelligence.tsx) to a verified medium-panel test surface with session hydration, visited-tab retention, theme variants, and idle-preload cleanup coverage in [`frontend/src/components/MarketIntelligence.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/MarketIntelligence.test.tsx)
  - expanded [`frontend/src/components/EconomicCalendarView.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/EconomicCalendarView.tsx) to `90%+` line coverage with live-feed rendering, cache hydration, range/filter interactions, refresh polling, watch-only fallback, and light-theme coverage in [`frontend/src/components/EconomicCalendarView.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/EconomicCalendarView.test.tsx)
  - simplified [`frontend/src/components/TradingViewWidget.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/TradingViewWidget.tsx) by collapsing redundant ref guards, keeping `100%` line coverage and improving targeted branch coverage through [`frontend/src/components/TradingViewWidget.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/TradingViewWidget.test.tsx)
  - expanded [`frontend/src/components/AlertsReviewsView.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/AlertsReviewsView.tsx) to `98%+` line coverage with fetched-data rendering, tab switching, dismiss flows, refresh/auto-refresh behavior, telegram success/error states, and light-theme empty-state coverage in [`frontend/src/components/AlertsReviewsView.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/AlertsReviewsView.test.tsx)
  - expanded [`frontend/src/components/DataAnomaliesView.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/DataAnomaliesView.tsx) to `100%` line coverage with anomaly loading, hour-range switching, refresh polling, empty-state, and light-theme error-path coverage in [`frontend/src/components/DataAnomaliesView.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/DataAnomaliesView.test.tsx)
  - expanded [`frontend/src/components/RiskAuditsView.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/RiskAuditsView.tsx) to `96%+` line coverage with paper-trade KPI rendering, log filtering, show-all toggling, refresh behavior, websocket DQ alert injection, and light-theme fallback coverage in [`frontend/src/components/RiskAuditsView.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/RiskAuditsView.test.tsx)
  - expanded [`frontend/src/components/BestAiControlView.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/BestAiControlView.tsx) to `100%` line coverage with control loading, sync/build actions, refresh polling, recommendations/guard rendering, and light-theme failure-path coverage in [`frontend/src/components/BestAiControlView.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/BestAiControlView.test.tsx)
  - stabilized [`frontend/src/components/PnLTracker.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/PnLTracker.tsx) by replacing the inline default `bootstrapSignals = []` dependency trap with a shared empty constant, then drove the panel to `100%` line coverage and `90%+` branch coverage across bootstrap simulation, websocket updates, MTM ticks, initial fetch, live-account sync, and light-theme empty-state coverage in [`frontend/src/components/PnLTracker.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/PnLTracker.test.tsx)
  - expanded [`frontend/src/components/PortfolioCenter.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/PortfolioCenter.tsx) to `95%+` line coverage with empty-state, quick-load error handling, wallet identity rendering, explorer links, tab toggling, priced-filter toggling, sort interactions, pagination, and clear-reset coverage in [`frontend/src/components/PortfolioCenter.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/PortfolioCenter.test.tsx)
  - drove [`frontend/src/components/layout/AppSidebar.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/layout/AppSidebar.tsx) to `100%` file coverage with focused dark/light theme, mobile callback, status, settings, and logout coverage in [`frontend/src/components/layout/AppSidebar.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/layout/AppSidebar.test.tsx)
  - drove [`frontend/src/components/layout/MarketStatusClock.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/layout/MarketStatusClock.tsx) to `100%` file coverage with backend-success, local fallback, session-rotation, invalid-time, and holiday-state coverage in [`frontend/src/components/layout/MarketStatusClock.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/layout/MarketStatusClock.test.tsx)
  - simplified [`frontend/src/components/layout/AppNavbar.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/layout/AppNavbar.tsx) by removing dead notification-fetching surface that had no rendered UI path, then drove the remaining visible app-shell behavior to `100%` file coverage with [`frontend/src/components/layout/AppNavbar.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/layout/AppNavbar.test.tsx)
  - drove [`frontend/src/components/layout/MainLayout.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/layout/MainLayout.tsx) to `100%` file coverage with focused drawer, ticker, active-tab, overflow, and mobile-nav interaction coverage in [`frontend/src/components/layout/MainLayout.test.tsx`](/C:/Users/pea01/OneDrive/Desktop/crypto-stream-ai/frontend/src/components/layout/MainLayout.test.tsx)
- Next:
  - move the next backend tranche into the remaining ML surfaces around promotion orchestration and integration flows
  - widen the frontend stream from the now-covered app-shell/layout spine, subtab shells, onboarding/settings surfaces, and first fetch-heavy panels into the remaining medium-complexity shared panels before tackling the giant dashboard files
  - continue the frontend medium-panel tranche with the remaining execution and analytics surfaces before stepping into the largest dashboard files
  - measure the next raw Python bump after the current backend tranche is folded into a full coverage run
