# Sector Constituent Stock Rankings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add expandable top-20 constituent stock rankings and matching stock trend charts for each ranked sector and period.

**Architecture:** Reuse existing sector ranking periods as the driver: for each ranked sector row, load that sector's constituents, fetch/cache each constituent's daily history, rank stocks by the same period as the clicked sector, and render the stock table plus stock chart into the static page. All external access remains sequential through `AccessPolicy` and `CacheStore`; only ranked sectors are expanded into stock requests to keep source pressure bounded.

**Tech Stack:** Python 3.12, pandas, unittest, AKShare/Eastmoney live data, static HTML, inline SVG, inline JavaScript.

---

### Task 1: Stock Ranking Data Shape

**Files:**
- Modify: `sector_dashboard.py`
- Test: `tests/test_sector_dashboard.py`

- [ ] **Step 1: Write the failing render test**

Add a test that passes `sector_stock_rankings` and `sector_stock_chart_series` into `render_dashboard`:

```python
context["sector_stock_rankings"] = {
    "industry": {
        5: {
            "半导体": [
                RankingRow("测试股份", 18.5, "2026-06-26", 12.3),
            ]
        }
    },
    "concept": {},
}
context["sector_stock_chart_series"] = {
    "industry": {
        5: {
            "半导体": [
                TrendSeries(
                    name="测试股份",
                    points=[
                        TrendPoint("2026-06-25", 0.0),
                        TrendPoint("2026-06-26", 18.5),
                    ],
                )
            ]
        }
    },
    "concept": {},
}
html = render_dashboard(context)
self.assertIn('class="sector-row"', html)
self.assertIn('data-stock-panel-key="industry-5-半导体"', html)
self.assertIn("测试股份", html)
self.assertIn("showSectorStocks", html)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_sector_dashboard
```

Expected: FAIL because ranking rows are not clickable and stock panels do not render.

- [ ] **Step 3: Add render data lookups**

Change `_render_rankings` signature to accept `stock_rankings` and `stock_chart_series`. Use a stable key made from category, period, and escaped board name for each row. Render each ranked sector row as a button-like table row plus a hidden detail row.

```python
stock_rows = stock_rankings.get(category, {}).get(period, {}).get(row.name, [])
stock_series = stock_chart_series.get(category, {}).get(period, {}).get(row.name, [])
panel_key = f"{category}-{period}-{row.name}"
```

- [ ] **Step 4: Run test to verify it passes**

Run the same unittest command. Expected: PASS.

### Task 2: Expandable Stock Table And Stock Chart UI

**Files:**
- Modify: `sector_dashboard.py`
- Test: `tests/test_sector_dashboard.py`

- [ ] **Step 1: Write failing interaction assertions**

Extend the render test to assert:

```python
self.assertIn('class="stock-detail"', html)
self.assertIn("板块内涨幅前20名股票", html)
self.assertIn("showStockChart", html)
self.assertIn('data-chart-key="stock-industry-5-半导体"', html)
```

- [ ] **Step 2: Implement hidden stock detail rows**

Inside each sector ranking card, render a second `<tr class="stock-detail" hidden>` after every sector row. The detail cell spans 4 columns and includes:

```html
<div class="stock-detail-body">
  <div class="stock-detail-title">板块内涨幅前20名股票</div>
  <button type="button" onclick="showStockChart('stock-industry-5-半导体')">查看股票趋势图</button>
  <table class="stock-table">...</table>
</div>
```

- [ ] **Step 3: Add stock chart panels**

Extend `_render_chart_panels` so it also renders hidden panels for `stock_chart_series`. Use `build_svg_chart(stock_series)` so the stock chart has the same axes, daily markers, line style, and clickable legend highlighting as the sector chart.

- [ ] **Step 4: Add JavaScript**

Add:

```javascript
function showSectorStocks(button) {
  const key = button.dataset.stockPanelKey;
  const detail = document.querySelector(`.stock-detail[data-stock-panel-key="${CSS.escape(key)}"]`);
  if (!detail) return;
  const willOpen = detail.hidden;
  document.querySelectorAll('.stock-detail').forEach((node) => { node.hidden = true; });
  document.querySelectorAll('.sector-row').forEach((node) => { node.classList.remove('expanded'); });
  detail.hidden = !willOpen;
  button.classList.toggle('expanded', willOpen);
  if (willOpen && button.dataset.stockChartKey) {
    showStockChart(button.dataset.stockChartKey);
  }
}

function showStockChart(key) {
  showPeriodChart(key);
}
```

