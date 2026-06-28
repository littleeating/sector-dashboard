# Sector Momentum Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a static daily-updated sector momentum dashboard that ranks industry and concept sectors by 5/10/20/30/45/60-trading-day cumulative returns and renders a combined trend chart.

**Architecture:** Add focused Python modules beside the existing stock filter code. `sector_momentum.py` owns pure calculations and SVG generation, `sector_data.py` owns safe source access and cache policy, and `sector_dashboard.py` is the CLI/rendering entry point. Tests avoid live network calls and verify behavior with fixed DataFrames and fake fetchers.

**Tech Stack:** Python 3.12, pandas, unittest, optional AKShare for live data, static HTML with inline CSS and inline SVG.

---

### Task 1: Pure Momentum Calculations

**Files:**
- Create: `sector_momentum.py`
- Test: `tests/test_sector_momentum.py`

- [ ] **Step 1: Write failing tests**

Add tests for cumulative returns, rankings, insufficient history skipping, and trend series.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_sector_momentum -v`
Expected: FAIL because `sector_momentum` does not exist.

- [ ] **Step 3: Implement minimal calculation code**

Create data classes for ranking rows and trend series, plus functions:
- `compute_return(history, period)`
- `rank_sectors(histories, periods, top_n)`
- `build_trend_series(histories, selected_names, lookback)`

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_sector_momentum -v`
Expected: PASS.

### Task 2: Safe Source Access And Cache Policy

**Files:**
- Create: `sector_data.py`
- Test: `tests/test_sector_data.py`

- [ ] **Step 1: Write failing tests**

Add tests for max worker validation, default single-thread settings, cache hit skipping external fetch, retry limit, and suspicious limit signal detection.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_sector_data -v`
Expected: FAIL because `sector_data` does not exist.

- [ ] **Step 3: Implement minimal safe data layer**

Create:
- `AccessPolicy`
- `SourceStatus`
- `CacheStore`
- `SuspiciousLimitError`
- `is_suspicious_limit_error(error)`
- `fetch_with_policy(fetcher, policy, status)`

Live AKShare adapters must be lazy imports so tests and offline HTML generation work without AKShare installed.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_sector_data -v`
Expected: PASS.

### Task 3: Static HTML And Inline SVG Rendering

**Files:**
- Create: `sector_dashboard.py`
- Test: `tests/test_sector_dashboard.py`

- [ ] **Step 1: Write failing tests**

Add tests that render a dashboard with fixed rankings and trend data, then assert the HTML includes title, both sector sections, all periods, source status, and an inline `<svg>`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_sector_dashboard -v`
Expected: FAIL because `sector_dashboard` does not exist.

- [ ] **Step 3: Implement renderer**

Create:
- `render_dashboard(context)`
- `build_svg_chart(series)`
- HTML escaping for names and status messages.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_sector_dashboard -v`
Expected: PASS.

### Task 4: CLI, README, And Sample Output

**Files:**
- Modify: `sector_dashboard.py`
- Modify: `README.md`
- Create: `output/sector_dashboard/index.html`

- [ ] **Step 1: Add failing CLI smoke test**

Add a test that calls a sample/offline generation function and confirms the output file is created.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_sector_dashboard -v`
Expected: FAIL because sample output generation is not implemented.

- [ ] **Step 3: Implement CLI**

Add:
- `parse_args()`
- `generate_sample_dashboard(output)`
- `main()`
- `--sample` mode for offline verification.

The live mode should try AKShare only when `--sample` is absent.

- [ ] **Step 4: Update README**

Document dependency installation, sample generation, live generation, safe concurrency defaults, and Windows Task Scheduler guidance.

- [ ] **Step 5: Generate sample dashboard**

Run: `python sector_dashboard.py --sample --output output/sector_dashboard/index.html`
Expected: file exists and contains the static dashboard.

### Task 5: Full Verification

**Files:**
- All new and modified files.

- [ ] **Step 1: Run full unit suite**

Run: `python -m unittest discover -s tests -v`
Expected: all tests pass.

- [ ] **Step 2: Inspect generated HTML**

Run a search for key strings: `板块动量看板`, `行业板块`, `概念板块`, `<svg`, `max-workers`.
Expected: the generated HTML contains `板块动量看板`, `行业板块`, `概念板块`, and `<svg`; `README.md` contains `max-workers`.

- [ ] **Step 3: Review git diff**

Run: `git diff --stat` and `git status --short`
Expected: only intended implementation/docs/sample files are changed, plus the pre-existing unstaged `output/selected.xlsx`.