- [ ] **Step 5: Run render tests**

Run:

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_sector_dashboard
```

Expected: PASS.

### Task 3: Live Constituent Fetch And Cache

**Files:**
- Modify: `sector_dashboard.py`
- Modify: `sector_data.py` if a generic JSON cache helper is needed
- Test: `tests/test_sector_dashboard.py`

- [ ] **Step 1: Write failing live data test**

Patch live fetchers so no network is used. Verify only ranked sectors request constituents and stock histories:

```python
with patch("sector_dashboard._fetch_eastmoney_board_constituents", return_value=[
    StockInfo(name="测试股份", code="600000"),
]):
    with patch("sector_dashboard._fetch_eastmoney_stock_history", return_value=pd.DataFrame({
        "date": ["2026-06-25", "2026-06-26"],
        "close": [10, 12],
    })):
        context = _build_context(..., include_stock_rankings=True)
        self.assertEqual(context["sector_stock_rankings"]["industry"][1]["半导体"][0].name, "测试股份")
```

- [ ] **Step 2: Add `StockInfo` and fetch adapters**

Add:

```python
@dataclass(frozen=True)
class StockInfo:
    name: str
    code: str
```

Add `_fetch_eastmoney_board_constituents(board, endpoint)` using Eastmoney board constituent endpoint or AKShare board constituent function after confirming available columns in local tests. Add `_fetch_eastmoney_stock_history(stock, start_date, end_date)` using daily K-line endpoint with Shanghai/Shenzhen secid inference.

- [ ] **Step 3: Build stock rankings from ranked sectors**

Add `_build_sector_stock_context(...)` that loops categories, periods, ranked board rows, constituents, and cached stock histories. It returns:

```python
sector_stock_rankings: dict[str, dict[int, dict[str, list[RankingRow]]]]
sector_stock_chart_series: dict[str, dict[int, dict[str, list[TrendSeries]]]]
```

For each sector-period pair, rank constituents by that same period and keep top 20. Build trend series with `lookback=period + 1`.

- [ ] **Step 4: Enforce source safety**

Use `get_or_fetch_history` for stock histories with category names like `stock_history/industry/半导体`. Use `fetch_with_policy` or a small cached JSON helper for constituent lists. Keep `max_workers` validation unchanged and keep actual requests sequential. Add quality counters:

```python
quality["stock_sector_count"] = len(selected_sector_keys)
quality["stock_history_short"] = stock_quality["history_short"]
quality["stock_rankings_enabled"] = True
```

- [ ] **Step 5: Run live-data unit tests**

Run:

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_sector_dashboard
```

Expected: PASS.

### Task 4: Sample Data, README, And Output

**Files:**
- Modify: `sector_dashboard.py`
- Modify: `README.md`
- Modify: `output/sector_dashboard/index.html`

- [ ] **Step 1: Add sample stock histories**

Extend `generate_sample_dashboard` so every sample ranked sector has deterministic sample stocks, for example `房地产开发股01` through `房地产开发股20`, with 70 business-day histories.

- [ ] **Step 2: Document source pressure**

Update README to state that constituent stock data multiplies requests, but only for ranked sectors; all live requests remain sequential, cached, delayed, and capped by `AccessPolicy`.

- [ ] **Step 3: Generate output without live requests**

Run:

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' sector_dashboard.py --sample --output output\sector_dashboard\index.html
```

Expected: output contains expandable stock rankings and stock charts.

### Task 5: Verification And Deployment Prep

**Files:**
- All modified files.

- [ ] **Step 1: Run full unit suite**

Run:

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 2: Run a no-network HTML structure check**

Run a Python snippet that reads `output/sector_dashboard/index.html` and prints counts for `sector-row`, `stock-detail`, `stock-table`, and `stock-` chart panels. Expected: all counts are greater than zero and no `mode: sample` marker appears in live output.

- [ ] **Step 3: Run browser or DOM interaction check**

If Browser plugin works, open the local file and click a sector row, then click a stock chart legend. If Browser is unavailable, run a Node DOM simulation for `showSectorStocks`, `showStockChart`, and legend highlighting.

- [ ] **Step 4: Review git status**

Run:

```powershell
git status --short --branch
git diff --stat
```

Expected: only intended files are changed; preserve the pre-existing local `output/selected.xlsx` modification.

