from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from sector_data import AccessPolicy, CacheStore, SourceStatus, fetch_with_policy, get_or_fetch_history, load_akshare
from sector_momentum import RankingRow, TrendPoint, TrendSeries, build_trend_series, rank_sectors


DEFAULT_PERIODS = [5, 10, 20, 30, 45, 60]
DEFAULT_TOP_N = 20
DEFAULT_STOCK_TOP_N = 10
DEFAULT_STOCK_SNAPSHOT_DAYS = 61
LIVE_CACHE_VERSION = "akshare-board-name-v2"
SOURCE_LABELS = {
    "industry": "东方财富行业板块（AKShare）",
    "concept": "东方财富概念板块（AKShare）",
}
EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


@dataclass(frozen=True)
class BoardInfo:
    name: str
    code: str


@dataclass(frozen=True)
class StockInfo:
    name: str
    code: str


def render_dashboard(context: dict[str, Any]) -> str:
    periods = [int(period) for period in context["periods"]]
    industry_rankings = context["industry_rankings"]
    concept_rankings = context["concept_rankings"]
    period_chart_series = context.get("period_chart_series", {"industry": {}, "concept": {}})
    sector_stock_rankings = context.get("sector_stock_rankings", {"industry": {}, "concept": {}})
    sector_stock_chart_series = context.get("sector_stock_chart_series", {"industry": {}, "concept": {}})
    source_labels = context.get("source_labels", SOURCE_LABELS)
    source_statuses = context.get("source_statuses", [])
    quality = context.get("quality", {})
    stock_top_n = int(context.get("stock_top_n", DEFAULT_STOCK_TOP_N))

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>板块动量看板</title>",
            f"<style>{_stylesheet()}</style>",
            "</head>",
            "<body>",
            '<main class="shell">',
            _render_header(context),
            '<section class="chart-section">',
            '<div class="chart-heading">',
            "<h2>趋势对比</h2>",
            '<p id="chart-caption">默认显示各周期榜首去重后的重点板块。点击下方任一周期排名，可切换为该周期全部入榜板块曲线。</p>',
            "</div>",
            _render_chart_panels(context.get("trend_series", []), period_chart_series, sector_stock_chart_series),
            "</section>",
            _render_rankings("行业板块", "industry", source_labels.get("industry", ""), industry_rankings, periods, sector_stock_rankings, stock_top_n),
            _render_rankings("概念板块", "concept", source_labels.get("concept", ""), concept_rankings, periods, sector_stock_rankings, stock_top_n),
            _render_statuses(source_statuses, quality),
            "</main>",
            _interaction_script(),
            "</body>",
            "</html>",
        ]
    )


def build_svg_chart(series: list[TrendSeries]) -> str:
    width = 980
    height = 460
    pad_left = 76
    pad_right = 30
    pad_top = 46
    pad_bottom = 148

    if not series:
        return '<div class="empty-chart">暂无可绘制趋势数据</div>'

    all_values = [point.return_pct for item in series for point in item.points]
    min_value = min(min(all_values), 0)
    max_value = max(max(all_values), 0)
    if min_value == max_value:
        max_value = min_value + 1

    domain_dates = sorted({point.date for item in series for point in item.points})
    date_indexes = {date: index for index, date in enumerate(domain_dates)}
    x_span = max(len(domain_dates) - 1, 1)
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom

    def x_at(index: int) -> float:
        return pad_left + plot_width * index / x_span

    def x_for_date(date: str) -> float:
        return x_at(date_indexes[date])

    def y_at(value: float) -> float:
        return pad_top + (max_value - value) * plot_height / (max_value - min_value)

    def show_day_label(index: int) -> bool:
        if len(domain_dates) <= 12:
            return True
        step = max(1, (len(domain_dates) - 1) // 10)
        return index in {0, len(domain_dates) - 1} or index % step == 0

    colors = [
        "#d83b36",
        "#0078d4",
        "#107c10",
        "#8764b8",
        "#ca5010",
        "#008575",
        "#8a2a2b",
        "#004e8c",
        "#b146c2",
        "#69797e",
        "#e3008c",
        "#00a2ad",
        "#ffaa44",
        "#744da9",
        "#498205",
        "#c23934",
        "#005e50",
        "#6b69d6",
        "#a4262c",
        "#038387",
    ]
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="重点板块累计涨幅趋势图">',
        f'<text class="axis-title y-title" x="{pad_left}" y="24">涨幅(%)</text>',
        f'<text class="axis-title x-title" x="{width - pad_right}" y="{height - pad_bottom + 24}" text-anchor="end">时间</text>',
        f'<line class="axis" x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{height - pad_bottom}" />',
        f'<line class="axis" x1="{pad_left}" y1="{height - pad_bottom}" x2="{width - pad_right}" y2="{height - pad_bottom}" />',
    ]

    for date_index, date in enumerate(domain_dates):
        x = x_for_date(date)
        label = date[5:] if len(date) >= 10 else date
        parts.append(f'<line class="day-tick" x1="{x:.2f}" y1="{height - pad_bottom}" x2="{x:.2f}" y2="{height - pad_bottom + 6}" />')
        if show_day_label(date_index):
            parts.append(
                f'<text class="day-label" x="{x:.2f}" y="{height - pad_bottom + 22}" transform="rotate(45 {x:.2f} {height - pad_bottom + 22})">{html.escape(label)}</text>'
            )

    for tick_value in [min_value, 0, max_value]:
        y = y_at(tick_value)
        parts.append(f'<line class="grid" x1="{pad_left}" y1="{y:.2f}" x2="{width - pad_right}" y2="{y:.2f}" />')
        parts.append(f'<text class="tick" x="{pad_left - 12}" y="{y + 4:.2f}" text-anchor="end">{tick_value:.1f}%</text>')

    legend_y = height - pad_bottom + 62
    for index, item in enumerate(series):
        color = colors[index % len(colors)]
        series_id = f"series-{index}"
        points = " ".join(
            f"{x_for_date(point.date):.2f},{y_at(point.return_pct):.2f}"
            for point in item.points
        )
        parts.append(f'<g class="series-group" data-series-id="{series_id}">')
        parts.append(f'<polyline class="trend" points="{points}" stroke="{color}" />')
        for point in item.points:
            x = x_for_date(point.date)
            y = y_at(point.return_pct)
            parts.append(
                f'<circle class="daily-point" cx="{x:.2f}" cy="{y:.2f}" r="2.8" fill="{color}"><title>{html.escape(point.date)}: {point.return_pct:.2f}%</title></circle>'
            )
        parts.append("</g>")
        legend_x = pad_left + (index % 5) * 176
        row_y = legend_y + (index // 5) * 20
        parts.append(
            f'<g class="legend-item" data-series-id="{series_id}" role="button" tabindex="0" '
            f'aria-label="高亮 {html.escape(item.name)}" onclick="selectLegendSeries(this)" '
            f'onkeydown="handleLegendKey(event, this)">'
        )
        parts.append(f'<line class="legend-swatch" x1="{legend_x}" y1="{row_y}" x2="{legend_x + 20}" y2="{row_y}" stroke="{color}" stroke-width="2.5" />')
        parts.append(f'<text class="legend" x="{legend_x + 28}" y="{row_y + 4}">{html.escape(item.name)}</text>')
        parts.append("</g>")

    parts.append("</svg>")
    return "\n".join(parts)


def _render_chart_panels(
    overview_series: list[TrendSeries],
    period_chart_series: dict[str, dict[int, list[TrendSeries]]],
    sector_stock_chart_series: dict[str, dict[int, dict[str, list[TrendSeries]]]] | None = None,
) -> str:
    panels = [
        f'<div class="chart-panel active" data-chart-key="overview" data-chart-title="重点板块趋势对比">{build_svg_chart(overview_series)}</div>'
    ]
    labels = {"industry": "行业板块", "concept": "概念板块"}
    for category in ("industry", "concept"):
        for period, series in sorted(period_chart_series.get(category, {}).items()):
            title = f"{labels[category]} {period}日入榜板块趋势"
            panels.append(
                f'<div class="chart-panel" data-chart-key="{category}-{period}" data-chart-title="{html.escape(title)}" hidden>{build_svg_chart(series)}</div>'
            )
    for category, periods in (sector_stock_chart_series or {}).items():
        label = labels.get(category, category)
        for period, boards in sorted(periods.items()):
            for board_name, series in boards.items():
                key = _stock_chart_key(category, period, board_name)
                title = f"{label} {board_name} {period}日股票涨幅趋势"
                panels.append(
                    f'<div class="chart-panel stock-chart-panel" data-chart-key="{html.escape(key, quote=True)}" '
                    f'data-chart-title="{html.escape(title, quote=True)}" hidden>{build_svg_chart(series)}</div>'
                )
    return "\n".join(panels)


def _render_header(context: dict[str, Any]) -> str:
    return f"""
<header class="hero">
  <div>
    <h1>板块动量看板</h1>
    <p>按最近可用交易日回看 5、10、20、30、45、60 个交易日，跟踪累计涨幅领先的行业与概念板块。</p>
  </div>
  <dl class="meta">
    <div><dt>最近数据日期</dt><dd>{html.escape(str(context["data_date"]))}</dd></div>
    <div><dt>生成时间</dt><dd>{html.escape(str(context["generated_at"]))}</dd></div>
    <div><dt>行业板块</dt><dd>{int(context.get("industry_count", 0))}</dd></div>
    <div><dt>概念板块</dt><dd>{int(context.get("concept_count", 0))}</dd></div>
  </dl>
</header>
"""


def _render_rankings(
    title: str,
    category: str,
    source_label: str,
    rankings: dict[int, list[RankingRow]],
    periods: list[int],
    sector_stock_rankings: dict[str, dict[int, dict[str, list[RankingRow]]]] | None = None,
    stock_top_n: int = DEFAULT_STOCK_TOP_N,
) -> str:
    cards = []
    for period in periods:
        rows = rankings.get(period, [])
        if rows:
            rendered_rows = []
            for rank, row in enumerate(rows, start=1):
                stock_rows = (
                    sector_stock_rankings
                    or {}
                ).get(category, {}).get(period, {}).get(row.name, [])
                panel_key = _stock_panel_key(category, period, row.name)
                chart_key = _stock_chart_key(category, period, row.name)
                rendered_rows.append(
                    f'<tr class="sector-row" role="button" tabindex="0" '
                    f'data-stock-panel-key="{html.escape(panel_key, quote=True)}" '
                    f'data-stock-chart-key="{html.escape(chart_key, quote=True)}" '
                    f'aria-expanded="false" onclick="showSectorStocks(this)" '
                    f'onkeydown="handleSectorRowKey(event, this)">'
                    f"<td>{rank}</td><td>{html.escape(row.name)}</td><td>{row.return_pct:.2f}%</td><td>{row.latest_close:.2f}</td></tr>"
                )
                rendered_rows.append(_render_stock_detail_row(panel_key, stock_rows, stock_top_n))
            body = "\n".join(rendered_rows)
        else:
            body = '<tr><td colspan="4" class="empty">暂无足够历史数据</td></tr>'
        cards.append(
            f"""
<article class="ranking-card">
  <button class="period-button" type="button" data-chart-key="{category}-{period}" onclick="showPeriodChart('{category}-{period}')">{period}日</button>
  <table>
    <thead><tr><th>名次</th><th>板块</th><th>累计涨幅</th><th>收盘</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
</article>
"""
        )

    return f"""
<section class="rank-section">
  <div class="section-title">
    <h2>{html.escape(title)}</h2>
    <p>数据来源：{html.escape(source_label)}</p>
  </div>
  <div class="ranking-grid">
    {''.join(cards)}
  </div>
</section>
"""


def _render_stock_detail_row(panel_key: str, stock_rows: list[RankingRow], stock_top_n: int = DEFAULT_STOCK_TOP_N) -> str:
    chart_key = "stock-" + panel_key
    if stock_rows:
        rows = "\n".join(
            f"<tr><td>{rank}</td><td>{html.escape(row.name)}</td><td>{row.return_pct:.2f}%</td><td>{row.latest_close:.2f}</td></tr>"
            for rank, row in enumerate(stock_rows, start=1)
        )
    else:
        rows = '<tr><td colspan="4" class="empty">暂无可用个股数据</td></tr>'
    return f"""
<tr class="stock-detail" data-stock-panel-key="{html.escape(panel_key, quote=True)}" hidden>
  <td colspan="4">
    <div class="stock-detail-body">
      <div class="stock-detail-heading">
        <strong>板块内涨幅前{stock_top_n}名股票</strong>
        <button class="stock-chart-button" type="button" data-stock-chart-key="{html.escape(chart_key, quote=True)}" onclick="showStockChart(this.dataset.stockChartKey)">查看股票趋势图</button>
      </div>
      <table class="stock-table">
        <thead><tr><th>名次</th><th>股票</th><th>累计涨幅</th><th>收盘</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </td>
</tr>
"""


def _stock_panel_key(category: str, period: int, board_name: str) -> str:
    return f"{category}-{period}-{board_name}"


def _stock_chart_key(category: str, period: int, board_name: str) -> str:
    return "stock-" + _stock_panel_key(category, period, board_name)


def _interaction_script() -> str:
    return """
<script>
function showPeriodChart(key) {
  const panels = document.querySelectorAll('.chart-panel');
  let activeTitle = '重点板块趋势对比';
  panels.forEach((panel) => {
    const isActive = panel.dataset.chartKey === key;
    panel.hidden = !isActive;
    panel.classList.toggle('active', isActive);
    if (isActive) {
      clearLegendSelection(panel);
    }
    if (isActive && panel.dataset.chartTitle) {
      activeTitle = panel.dataset.chartTitle;
    }
  });
  document.querySelectorAll('.period-button').forEach((button) => {
    button.classList.toggle('selected', button.dataset.chartKey === key);
  });
  const caption = document.getElementById('chart-caption');
  if (caption) {
    caption.textContent = activeTitle + '。再次点击其他周期可切换图表。';
  }
}

function findStockDetail(key) {
  return Array.from(document.querySelectorAll('.stock-detail')).find((node) => node.dataset.stockPanelKey === key);
}

function showSectorStocks(row) {
  const key = row.dataset.stockPanelKey;
  const detail = findStockDetail(key);
  if (!detail) {
    return;
  }
  const willOpen = detail.hidden;
  document.querySelectorAll('.stock-detail').forEach((node) => {
    node.hidden = true;
  });
  document.querySelectorAll('.sector-row').forEach((node) => {
    node.classList.remove('expanded');
    node.setAttribute('aria-expanded', 'false');
  });
  detail.hidden = !willOpen;
  row.classList.toggle('expanded', willOpen);
  row.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
  if (willOpen && row.dataset.stockChartKey) {
    showStockChart(row.dataset.stockChartKey);
  }
}

function showStockChart(key) {
  showPeriodChart(key);
}

function handleSectorRowKey(event, row) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    showSectorStocks(row);
  }
}

function clearLegendSelection(scope) {
  const root = scope || document;
  const selectionRoots = [];
  if (root.matches && (root.matches('.chart-panel') || root.matches('svg'))) {
    selectionRoots.push(root);
  }
  root.querySelectorAll('.chart-panel, svg').forEach((node) => {
    selectionRoots.push(node);
  });
  selectionRoots.forEach((node) => {
    node.classList.remove('has-selection');
    delete node.dataset.selectedSeries;
  });
  root.querySelectorAll('.series-group, .legend-item').forEach((node) => {
    node.classList.remove('selected', 'dimmed');
    if (node.classList.contains('legend-item')) {
      node.setAttribute('aria-pressed', 'false');
    }
  });
}

function selectLegendSeries(legendItem) {
  const panel = legendItem.closest('.chart-panel');
  const svg = legendItem.closest('svg');
  if (!panel || !svg) {
    return;
  }
  const seriesId = legendItem.dataset.seriesId;
  const isSelected = svg.dataset.selectedSeries === seriesId;
  clearLegendSelection(panel);
  if (isSelected) {
    return;
  }
  svg.dataset.selectedSeries = seriesId;
  svg.classList.add('has-selection');
  panel.classList.add('has-selection');
  panel.querySelectorAll('.series-group, .legend-item').forEach((node) => {
    const selected = node.dataset.seriesId === seriesId;
    node.classList.toggle('selected', selected);
    node.classList.toggle('dimmed', !selected);
    if (node.classList.contains('legend-item')) {
      node.setAttribute('aria-pressed', selected ? 'true' : 'false');
    }
  });
}

function handleLegendKey(event, legendItem) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    selectLegendSeries(legendItem);
  }
}
</script>
"""


def _render_statuses(statuses: list[SourceStatus], quality: dict[str, Any]) -> str:
    if statuses:
        status_rows = "\n".join(
            f"<tr><td>{html.escape(status.source)}</td><td>{status.requests}</td><td>{status.cache_hits}</td><td>{status.failed_requests}</td><td>{'是' if status.limited else '否'}</td><td>{html.escape('; '.join(status.messages))}</td></tr>"
            for status in statuses
        )
    else:
        status_rows = '<tr><td colspan="6" class="empty">暂无数据源状态</td></tr>'

    quality_items = "".join(
        f"<li>{html.escape(str(key))}: {html.escape(str(value))}</li>" for key, value in sorted(quality.items())
    )
    return f"""
<section class="status-section">
  <h2>数据源与异常</h2>
  <table>
    <thead><tr><th>数据源</th><th>请求数</th><th>缓存命中</th><th>失败数</th><th>疑似限流</th><th>提示</th></tr></thead>
    <tbody>{status_rows}</tbody>
  </table>
  <ul class="quality">{quality_items}</ul>
</section>
"""


def _stylesheet() -> str:
    return """
:root { color-scheme: light; --text: #202124; --muted: #5f6368; --line: #dadce0; --red: #c5221f; --green: #188038; --bg: #f7f8fa; --panel: #fff; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; }
.shell { max-width: 1280px; margin: 0 auto; padding: 24px; }
.hero { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; padding: 24px 0 18px; border-bottom: 1px solid var(--line); }
h1 { margin: 0 0 10px; font-size: 32px; line-height: 1.2; }
h2 { margin: 28px 0 14px; font-size: 22px; }
h3 { margin: 0 0 12px; font-size: 17px; }
p { margin: 0; color: var(--muted); line-height: 1.7; }
.meta { display: grid; grid-template-columns: repeat(2, minmax(130px, 1fr)); gap: 10px; margin: 0; min-width: 360px; }
.meta div, .ranking-card, .chart-section, .status-section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
.meta div { padding: 12px; }
dt { color: var(--muted); font-size: 12px; }
dd { margin: 4px 0 0; font-weight: 700; }
.chart-section, .status-section { padding: 18px; }
.chart-heading { display: flex; justify-content: space-between; gap: 18px; align-items: baseline; margin-bottom: 12px; }
.chart-heading h2 { margin-top: 0; }
.chart-heading p { max-width: 680px; font-size: 13px; }
.chart-panel[hidden] { display: none; }
.section-title { display: flex; justify-content: space-between; gap: 16px; align-items: baseline; }
.section-title p { font-size: 13px; }
.ranking-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.ranking-card { padding: 14px; min-width: 0; }
.period-button { width: 100%; margin: 0 0 12px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; background: #f8fafc; color: var(--text); font: inherit; font-weight: 700; text-align: left; cursor: pointer; }
.period-button:hover, .period-button.selected { border-color: #0078d4; color: #005a9e; background: #eef6ff; }
.sector-row { cursor: pointer; }
.sector-row:hover, .sector-row.expanded { background: #f8fbff; }
.sector-row:focus-visible { outline: 2px solid #0078d4; outline-offset: -2px; }
.stock-detail[hidden] { display: none; }
.stock-detail td { padding: 0; background: #fbfcfe; }
.stock-detail-body { padding: 10px 8px 12px; border-top: 1px solid #dfe8f5; }
.stock-detail-heading { display: flex; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 8px; color: var(--text); }
.stock-chart-button { border: 1px solid var(--line); border-radius: 6px; background: #fff; color: #005a9e; cursor: pointer; font: inherit; font-size: 12px; padding: 5px 8px; white-space: nowrap; }
.stock-chart-button:hover { border-color: #0078d4; background: #eef6ff; }
.stock-table { font-size: 12px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 6px; border-bottom: 1px solid #eceff3; text-align: right; white-space: nowrap; }
th:nth-child(2), td:nth-child(2), .status-section td:last-child { text-align: left; }
th { color: var(--muted); font-weight: 600; }
.empty { color: var(--muted); text-align: center !important; }
svg { width: 100%; height: auto; display: block; }
.axis { stroke: #9aa0a6; stroke-width: 1.2; }
.grid { stroke: #e8eaed; stroke-width: 1; }
.trend { fill: none; stroke-width: 2.35; stroke-linejoin: round; stroke-linecap: round; opacity: .86; }
.trend:hover { opacity: 1; stroke-width: 3; }
.series-group, .legend-item { transition: opacity .16s ease, filter .16s ease; }
.legend-item { cursor: pointer; outline: none; }
.legend-item:focus-visible .legend { fill: #005a9e; font-weight: 700; text-decoration: underline; }
.legend-item:focus-visible .legend-swatch { stroke-width: 4; }
.chart-panel.has-selection .series-group.dimmed, .chart-panel.has-selection .legend-item.dimmed { opacity: .16; }
.chart-panel.has-selection .series-group.selected .trend { opacity: 1; stroke-width: 4; filter: drop-shadow(0 1px 2px rgba(0, 0, 0, .20)); }
.chart-panel.has-selection .series-group.selected .daily-point { opacity: 1; stroke-width: 1.6; }
.chart-panel.has-selection .legend-item.selected .legend { fill: #202124; font-weight: 700; }
.chart-panel.has-selection .legend-item.selected .legend-swatch { stroke-width: 4; }
.axis-title { fill: #374151; font-size: 14px; font-weight: 700; }
.tick, .date-label, .day-label { fill: #5f6368; font-size: 10px; }
.legend { fill: #5f6368; font-size: 11.5px; }
.day-tick { stroke: #9aa0a6; stroke-width: 1; }
.daily-point { stroke: #fff; stroke-width: 1.2; opacity: .92; }
.daily-point:hover { r: 4; opacity: 1; }
.quality { color: var(--muted); line-height: 1.7; }
@media (max-width: 900px) { .hero, .chart-heading, .section-title { display: block; } .meta { margin-top: 16px; min-width: 0; } .ranking-grid { grid-template-columns: 1fr; } .shell { padding: 16px; } }
"""


def generate_sample_dashboard(output: str | Path) -> Path:
    output_path = Path(output)
    industry_names = _sample_industry_names()
    concept_names = _sample_concept_names()
    context = _build_context(
        industry_histories=_sample_histories(industry_names, base=1000),
        concept_histories=_sample_histories(concept_names, base=900),
        periods=DEFAULT_PERIODS,
        top_n=DEFAULT_TOP_N,
        source_statuses=[SourceStatus(source="sample", requests=0, cache_hits=0)],
        quality={"mode": "sample"},
        sector_stock_histories={
            "industry": _sample_sector_stock_histories(industry_names, base=20),
            "concept": _sample_sector_stock_histories(concept_names, base=16),
        },
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_dashboard(context), encoding="utf-8")
    return output_path


def _sample_industry_names() -> list[str]:
    return [
        "半导体",
        "软件开发",
        "小金属",
        "银行",
        "证券",
        "通信设备",
        "光伏设备",
        "电池",
        "消费电子",
        "汽车零部件",
        "医疗服务",
        "中药",
        "化学制药",
        "军工电子",
        "航天航空",
        "工程机械",
        "工业金属",
        "贵金属",
        "白酒",
        "食品饮料",
        "电力",
        "煤炭行业",
        "游戏",
        "互联网服务",
        "房地产开发",
    ]


def _sample_concept_names() -> list[str]:
    return [
        "机器人概念",
        "低空经济",
        "算力概念",
        "AI应用",
        "人工智能",
        "数据要素",
        "鸿蒙概念",
        "国产芯片",
        "第三代半导体",
        "先进封装",
        "液冷服务器",
        "云计算",
        "信创",
        "车联网",
        "无人驾驶",
        "固态电池",
        "储能",
        "光刻机",
        "商业航天",
        "卫星导航",
        "新型工业化",
        "中特估",
        "跨境支付",
        "数字货币",
        "创新药",
    ]


def generate_live_dashboard(
    output: str | Path,
    *,
    periods: list[int],
    top_n: int,
    cache_dir: str | Path,
    max_workers: int,
    min_delay: float,
    max_delay: float,
    stock_top_n: int = DEFAULT_STOCK_TOP_N,
    board_limit: int = 0,
    stock_sector_limit: int = 0,
    stock_constituent_limit: int = 0,
    stock_candidate_limit: int = 0,
    stock_snapshot_days: int = DEFAULT_STOCK_SNAPSHOT_DAYS,
    request_budget: int = 0,
    board_list_timeout: float = 30.0,
    stock_fetch_timeout: float = 30.0,
    data_source: str = "eastmoney",
    stock_data_source: str | None = None,
    sina_board_pool_limit: int = 40,
    cache_only: bool = False,
    board_cache_only: bool = False,
) -> Path:
    stock_data_source = stock_data_source or ("eastmoney_snapshot" if data_source == "eastmoney" else data_source)
    if data_source == "sina":
        return generate_sina_dashboard(
            output,
            periods=periods,
            top_n=top_n,
            stock_top_n=stock_top_n,
            cache_dir=cache_dir,
            max_workers=max_workers,
            min_delay=min_delay,
            max_delay=max_delay,
            board_limit=board_limit,
            stock_sector_limit=stock_sector_limit,
            stock_constituent_limit=stock_constituent_limit,
            stock_candidate_limit=stock_candidate_limit,
            request_budget=request_budget,
            stock_fetch_timeout=stock_fetch_timeout,
            sina_board_pool_limit=sina_board_pool_limit,
            cache_only=cache_only,
        )
    if data_source != "eastmoney":
        raise ValueError(f"unknown data source: {data_source}")

    # max_workers is validated and reported, but requests stay sequential in v1 to respect source limits.
    policy = AccessPolicy(max_workers=max_workers, min_delay=min_delay, max_delay=max_delay)
    cache = CacheStore(cache_dir, version=LIVE_CACHE_VERSION)
    if stock_data_source == "sina":
        status_source = "eastmoney+sina"
    elif stock_data_source == "eastmoney_snapshot":
        status_source = "eastmoney+snapshot"
    else:
        status_source = "eastmoney"
    status = SourceStatus(source=status_source)
    ak = load_akshare()
    today = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")

    industry_boards = _limit_boards(
        _load_board_infos_cached(
            cache=cache,
            category="industry",
            latest_date=today,
            fetcher=lambda: _fetch_akshare_board_list("industry", timeout_seconds=board_list_timeout),
            policy=policy,
            status=status,
        ),
        board_limit,
    )
    concept_boards = _limit_boards(
        _load_board_infos_cached(
            cache=cache,
            category="concept",
            latest_date=today,
            fetcher=lambda: _fetch_akshare_board_list("concept", timeout_seconds=board_list_timeout),
            policy=policy,
            status=status,
        ),
        board_limit,
    )

    industry_histories = _load_histories(
        cache=cache,
        category="industry",
        boards=industry_boards,
        latest_date=today,
        status=status,
        policy=policy,
        cache_only=cache_only or board_cache_only,
        fetcher_factory=lambda board: lambda: _fetch_eastmoney_board_history(
            board,
            start_date=start_date,
            end_date=end_date,
            endpoint="https://7.push2his.eastmoney.com/api/qt/stock/kline/get",
        ),
    )
    concept_histories = _load_histories(
        cache=cache,
        category="concept",
        boards=concept_boards,
        latest_date=today,
        status=status,
        policy=policy,
        cache_only=cache_only or board_cache_only,
        fetcher_factory=lambda board: lambda: _fetch_eastmoney_board_history(
            board,
            start_date=start_date,
            end_date=end_date,
            endpoint="https://91.push2his.eastmoney.com/api/qt/stock/kline/get",
        ),
    )

    base_context = _build_context(
        industry_histories=industry_histories,
        concept_histories=concept_histories,
        periods=periods,
        top_n=top_n,
        stock_top_n=stock_top_n,
        source_statuses=[status],
        quality={"max_workers": policy.max_workers},
    )
    stock_boards_by_category = {
        "industry": {board.name: board for board in industry_boards},
        "concept": {board.name: board for board in concept_boards},
    }
    stock_constituent_source = "eastmoney"
    if stock_data_source == "sina":
        stock_constituent_source = "sina"
        sina_industry_spot = fetch_with_policy(
            lambda: _fetch_sina_sector_spot("industry", timeout_seconds=stock_fetch_timeout),
            policy=policy,
            status=status,
        )
        sina_concept_spot = fetch_with_policy(
            lambda: _fetch_sina_sector_spot("concept", timeout_seconds=stock_fetch_timeout),
            policy=policy,
            status=status,
        )
        sina_stock_spot = pd.concat([sina_industry_spot, sina_concept_spot], ignore_index=True)
        stock_boards_by_category = {
            "industry": _map_boards_to_sina_labels(industry_boards, sina_stock_spot),
            "concept": _map_boards_to_sina_labels(concept_boards, sina_stock_spot),
        }
    stock_cache = cache
    if stock_data_source == "sina":
        stock_cache = CacheStore(cache_dir, version=f"{LIVE_CACHE_VERSION}-sina-v1")

    sector_stock_histories = _load_sector_stock_histories(
        cache=stock_cache,
        akshare_client=ak,
        periods=periods,
        rankings_by_category={
            "industry": base_context["industry_rankings"],
            "concept": base_context["concept_rankings"],
        },
        boards_by_category=stock_boards_by_category,
        latest_date=today,
        start_date=start_date,
        end_date=end_date,
        status=status,
        policy=policy,
        stock_sector_limit=stock_sector_limit,
        stock_constituent_limit=stock_constituent_limit,
        stock_candidate_limit=stock_candidate_limit,
        stock_top_n=stock_top_n,
        stock_snapshot_days=stock_snapshot_days,
        request_budget=request_budget,
        stock_fetch_timeout=stock_fetch_timeout,
        source=stock_constituent_source,
        stock_history_source=stock_data_source,
    )
    context = _build_context(
        industry_histories=industry_histories,
        concept_histories=concept_histories,
        periods=periods,
        top_n=top_n,
        stock_top_n=stock_top_n,
        source_statuses=[status],
        quality={
            "max_workers": policy.max_workers,
            "stock_sector_limit": stock_sector_limit,
            "stock_constituent_limit": stock_constituent_limit,
            "stock_candidate_limit": stock_candidate_limit,
            "stock_snapshot_days": stock_snapshot_days,
            "request_budget": request_budget,
            "data_source": "eastmoney",
            "stock_data_source": stock_data_source,
        },
        sector_stock_histories=sector_stock_histories,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_dashboard(context), encoding="utf-8")
    return output_path


def generate_sina_dashboard(
    output: str | Path,
    *,
    periods: list[int],
    top_n: int,
    cache_dir: str | Path,
    max_workers: int,
    min_delay: float,
    max_delay: float,
    stock_top_n: int = DEFAULT_STOCK_TOP_N,
    board_limit: int = 0,
    stock_sector_limit: int = 0,
    stock_constituent_limit: int = 0,
    stock_candidate_limit: int = 0,
    request_budget: int = 0,
    stock_fetch_timeout: float = 30.0,
    sina_board_pool_limit: int = 40,
    cache_only: bool = False,
) -> Path:
    policy = AccessPolicy(max_workers=max_workers, min_delay=min_delay, max_delay=max_delay)
    cache = CacheStore(cache_dir, version=f"{LIVE_CACHE_VERSION}-sina-v1")
    status = SourceStatus(source="sina")
    today = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")

    industry_spot = fetch_with_policy(
        lambda: _fetch_sina_sector_spot("industry", timeout_seconds=stock_fetch_timeout),
        policy=policy,
        status=status,
    )
    concept_spot = fetch_with_policy(
        lambda: _fetch_sina_sector_spot("concept", timeout_seconds=stock_fetch_timeout),
        policy=policy,
        status=status,
    )
    industry_boards = _select_sina_board_pool(industry_spot, limit=board_limit or sina_board_pool_limit)
    concept_boards = _select_sina_board_pool(concept_spot, limit=board_limit or sina_board_pool_limit)

    seed_rankings = {
        "industry": _seed_rankings_from_spot(industry_spot, industry_boards, periods),
        "concept": _seed_rankings_from_spot(concept_spot, concept_boards, periods),
    }
    sector_stock_histories = _load_sector_stock_histories(
        cache=cache,
        akshare_client=None,
        periods=periods,
        rankings_by_category=seed_rankings,
        boards_by_category={
            "industry": {board.name: board for board in industry_boards},
            "concept": {board.name: board for board in concept_boards},
        },
        latest_date=today,
        start_date=start_date,
        end_date=end_date,
        status=status,
        policy=policy,
        stock_sector_limit=stock_sector_limit,
        stock_constituent_limit=stock_constituent_limit,
        stock_candidate_limit=stock_candidate_limit,
        stock_top_n=stock_top_n,
        request_budget=request_budget,
        stock_fetch_timeout=stock_fetch_timeout,
        source="sina",
        cache_only=cache_only,
    )
    aggregated = _aggregate_sector_histories_from_stocks(sector_stock_histories)
    context = _build_context(
        industry_histories=aggregated["industry"],
        concept_histories=aggregated["concept"],
        periods=periods,
        top_n=top_n,
        stock_top_n=stock_top_n,
        source_statuses=[status],
        quality={
            "max_workers": policy.max_workers,
            "stock_sector_limit": stock_sector_limit,
            "stock_constituent_limit": stock_constituent_limit,
            "stock_candidate_limit": stock_candidate_limit,
            "request_budget": request_budget,
            "data_source": "sina",
            "sina_board_pool_limit": sina_board_pool_limit,
        },
        sector_stock_histories=sector_stock_histories,
    )
    context["source_labels"] = {
        "industry": "新浪行业板块（成分股等权重建）",
        "concept": "新浪概念板块（成分股等权重建）",
    }
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_dashboard(context), encoding="utf-8")
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成行业和概念板块动量静态网页。")
    parser.add_argument("--output", default="output/sector_dashboard/index.html", help="输出 HTML 路径。")
    parser.add_argument("--sample", action="store_true", help="使用内置样例数据离线生成网页。")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="每个周期展示前 N 名。")
    parser.add_argument("--stock-top-n", type=int, default=DEFAULT_STOCK_TOP_N, help="每个板块展开显示的涨幅前 N 名股票。")
    parser.add_argument("--periods", default="5,10,20,30,45,60", help="逗号分隔的交易日周期。")
    parser.add_argument("--cache-dir", default="cache/sector_dashboard", help="缓存目录。")
    parser.add_argument("--max-workers", type=int, default=1, help="外部请求并行度，硬上限为 2；v1 仍顺序请求。")
    parser.add_argument("--min-delay", type=float, default=1.2, help="外部请求之间的最小随机延迟秒数。")
    parser.add_argument("--max-delay", type=float, default=2.5, help="外部请求之间的最大随机延迟秒数。")
    parser.add_argument("--board-limit", type=int, default=0, help="仅用于验证的每类板块数量限制；0 表示全量。")
    parser.add_argument("--stock-sector-limit", type=int, default=0, help="抓取个股明细的入榜板块数量限制；0 表示全量。")
    parser.add_argument("--stock-constituent-limit", type=int, default=0, help="每个板块抓取历史行情的成分股数量限制；0 表示全量。")
    parser.add_argument("--stock-candidate-limit", type=int, default=0, help="按跨板块重复度筛选每个板块候选股票数量；0 表示不启用。")
    parser.add_argument("--stock-snapshot-days", type=int, default=DEFAULT_STOCK_SNAPSHOT_DAYS, help="东方财富全市场历史快照交易日数量；默认 61 个点用于计算 60 日涨幅。")
    parser.add_argument("--request-budget", type=int, default=0, help="本轮最多新增外部请求数；0 表示不限制。")
    parser.add_argument("--board-list-timeout", type=float, default=30.0, help="板块清单接口单次等待秒数；超时后使用缓存兜底。")
    parser.add_argument("--stock-fetch-timeout", type=float, default=30.0, help="成分股和个股历史接口单次等待秒数；超时后跳过并继续。")
    parser.add_argument("--data-source", choices=["eastmoney", "sina"], default="eastmoney", help="行情数据源。")
    parser.add_argument("--stock-data-source", choices=["eastmoney", "eastmoney_snapshot", "sina"], default=None, help="个股数据源；东方财富模式默认使用全市场快照本地过滤。")
    parser.add_argument("--sina-board-pool-limit", type=int, default=40, help="新浪模式每类按当日涨跌幅进入候选池的板块数量。")
    parser.add_argument("--cache-only", action="store_true", help="只使用已有缓存生成页面，不新增外部请求。")
    parser.add_argument("--board-cache-only", action="store_true", help="只对板块历史使用缓存；股票数据仍按参数抓取或读取。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    periods = _parse_periods(args.periods)
    if args.sample:
        output = generate_sample_dashboard(args.output)
    else:
        output = generate_live_dashboard(
            args.output,
            periods=periods,
            top_n=args.top_n,
            stock_top_n=args.stock_top_n,
            cache_dir=args.cache_dir,
            max_workers=args.max_workers,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
            board_limit=args.board_limit,
            stock_sector_limit=args.stock_sector_limit,
            stock_constituent_limit=args.stock_constituent_limit,
            stock_candidate_limit=args.stock_candidate_limit,
            stock_snapshot_days=args.stock_snapshot_days,
            request_budget=args.request_budget,
            board_list_timeout=args.board_list_timeout,
            stock_fetch_timeout=args.stock_fetch_timeout,
            data_source=args.data_source,
            stock_data_source=args.stock_data_source,
            sina_board_pool_limit=args.sina_board_pool_limit,
            cache_only=args.cache_only,
            board_cache_only=args.board_cache_only,
        )
    print(f"板块动量看板已生成: {output.resolve()}")
    return 0


def _build_context(
    *,
    industry_histories: dict[str, pd.DataFrame],
    concept_histories: dict[str, pd.DataFrame],
    periods: list[int],
    top_n: int,
    stock_top_n: int | None = None,
    source_statuses: list[SourceStatus],
    quality: dict[str, Any],
    sector_stock_histories: dict[str, dict[str, dict[str, pd.DataFrame]]] | None = None,
) -> dict[str, Any]:
    stock_top_n = top_n if stock_top_n is None else stock_top_n
    industry_rankings, industry_quality = rank_sectors(industry_histories, periods, top_n)
    concept_rankings, concept_quality = rank_sectors(concept_histories, periods, top_n)
    selected_names = _selected_trend_names(industry_rankings, concept_rankings)
    all_histories = {**industry_histories, **concept_histories}
    trend_series = build_trend_series(all_histories, selected_names, lookback=max(periods) + 1)
    period_chart_series = {
        "industry": _build_period_chart_series(industry_histories, industry_rankings),
        "concept": _build_period_chart_series(concept_histories, concept_rankings),
    }
    sector_stock_rankings, sector_stock_chart_series, stock_quality = _build_sector_stock_context(
        sector_stock_histories or {"industry": {}, "concept": {}},
        {"industry": industry_rankings, "concept": concept_rankings},
        periods,
        stock_top_n,
    )
    data_date = _latest_data_date(all_histories)
    merged_quality = {
        **quality,
        "industry_history_short": industry_quality["history_short"],
        "concept_history_short": concept_quality["history_short"],
        **stock_quality,
    }
    return {
        "data_date": data_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "periods": periods,
        "industry_rankings": industry_rankings,
        "concept_rankings": concept_rankings,
        "stock_top_n": stock_top_n,
        "industry_count": len(industry_histories),
        "concept_count": len(concept_histories),
        "trend_series": trend_series,
        "period_chart_series": period_chart_series,
        "sector_stock_rankings": sector_stock_rankings,
        "sector_stock_chart_series": sector_stock_chart_series,
        "source_statuses": source_statuses,
        "source_labels": SOURCE_LABELS,
        "quality": merged_quality,
    }


def _build_period_chart_series(
    histories: dict[str, pd.DataFrame],
    rankings: dict[int, list[RankingRow]],
) -> dict[int, list[TrendSeries]]:
    output: dict[int, list[TrendSeries]] = {}
    for period, rows in rankings.items():
        names = [row.name for row in rows]
        output[period] = build_trend_series(histories, names, lookback=period + 1)
    return output


def _build_sector_stock_context(
    sector_stock_histories: dict[str, dict[str, dict[str, pd.DataFrame]]],
    rankings_by_category: dict[str, dict[int, list[RankingRow]]],
    periods: list[int],
    top_n: int,
) -> tuple[
    dict[str, dict[int, dict[str, list[RankingRow]]]],
    dict[str, dict[int, dict[str, list[TrendSeries]]]],
    dict[str, int | bool],
]:
    stock_rankings: dict[str, dict[int, dict[str, list[RankingRow]]]] = {"industry": {}, "concept": {}}
    stock_chart_series: dict[str, dict[int, dict[str, list[TrendSeries]]]] = {"industry": {}, "concept": {}}
    stock_history_short = 0
    stock_sector_count = 0

    for category, rankings in rankings_by_category.items():
        stock_rankings.setdefault(category, {})
        stock_chart_series.setdefault(category, {})
        histories_by_board = sector_stock_histories.get(category, {})
        for period in periods:
            stock_rankings[category].setdefault(period, {})
            stock_chart_series[category].setdefault(period, {})
            for sector_row in rankings.get(period, []):
                stock_histories = histories_by_board.get(sector_row.name, {})
                if not stock_histories:
                    stock_rankings[category][period][sector_row.name] = []
                    stock_chart_series[category][period][sector_row.name] = []
                    continue
                ranked, quality = rank_sectors(stock_histories, [period], top_n)
                rows = ranked.get(period, [])
                stock_rankings[category][period][sector_row.name] = rows
                stock_chart_series[category][period][sector_row.name] = build_trend_series(
                    stock_histories,
                    [row.name for row in rows],
                    lookback=period + 1,
                )
                stock_history_short += quality["history_short"]
                stock_sector_count += 1

    return stock_rankings, stock_chart_series, {
        "stock_rankings_enabled": bool(stock_sector_count),
        "stock_sector_count": stock_sector_count,
        "stock_history_short": stock_history_short,
    }


def _selected_trend_names(
    industry_rankings: dict[int, list[RankingRow]],
    concept_rankings: dict[int, list[RankingRow]],
) -> list[str]:
    names: list[str] = []
    for rankings in (industry_rankings, concept_rankings):
        for rows in rankings.values():
            if rows and rows[0].name not in names:
                names.append(rows[0].name)
    return names[:8]


def _sample_histories(names: list[str], base: float) -> dict[str, pd.DataFrame]:
    histories: dict[str, pd.DataFrame] = {}
    dates = pd.bdate_range(end=pd.Timestamp("2026-06-26"), periods=70).strftime("%Y-%m-%d")
    for index, name in enumerate(names):
        drift = 0.003 + index * 0.001
        wave = [((day % 9) - 4) * 0.001 for day in range(70)]
        prices = [round(base * (1 + drift * day + wave[day]), 2) for day in range(70)]
        histories[name] = pd.DataFrame({"date": dates, "close": prices})
    return histories


def _sample_sector_stock_histories(board_names: list[str], base: float) -> dict[str, dict[str, pd.DataFrame]]:
    output: dict[str, dict[str, pd.DataFrame]] = {}
    dates = pd.bdate_range(end=pd.Timestamp("2026-06-26"), periods=70).strftime("%Y-%m-%d")
    for board_index, board_name in enumerate(board_names):
        stocks: dict[str, pd.DataFrame] = {}
        for stock_index in range(20):
            drift = 0.002 + board_index * 0.0004 + stock_index * 0.0008
            wave = [((day + stock_index) % 7 - 3) * 0.0015 for day in range(70)]
            start = base + stock_index * 0.6 + board_index * 0.05
            prices = [round(start * (1 + drift * day + wave[day]), 2) for day in range(70)]
            stocks[f"{board_name}股{stock_index + 1:02d}"] = pd.DataFrame({"date": dates, "close": prices})
        output[board_name] = stocks
    return output


def _load_board_infos(fetcher: Any) -> list[BoardInfo]:
    frame = fetcher()
    required = {"板块名称", "板块代码"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("板块清单缺少字段: " + ", ".join(sorted(missing)))
    cleaned = frame.loc[:, ["板块名称", "板块代码"]].dropna()
    return [BoardInfo(name=str(row["板块名称"]), code=str(row["板块代码"])) for _, row in cleaned.iterrows()]


def _load_board_infos_cached(
    *,
    cache: CacheStore,
    category: str,
    latest_date: str,
    fetcher: Any,
    policy: AccessPolicy,
    status: SourceStatus,
) -> list[BoardInfo]:
    cache_category = "board_list"
    cached = cache.read_history(cache_category, category)
    try:
        frame = fetch_with_policy(fetcher, policy=policy, status=status)
        cache.write_history(cache_category, category, frame, data_date=latest_date)
        return _load_board_infos(lambda: frame)
    except Exception:
        if cached is None:
            boards_from_history = _board_infos_from_history_cache(cache, category)
            if boards_from_history:
                status.cache_hits += len(boards_from_history)
                status.messages.append(f"using cached {category} history names as board list")
                return boards_from_history
            raise
        frame, cached_date = cached
        status.cache_hits += 1
        status.messages.append(f"using cached board list for {category} from {cached_date}")
        return _load_board_infos(lambda: frame)


def _board_infos_from_history_cache(cache: CacheStore, category: str) -> list[BoardInfo]:
    return [BoardInfo(name=name, code="") for name in cache.list_history_names(category)]


def _fetch_akshare_board_list(category: str, *, timeout_seconds: float) -> pd.DataFrame:
    return _fetch_eastmoney_board_list(category, timeout_seconds=timeout_seconds or 20)


def _run_timed_worker(label: str, timeout_seconds: float, worker: Any, *args: Any) -> Any:
    import multiprocessing as mp

    queue: mp.Queue = mp.Queue(maxsize=1)
    process = mp.Process(target=worker, args=(*args, queue), daemon=True)
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise TimeoutError(f"{label} timed out after {timeout_seconds:.0f}s")

    if queue.empty():
        raise RuntimeError(f"{label} worker exited without data")

    state, payload = queue.get()
    if state == "ok":
        return payload
    raise RuntimeError(str(payload))


def _akshare_board_list_worker(category: str, queue: Any) -> None:
    try:
        frame = _fetch_akshare_board_list_direct(category)
        queue.put(("ok", frame.to_dict(orient="records")))
    except BaseException as exc:
        queue.put(("error", repr(exc)))


def _fetch_akshare_board_list_direct(category: str) -> pd.DataFrame:
    return _fetch_eastmoney_board_list(category, timeout_seconds=20)


def _fetch_eastmoney_board_list(category: str, *, timeout_seconds: float) -> pd.DataFrame:
    if category == "industry":
        url = "https://push2delay.eastmoney.com/api/qt/clist/get"
        fs = "m:90 t:2 f:!50"
        fid = "f3"
    elif category == "concept":
        url = "https://push2delay.eastmoney.com/api/qt/clist/get"
        fs = "m:90 t:3 f:!50"
        fid = "f12"
    else:
        raise ValueError(f"unknown board category: {category}")

    rows = _fetch_eastmoney_clist_rows(
        url,
        {
            "pn": "1",
            "pz": "5000",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": fid,
            "fs": fs,
            "fields": "f12,f14",
        },
        timeout_seconds=timeout_seconds,
    )
    return pd.DataFrame(
        [
            {"板块名称": str(row.get("f14", "")), "板块代码": str(row.get("f12", ""))}
            for row in rows
            if row.get("f14") and row.get("f12")
        ]
    )


def _limit_boards(boards: list[BoardInfo], limit: int) -> list[BoardInfo]:
    if limit < 0:
        raise ValueError("board_limit must not be negative")
    if limit == 0:
        return boards
    return boards[:limit]


def _load_histories(
    *,
    cache: CacheStore,
    category: str,
    boards: list[BoardInfo],
    latest_date: str,
    status: SourceStatus,
    policy: AccessPolicy,
    fetcher_factory: Any,
    cache_only: bool = False,
) -> dict[str, pd.DataFrame]:
    histories: dict[str, pd.DataFrame] = {}
    for board in boards:
        if status.limited:
            break
        try:
            if cache_only:
                cached = cache.read_history(category, board.name)
                if cached is None:
                    continue
                history, _ = cached
                status.cache_hits += 1
                histories[board.name] = history
            else:
                histories[board.name] = get_or_fetch_history(
                    cache=cache,
                    category=category,
                    name=board.name,
                    latest_date=latest_date,
                    fetcher=fetcher_factory(board),
                    policy=policy,
                    status=status,
                )
        except Exception as exc:
            status.messages.append(f"{board.name}: {exc}")
    return histories


def _load_sector_stock_histories(
    *,
    cache: CacheStore,
    akshare_client: Any,
    periods: list[int],
    rankings_by_category: dict[str, dict[int, list[RankingRow]]],
    boards_by_category: dict[str, dict[str, BoardInfo]],
    latest_date: str,
    start_date: str,
    end_date: str,
    status: SourceStatus,
    policy: AccessPolicy,
    stock_sector_limit: int,
    stock_constituent_limit: int,
    stock_candidate_limit: int = 0,
    stock_top_n: int = DEFAULT_STOCK_TOP_N,
    stock_snapshot_days: int = DEFAULT_STOCK_SNAPSHOT_DAYS,
    request_budget: int = 0,
    stock_fetch_timeout: float = 30.0,
    source: str = "eastmoney",
    stock_history_source: str | None = None,
    cache_only: bool = False,
) -> dict[str, dict[str, dict[str, pd.DataFrame]]]:
    stock_history_source = stock_history_source or source
    if stock_sector_limit < 0:
        raise ValueError("stock_sector_limit must not be negative")
    if stock_constituent_limit < 0:
        raise ValueError("stock_constituent_limit must not be negative")
    if stock_candidate_limit < 0:
        raise ValueError("stock_candidate_limit must not be negative")
    if stock_top_n <= 0:
        raise ValueError("stock_top_n must be greater than zero")
    if stock_snapshot_days <= 1:
        raise ValueError("stock_snapshot_days must be greater than one")
    if request_budget < 0:
        raise ValueError("request_budget must not be negative")

    output: dict[str, dict[str, dict[str, pd.DataFrame]]] = {"industry": {}, "concept": {}}
    selected = _selected_ranked_boards(rankings_by_category, boards_by_category, periods)
    if stock_sector_limit:
        selected = selected[:stock_sector_limit]

    constituents_by_board: dict[tuple[str, str], list[StockInfo]] = {}
    selected_with_constituents: list[tuple[str, BoardInfo]] = []
    for category, board in selected:
        if status.limited or _request_budget_reached(status, request_budget):
            break
        try:
            constituents = _get_or_fetch_constituents(
                cache=cache,
                category=category,
                board=board,
                latest_date=latest_date,
                status=status,
                policy=policy,
                cache_only=cache_only,
                fetcher=lambda category=category, board=board: _fetch_eastmoney_board_constituents(
                    board,
                    category=category,
                    akshare_client=akshare_client,
                    timeout_seconds=stock_fetch_timeout,
                    source=source,
                ),
            )
        except Exception as exc:
            status.messages.append(f"{board.name} constituents: {exc}")
            continue

        constituents_by_board[(category, board.name)] = constituents
        selected_with_constituents.append((category, board))

    if stock_history_source == "eastmoney_snapshot":
        if not selected_with_constituents:
            return output
        if status.limited or _request_budget_reached(status, request_budget):
            return output
        try:
            snapshot = _get_or_fetch_market_snapshot_history(
                cache=cache,
                latest_date=latest_date,
                status=status,
                policy=policy,
                timeout_seconds=stock_fetch_timeout,
                cache_only=cache_only,
                request_budget=request_budget,
                snapshot_days=max(stock_snapshot_days, (max(periods) + 1) if periods else stock_snapshot_days),
            )
        except Exception as exc:
            status.messages.append(f"eastmoney market snapshot: {exc}")
            return output

        snapshot_by_code = _market_snapshot_history_by_code(snapshot)
        for category, board in selected_with_constituents:
            stocks = constituents_by_board.get((category, board.name), [])
            output.setdefault(category, {}).setdefault(board.name, {})
            output[category][board.name].update(
                _snapshot_histories_for_constituents(
                    constituents=stocks,
                    snapshot_by_code=snapshot_by_code,
                )
            )
        return output

    candidates_by_board = _select_candidate_stocks_by_board(constituents_by_board, stock_candidate_limit)

    for category, board in selected_with_constituents:
        if status.limited or _request_budget_reached(status, request_budget):
            break
        stocks = candidates_by_board.get((category, board.name), [])
        if stock_constituent_limit:
            stocks = stocks[:stock_constituent_limit]
        output.setdefault(category, {}).setdefault(board.name, {})
        for stock in stocks:
            if status.limited or _request_budget_reached(status, request_budget):
                break
            try:
                if cache_only:
                    cached = cache.read_history("stock_history/global", _stock_cache_name(stock))
                    if cached is None:
                        continue
                    frame, _ = cached
                    status.cache_hits += 1
                    output[category][board.name][stock.name] = frame
                else:
                    output[category][board.name][stock.name] = get_or_fetch_history(
                        cache=cache,
                        category="stock_history/global",
                        name=_stock_cache_name(stock),
                        latest_date=latest_date,
                        fetcher=lambda stock=stock: _fetch_eastmoney_stock_history(
                            stock,
                            start_date=start_date,
                            end_date=end_date,
                            akshare_client=akshare_client,
                            timeout_seconds=stock_fetch_timeout,
                            source=stock_history_source,
                        ),
                        policy=policy,
                        status=status,
                    )
            except Exception as exc:
                status.messages.append(f"{board.name}/{stock.name}: {exc}")
    return output


def _select_candidate_stocks_by_board(
    constituents_by_board: dict[tuple[str, str], list[StockInfo]],
    candidate_limit: int,
) -> dict[tuple[str, str], list[StockInfo]]:
    if candidate_limit <= 0:
        return constituents_by_board

    frequencies = Counter(
        _stock_identity(stock)
        for constituents in constituents_by_board.values()
        for stock in constituents
    )
    selected: dict[tuple[str, str], list[StockInfo]] = {}
    for key, constituents in constituents_by_board.items():
        ranked = sorted(
            enumerate(constituents),
            key=lambda item: (-frequencies[_stock_identity(item[1])], item[0]),
        )
        selected[key] = [stock for _, stock in ranked[:candidate_limit]]
    return selected


def _get_or_fetch_market_snapshot(
    *,
    cache: CacheStore,
    latest_date: str,
    status: SourceStatus,
    policy: AccessPolicy,
    timeout_seconds: float,
    cache_only: bool = False,
    request_budget: int = 0,
) -> pd.DataFrame:
    cache_category = "stock_snapshot/global"
    cache_name = "eastmoney_market"
    cached = cache.read_history(cache_category, cache_name)
    if cached is not None:
        frame, cached_date = cached
        if cached_date == latest_date:
            status.cache_hits += 1
            return frame
    if cache_only:
        raise ValueError("missing cached eastmoney market snapshot")

    page_size = 100
    first_page, total = fetch_with_policy(
        lambda: _fetch_eastmoney_market_snapshot_page(1, page_size, timeout_seconds=timeout_seconds),
        policy=policy,
        status=status,
    )
    frames = [first_page]
    page_count = max(1, (int(total) + page_size - 1) // page_size)
    for page in range(2, page_count + 1):
        if status.limited or _request_budget_reached(status, request_budget):
            break
        page_frame, _ = fetch_with_policy(
            lambda page=page: _fetch_eastmoney_market_snapshot_page(page, page_size, timeout_seconds=timeout_seconds),
            policy=policy,
            status=status,
        )
        frames.append(page_frame)
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    cache.write_history(cache_category, cache_name, frame, data_date=latest_date)
    return frame


def _market_snapshot_by_code(snapshot: pd.DataFrame) -> dict[str, dict[str, Any]]:
    required = {"code", "name", "close", "return_pct"}
    missing = required - set(snapshot.columns)
    if missing:
        raise ValueError("eastmoney market snapshot missing columns: " + ", ".join(sorted(missing)))

    rows: dict[str, dict[str, Any]] = {}
    for _, row in snapshot.iterrows():
        code = _normalize_stock_code(str(row.get("code", "")))
        if not code:
            continue
        close = _to_float_or_none(row.get("close"))
        return_pct = _to_float_or_none(row.get("return_pct"))
        if close is None or return_pct is None:
            continue
        rows[code] = {
            "code": code,
            "name": str(row.get("name") or ""),
            "close": close,
            "return_pct": return_pct,
        }
    return rows


def _snapshot_histories_for_constituents(
    *,
    constituents: list[StockInfo],
    snapshot_by_code: dict[str, dict[str, Any]],
    latest_date: str,
    max_period: int,
    top_n: int,
) -> dict[str, pd.DataFrame]:
    matched: list[tuple[StockInfo, dict[str, Any]]] = []
    for stock in constituents:
        snapshot = snapshot_by_code.get(_normalize_stock_code(stock.code))
        if snapshot is not None:
            matched.append((stock, snapshot))

    selected = sorted(matched, key=lambda item: float(item[1]["return_pct"]), reverse=True)[:top_n]
    return {
        stock.name or str(snapshot.get("name") or stock.code): _snapshot_row_to_history(
            latest_date=latest_date,
            close=float(snapshot["close"]),
            return_pct=float(snapshot["return_pct"]),
            max_period=max_period,
        )
        for stock, snapshot in selected
    }


def _snapshot_row_to_history(*, latest_date: str, close: float, return_pct: float, max_period: int) -> pd.DataFrame:
    if close <= 0 or return_pct <= -100:
        return pd.DataFrame(columns=["date", "close"])
    base_close = close / (1 + return_pct / 100)
    try:
        latest = datetime.strptime(latest_date, "%Y-%m-%d")
    except ValueError:
        latest = datetime.now()
    rows = [
        {
            "date": (latest - timedelta(days=max_period - index)).strftime("%Y-%m-%d"),
            "close": round(base_close, 4),
        }
        for index in range(max_period)
    ]
    rows.append({"date": latest.strftime("%Y-%m-%d"), "close": round(close, 4)})
    return pd.DataFrame(rows)


def _get_or_fetch_market_snapshot_history(
    *,
    cache: CacheStore,
    latest_date: str,
    status: SourceStatus,
    policy: AccessPolicy,
    timeout_seconds: float,
    cache_only: bool = False,
    request_budget: int = 0,
    snapshot_days: int = DEFAULT_STOCK_SNAPSHOT_DAYS,
) -> pd.DataFrame:
    cache_category = "stock_snapshot/history"
    cache_name = f"eastmoney_market_{snapshot_days}"
    cached = cache.read_history(cache_category, cache_name)
    if cached is not None:
        frame, cached_date = cached
        if cached_date == latest_date:
            status.cache_hits += 1
            return frame
    if cache_only:
        raise ValueError("missing cached eastmoney market snapshot history")

    dates = fetch_with_policy(
        lambda: _fetch_eastmoney_snapshot_dates(snapshot_days, timeout_seconds=timeout_seconds),
        policy=policy,
        status=status,
    )
    frames: list[pd.DataFrame] = []
    for trade_date in dates:
        if status.limited or _request_budget_reached(status, request_budget):
            break
        day_frame = _get_or_fetch_market_snapshot_for_date(
            cache=cache,
            trade_date=trade_date,
            status=status,
            policy=policy,
            timeout_seconds=timeout_seconds,
            cache_only=cache_only,
            request_budget=request_budget,
        )
        if not day_frame.empty:
            frames.append(day_frame)
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    cache.write_history(cache_category, cache_name, frame, data_date=latest_date)
    return frame


def _get_or_fetch_market_snapshot_for_date(
    *,
    cache: CacheStore,
    trade_date: str,
    status: SourceStatus,
    policy: AccessPolicy,
    timeout_seconds: float,
    cache_only: bool = False,
    request_budget: int = 0,
) -> pd.DataFrame:
    cache_category = "stock_snapshot/daily"
    cached = cache.read_history(cache_category, trade_date)
    if cached is not None:
        frame, _ = cached
        status.cache_hits += 1
        return frame
    if cache_only:
        return pd.DataFrame()

    page_size = 5000
    first_page, total = fetch_with_policy(
        lambda: _fetch_eastmoney_market_snapshot_for_date(
            trade_date,
            page=1,
            page_size=page_size,
            timeout_seconds=timeout_seconds,
        ),
        policy=policy,
        status=status,
    )
    frames = [first_page]
    page_count = max(1, (int(total) + page_size - 1) // page_size)
    for page in range(2, page_count + 1):
        if status.limited or _request_budget_reached(status, request_budget):
            break
        page_frame, _ = fetch_with_policy(
            lambda page=page: _fetch_eastmoney_market_snapshot_for_date(
                trade_date,
                page=page,
                page_size=page_size,
                timeout_seconds=timeout_seconds,
            ),
            policy=policy,
            status=status,
        )
        frames.append(page_frame)
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    cache.write_history(cache_category, trade_date, frame, data_date=trade_date)
    return frame


def _market_snapshot_history_by_code(snapshot: pd.DataFrame) -> dict[str, pd.DataFrame]:
    required = {"code", "name", "date", "close"}
    missing = required - set(snapshot.columns)
    if missing:
        raise ValueError("eastmoney market snapshot history missing columns: " + ", ".join(sorted(missing)))

    rows: dict[str, list[dict[str, Any]]] = {}
    for _, row in snapshot.iterrows():
        code = _normalize_stock_code(str(row.get("code", "")))
        if not code:
            continue
        close = _to_float_or_none(row.get("close"))
        if close is None:
            continue
        rows.setdefault(code, []).append(
            {
                "code": code,
                "name": str(row.get("name") or ""),
                "date": str(row.get("date", ""))[:10],
                "close": close,
            }
        )
    return {
        code: pd.DataFrame(items)
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
        for code, items in rows.items()
        if items
    }


def _snapshot_histories_for_constituents(
    *,
    constituents: list[StockInfo],
    snapshot_by_code: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    histories: dict[str, pd.DataFrame] = {}
    for stock in constituents:
        history = snapshot_by_code.get(_normalize_stock_code(stock.code))
        if history is None or history.empty:
            continue
        histories[stock.name] = history.loc[:, ["date", "close"]].copy()
    return histories


def _select_sina_board_pool(spot: pd.DataFrame, limit: int) -> list[BoardInfo]:
    if limit < 0:
        raise ValueError("sina_board_pool_limit must not be negative")
    required = {"板块", "label", "涨跌幅"}
    missing = required - set(spot.columns)
    if missing:
        raise ValueError("新浪板块行情缺少字段: " + ", ".join(sorted(missing)))
    sorted_spot = spot.copy()
    sorted_spot["涨跌幅"] = pd.to_numeric(sorted_spot["涨跌幅"], errors="coerce")
    sorted_spot = sorted_spot.dropna(subset=["板块", "label", "涨跌幅"]).sort_values("涨跌幅", ascending=False)
    if limit:
        sorted_spot = sorted_spot.head(limit)
    return [BoardInfo(str(row["板块"]), str(row["label"])) for _, row in sorted_spot.iterrows()]


def _map_boards_to_sina_labels(boards: list[BoardInfo], spot: pd.DataFrame) -> dict[str, BoardInfo]:
    if "板块" not in spot.columns or "label" not in spot.columns:
        return {}
    label_by_name = {
        str(row["板块"]): str(row["label"])
        for _, row in spot.dropna(subset=["板块", "label"]).iterrows()
    }
    return {
        board.name: BoardInfo(board.name, label_by_name[board.name])
        for board in boards
        if board.name in label_by_name
    }


def _map_boards_to_sina_labels(boards: list[BoardInfo], spot: pd.DataFrame) -> dict[str, BoardInfo]:
    board_column = next((column for column in ("板块", "겼욥") if column in spot.columns), None)
    if board_column is None or "label" not in spot.columns:
        return {}

    label_by_name: dict[str, str] = {}
    normalized: dict[str, list[tuple[str, str]]] = {}
    for _, row in spot.dropna(subset=[board_column, "label"]).iterrows():
        name = str(row[board_column])
        label = str(row["label"])
        label_by_name[name] = label
        normalized.setdefault(_normalize_sina_board_name(name), []).append((name, label))

    mapped: dict[str, BoardInfo] = {}
    for board in boards:
        if board.name in label_by_name:
            mapped[board.name] = BoardInfo(board.name, label_by_name[board.name])
            continue

        board_key = _normalize_sina_board_name(board.name)
        candidates = normalized.get(board_key, [])
        if not candidates:
            candidates = _contained_sina_board_candidates(board_key, normalized)
        if not candidates:
            alias_name = _sina_board_alias_name(board_key)
            if alias_name and alias_name in label_by_name:
                candidates = [(alias_name, label_by_name[alias_name])]
        if len(candidates) == 1:
            mapped[board.name] = BoardInfo(board.name, candidates[0][1])
    return mapped


def _normalize_sina_board_name(name: str) -> str:
    normalized = re.sub(r"[\s,，、（）()·\-_/]", "", str(name).strip())
    normalized = re.sub(r"(概念|板块)$", "", normalized)
    normalized = re.sub(r"[ⅠⅡⅢIV]+$", "", normalized)
    return normalized.upper()


def _contained_sina_board_candidates(
    board_key: str,
    normalized: dict[str, list[tuple[str, str]]],
) -> list[tuple[str, str]]:
    if len(board_key) < 3:
        return []
    matches: list[tuple[str, str]] = []
    for spot_key, candidates in normalized.items():
        if len(spot_key) < 3:
            continue
        if board_key in spot_key or spot_key in board_key:
            matches.extend(candidates)
    return matches


def _sina_board_alias_name(board_key: str) -> str | None:
    aliases = [
        (
            (
                "半导体",
                "集成电路",
                "芯片",
                "分立器件",
                "光学光电子",
                "光学元件",
                "印制电路",
                "电子化学品",
                "面板",
                "元件",
                "LED",
                "其他电子",
            ),
            "计算机、通信和其他电子设备制造业",
        ),
        (("激光设备", "光伏加工设备"), "专用设备制造业"),
        (("玻璃玻纤", "磨具磨料"), "非金属矿物制品业"),
        (("无机盐",), "化学原料和化学制品制造业"),
        (("房地产开发", "房地产服务"), "房地产业"),
        (("虚拟机器人",), "机器人概念"),
    ]
    for needles, alias in aliases:
        if any(needle.upper() in board_key for needle in needles):
            return alias
    return None


def _seed_rankings_from_spot(
    spot: pd.DataFrame,
    boards: list[BoardInfo],
    periods: list[int],
) -> dict[int, list[RankingRow]]:
    change_by_name = {
        str(row["板块"]): float(row["涨跌幅"])
        for _, row in spot.iterrows()
        if pd.notna(row.get("板块")) and pd.notna(row.get("涨跌幅"))
    }
    rows = [
        RankingRow(board.name, change_by_name.get(board.name, 0.0), "", 0.0)
        for board in boards
    ]
    return {period: rows for period in periods}


def _aggregate_sector_histories_from_stocks(
    sector_stock_histories: dict[str, dict[str, dict[str, pd.DataFrame]]]
) -> dict[str, dict[str, pd.DataFrame]]:
    output: dict[str, dict[str, pd.DataFrame]] = {"industry": {}, "concept": {}}
    for category, boards in sector_stock_histories.items():
        for board_name, stocks in boards.items():
            normalized: list[pd.Series] = []
            for history in stocks.values():
                if history.empty or "date" not in history.columns or "close" not in history.columns:
                    continue
                frame = history.loc[:, ["date", "close"]].copy()
                frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
                frame = frame.dropna().sort_values("date")
                if frame.empty or float(frame["close"].iloc[0]) == 0:
                    continue
                series = frame.set_index("date")["close"] / float(frame["close"].iloc[0]) * 100
                normalized.append(series)
            if not normalized:
                continue
            combined = pd.concat(normalized, axis=1).mean(axis=1).dropna().reset_index()
            combined.columns = ["date", "close"]
            output.setdefault(category, {})[board_name] = combined
    return output


def _stock_identity(stock: StockInfo) -> str:
    code = _normalize_stock_code(stock.code)
    return code or stock.name


def _request_budget_reached(status: SourceStatus, request_budget: int) -> bool:
    if request_budget <= 0 or status.requests < request_budget:
        return False
    message = f"request budget reached ({request_budget}); resume next run from cache"
    if message not in status.messages:
        status.messages.append(message)
    return True


def _selected_ranked_boards(
    rankings_by_category: dict[str, dict[int, list[RankingRow]]],
    boards_by_category: dict[str, dict[str, BoardInfo]],
    periods: list[int],
) -> list[tuple[str, BoardInfo]]:
    selected: list[tuple[str, BoardInfo]] = []
    seen: set[tuple[str, str]] = set()
    for category in ("industry", "concept"):
        boards = boards_by_category.get(category, {})
        rankings = rankings_by_category.get(category, {})
        for period in periods:
            for row in rankings.get(period, []):
                key = (category, row.name)
                if key in seen or row.name not in boards:
                    continue
                seen.add(key)
                selected.append((category, boards[row.name]))
    return selected


def _get_or_fetch_constituents(
    *,
    cache: CacheStore,
    category: str,
    board: BoardInfo,
    latest_date: str,
    status: SourceStatus,
    policy: AccessPolicy,
    fetcher: Any,
    cache_only: bool = False,
) -> list[StockInfo]:
    cache_category = f"constituents/{category}"
    cached = cache.read_history(cache_category, board.name)
    if cached is not None:
        frame, cached_date = cached
        if cached_date == latest_date:
            status.cache_hits += 1
            return _stock_infos_from_frame(frame)
    if cache_only:
        raise ValueError("missing cached constituents")

    frame = fetch_with_policy(
        lambda: pd.DataFrame([stock.__dict__ for stock in fetcher()]),
        policy=policy,
        status=status,
    )
    cache.write_history(cache_category, board.name, frame, data_date=latest_date)
    return _stock_infos_from_frame(frame)


def _fetch_eastmoney_board_constituents(
    board: BoardInfo,
    *,
    category: str,
    akshare_client: Any,
    timeout_seconds: float = 30.0,
    source: str = "eastmoney",
) -> list[StockInfo]:
    if source == "sina":
        return _fetch_sina_board_constituents(board, timeout_seconds=timeout_seconds)

    if not board.code:
        raise ValueError(f"{board.name} missing board code for constituents")

    rows = _fetch_eastmoney_clist_rows(
        "https://push2delay.eastmoney.com/api/qt/clist/get",
        {
            "pn": "1",
            "pz": "5000",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3" if category == "industry" else "f12",
            "fs": f"b:{board.code} f:!50",
            "fields": "f12,f14",
        },
        timeout_seconds=timeout_seconds or 20,
    )
    return [
        StockInfo(name=str(row.get("f14", "")), code=_normalize_stock_code(str(row.get("f12", ""))))
        for row in rows
        if row.get("f14") and row.get("f12")
    ]


def _fetch_eastmoney_market_snapshot(*, timeout_seconds: float) -> pd.DataFrame:
    page_size = 100
    first_page, total = _fetch_eastmoney_market_snapshot_page(1, page_size, timeout_seconds=timeout_seconds)
    frames = [first_page]
    page_count = max(1, (int(total) + page_size - 1) // page_size)
    for page in range(2, page_count + 1):
        page_frame, _ = _fetch_eastmoney_market_snapshot_page(page, page_size, timeout_seconds=timeout_seconds)
        frames.append(page_frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _fetch_eastmoney_snapshot_dates(limit: int, *, timeout_seconds: float) -> list[str]:
    payload = _fetch_eastmoney_datacenter_payload(
        {
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "pageSize": str(max(limit + 5, 80)),
            "pageNumber": "1",
            "reportName": "RPT_VALUEANALYSIS_DET",
            "columns": "TRADE_DATE",
            "source": "WEB",
            "client": "WEB",
            "filter": '(SECURITY_CODE="000001")',
        },
        timeout_seconds=timeout_seconds or 20,
    )
    rows = ((payload.get("result") or {}).get("data") or [])
    dates: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        trade_date = str(row.get("TRADE_DATE", ""))[:10]
        if trade_date and trade_date not in dates:
            dates.append(trade_date)
    return list(reversed(dates[:limit]))


def _fetch_eastmoney_market_snapshot_for_date(
    trade_date: str,
    *,
    page: int,
    page_size: int,
    timeout_seconds: float,
) -> tuple[pd.DataFrame, int]:
    payload = _fetch_eastmoney_datacenter_payload(
        {
            "sortColumns": "SECURITY_CODE",
            "sortTypes": "1",
            "pageSize": str(page_size),
            "pageNumber": str(page),
            "reportName": "RPT_VALUEANALYSIS_DET",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,CLOSE_PRICE,CHANGE_RATE",
            "source": "WEB",
            "client": "WEB",
            "filter": f"(TRADE_DATE='{trade_date}')",
        },
        timeout_seconds=timeout_seconds or 20,
    )
    result = payload.get("result") or {}
    rows = result.get("data") or []
    if not isinstance(rows, list):
        raise ValueError("eastmoney historical market snapshot returned unexpected rows")
    total = int(result.get("count") or len(rows))
    return pd.DataFrame(
        [
            {
                "code": _normalize_stock_code(str(row.get("SECURITY_CODE", ""))),
                "name": str(row.get("SECURITY_NAME_ABBR", "")),
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "close": _to_float_or_none(row.get("CLOSE_PRICE")),
                "return_pct": _to_float_or_none(row.get("CHANGE_RATE")),
            }
            for row in rows
            if isinstance(row, dict) and row.get("SECURITY_CODE") and row.get("TRADE_DATE")
        ]
    ).dropna(subset=["close"]), total


def _fetch_eastmoney_market_snapshot_page(
    page: int,
    page_size: int,
    *,
    timeout_seconds: float,
) -> tuple[pd.DataFrame, int]:
    payload = _fetch_eastmoney_clist_payload(
        "https://push2delay.eastmoney.com/api/qt/clist/get",
        {
            "pn": str(page),
            "pz": str(page_size),
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f2,f3,f12,f14",
        },
        timeout_seconds=timeout_seconds or 20,
    )
    data = payload.get("data") or {}
    rows = data.get("diff") or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        raise ValueError("eastmoney market snapshot returned unexpected rows")
    total = int(data.get("total") or len(rows))
    return pd.DataFrame(
        [
            {
                "code": _normalize_stock_code(str(row.get("f12", ""))),
                "name": str(row.get("f14", "")),
                "close": _to_float_or_none(row.get("f2")),
                "return_pct": _to_float_or_none(row.get("f3")),
            }
            for row in rows
            if isinstance(row, dict) and row.get("f12") and row.get("f14")
        ]
    ).dropna(subset=["close", "return_pct"]), total


def _fetch_eastmoney_stock_history(
    stock: StockInfo,
    *,
    start_date: str,
    end_date: str,
    akshare_client: Any,
    timeout_seconds: float = 30.0,
    source: str = "eastmoney",
) -> pd.DataFrame:
    if source == "sina":
        return _fetch_sina_stock_history(
            stock,
            start_date=start_date,
            end_date=end_date,
            timeout_seconds=timeout_seconds,
        )
    if source == "eastmoney_snapshot":
        raise ValueError("eastmoney_snapshot must be loaded through market snapshot filtering")

    import requests

    response = requests.get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": _stock_secid(stock.code),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "0",
            "beg": start_date,
            "end": end_date,
            "smplmt": "10000",
            "lmt": "1000000",
        },
        headers=EASTMONEY_HEADERS,
        timeout=timeout_seconds or 20,
    )
    response.raise_for_status()
    payload = response.json()
    klines = ((payload.get("data") or {}).get("klines") or [])
    rows = []
    for item in klines:
        fields = str(item).split(",")
        if len(fields) >= 3:
            rows.append({"日期": fields[0], "收盘": fields[2]})
    if not rows:
        raise ValueError(f"{stock.name}({stock.code}) missing kline data")
    return _normalize_history(pd.DataFrame(rows))


def _akshare_constituents_worker(category: str, board_name: str, queue: Any) -> None:
    try:
        akshare_client = load_akshare()
        if category == "industry":
            frame = akshare_client.stock_board_industry_cons_em(symbol=board_name)
        elif category == "concept":
            frame = akshare_client.stock_board_concept_cons_em(symbol=board_name)
        else:
            raise ValueError(f"unknown board category: {category}")
        queue.put(("ok", frame.to_dict(orient="records")))
    except BaseException as exc:
        queue.put(("error", repr(exc)))


def _akshare_stock_history_worker(code: str, start_date: str, end_date: str, queue: Any) -> None:
    try:
        akshare_client = load_akshare()
        frame = akshare_client.stock_zh_a_hist(
            symbol=_normalize_stock_code(code),
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="",
        )
        queue.put(("ok", frame.to_dict(orient="records")))
    except BaseException as exc:
        queue.put(("error", repr(exc)))


def _fetch_sina_sector_spot(category: str, *, timeout_seconds: float) -> pd.DataFrame:
    import requests

    if category == "industry":
        params = {"param": "industry"}
    elif category == "concept":
        params = {"param": "class"}
    else:
        raise ValueError(f"unknown sina category: {category}")
    response = requests.get(
        "http://money.finance.sina.com.cn/q/view/newFLJK.php",
        params=params,
        timeout=timeout_seconds or 20,
    )
    response.raise_for_status()
    text = response.text
    payload = json.loads(text[text.find("{") :])
    rows = []
    for value in payload.values():
        fields = str(value).split(",")
        if len(fields) < 13:
            continue
        rows.append(
            {
                "label": fields[0],
                "板块": fields[1],
                "公司家数": fields[2],
                "平均价格": fields[3],
                "涨跌额": fields[4],
                "涨跌幅": fields[5],
                "总成交量": fields[6],
                "总成交额": fields[7],
                "股票代码": fields[8],
                "个股-涨跌幅": fields[9],
                "个股-当前价": fields[10],
                "个股-涨跌额": fields[11],
                "股票名称": fields[12],
            }
        )
    frame = pd.DataFrame(rows)
    for column in ["公司家数", "平均价格", "涨跌额", "涨跌幅", "总成交量", "总成交额", "个股-涨跌幅", "个股-当前价", "个股-涨跌额"]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _fetch_sina_board_constituents(board: BoardInfo, *, timeout_seconds: float) -> list[StockInfo]:
    import math
    import requests
    from akshare.utils import demjson

    count_response = requests.get(
        "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount",
        params={"node": board.code},
        timeout=timeout_seconds or 20,
    )
    count_response.raise_for_status()
    total = int(count_response.json())
    pages = max(1, math.ceil(total / 80))
    stocks: list[StockInfo] = []
    for page in range(1, pages + 1):
        data_response = requests.get(
            "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
            params={
                "page": str(page),
                "num": "80",
                "sort": "changepercent",
                "asc": "0",
                "node": board.code,
                "symbol": "",
                "_s_r_a": "page",
            },
            timeout=timeout_seconds or 20,
        )
        data_response.raise_for_status()
        for row in demjson.decode(data_response.text):
            symbol = str(row.get("symbol", ""))
            name = str(row.get("name", ""))
            if symbol and name:
                stocks.append(StockInfo(name=name, code=symbol))
    return stocks


def _fetch_sina_stock_history(
    stock: StockInfo,
    *,
    start_date: str,
    end_date: str,
    timeout_seconds: float,
) -> pd.DataFrame:
    import requests
    from akshare.stock.stock_zh_a_sina import hk_js_decode, zh_sina_a_stock_hist_url
    from py_mini_racer import MiniRacer

    symbol = _sina_symbol(stock.code)
    response = requests.get(zh_sina_a_stock_hist_url.format(symbol), timeout=timeout_seconds or 20)
    response.raise_for_status()
    js_code = MiniRacer()
    js_code.eval(hk_js_decode)
    encoded = response.text.split("=")[1].split(";")[0].replace('"', "")
    rows = js_code.call("d", encoded)
    frame = pd.DataFrame(rows)
    if frame.empty or "date" not in frame.columns or "close" not in frame.columns:
        raise ValueError(f"{stock.name}({stock.code}) missing sina history data")
    frame = frame.loc[:, ["date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    start = pd.to_datetime(start_date).strftime("%Y-%m-%d")
    end = pd.to_datetime(end_date).strftime("%Y-%m-%d")
    frame = frame.dropna()
    frame = frame[(frame["date"] >= start) & (frame["date"] <= end)]
    if frame.empty:
        raise ValueError(f"{stock.name}({stock.code}) missing sina close data")
    return frame


def _sina_symbol(code: str) -> str:
    normalized = str(code).strip().lower()
    if normalized.startswith(("sh", "sz", "bj")):
        return normalized
    digits = _normalize_stock_code(normalized)
    if digits.startswith(("920", "4", "8")):
        return f"bj{digits}"
    if digits.startswith(("5", "6", "9")):
        return f"sh{digits}"
    return f"sz{digits}"


def _fetch_eastmoney_clist_rows(url: str, params: dict[str, str], *, timeout_seconds: float) -> list[dict[str, Any]]:
    payload = _fetch_eastmoney_clist_payload(url, params, timeout_seconds=timeout_seconds)
    rows = ((payload.get("data") or {}).get("diff") or [])
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        raise ValueError("eastmoney clist returned unexpected rows")
    return [row for row in rows if isinstance(row, dict)]


def _fetch_eastmoney_clist_payload(url: str, params: dict[str, str], *, timeout_seconds: float) -> dict[str, Any]:
    import requests

    try:
        response = requests.get(url, params=params, headers=EASTMONEY_HEADERS, timeout=timeout_seconds)
    except requests.exceptions.RequestException:
        delay_url = _eastmoney_delay_clist_url(url)
        if delay_url == url:
            raise
        response = requests.get(delay_url, params=params, headers=EASTMONEY_HEADERS, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("eastmoney clist returned unexpected payload")
    return payload


def _fetch_eastmoney_datacenter_payload(params: dict[str, str], *, timeout_seconds: float) -> dict[str, Any]:
    import requests

    response = requests.get(
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        params=params,
        headers={
            **EASTMONEY_HEADERS,
            "Referer": "https://data.eastmoney.com/",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("success"):
        raise ValueError(f"eastmoney datacenter returned unexpected payload: {payload}")
    return payload


def _eastmoney_delay_clist_url(url: str) -> str:
    if "push2delay.eastmoney.com/api/qt/clist/get" in url:
        return url
    if "/api/qt/clist/get" not in url or "eastmoney.com" not in url:
        return url
    return "https://push2delay.eastmoney.com/api/qt/clist/get"


def _stock_infos_from_frame(frame: pd.DataFrame) -> list[StockInfo]:
    name_column = _first_existing_column(frame, ["名称", "股票名称", "name"])
    code_column = _first_existing_column(frame, ["代码", "股票代码", "code"])
    if not name_column or not code_column:
        raise ValueError("成分股列表缺少 名称 或 代码 字段")
    cleaned = frame.loc[:, [name_column, code_column]].dropna()
    return [
        StockInfo(name=str(row[name_column]), code=_normalize_stock_code(str(row[code_column])))
        for _, row in cleaned.iterrows()
    ]


def _first_existing_column(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def _normalize_stock_code(code: str) -> str:
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    return digits or str(code).strip()


def _to_float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stock_secid(code: str) -> str:
    normalized = _normalize_stock_code(code)
    if normalized.startswith(("5", "6", "9")):
        market = "1"
    else:
        market = "0"
    return f"{market}.{normalized}"


def _stock_cache_name(stock: StockInfo) -> str:
    return f"{stock.code}_{stock.name}"


def _normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
    if "日期" not in frame.columns or "收盘" not in frame.columns:
        raise ValueError("历史行情缺少 日期 或 收盘 字段")
    return pd.DataFrame({"date": frame["日期"].map(str), "close": frame["收盘"]})


def _fetch_eastmoney_board_history(
    board: BoardInfo,
    *,
    start_date: str,
    end_date: str,
    endpoint: str,
) -> pd.DataFrame:
    import requests

    response = requests.get(
        endpoint,
        params={
            "secid": f"90.{board.code}",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "0",
            "beg": start_date,
            "end": end_date,
            "smplmt": "10000",
            "lmt": "1000000",
        },
        headers=EASTMONEY_HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    klines = ((payload.get("data") or {}).get("klines") or [])
    if not klines:
        raise ValueError(f"{board.name}({board.code}) missing kline data")

    rows = []
    for item in klines:
        fields = str(item).split(",")
        if len(fields) < 3:
            continue
        rows.append({"date": fields[0], "close": fields[2]})
    if not rows:
        raise ValueError(f"{board.name}({board.code}) missing close data")
    return pd.DataFrame(rows)


def _latest_data_date(histories: dict[str, pd.DataFrame]) -> str:
    dates = [str(frame["date"].max()) for frame in histories.values() if not frame.empty and "date" in frame.columns]
    return max(dates) if dates else "无可用数据"


def _parse_periods(value: str) -> list[int]:
    periods = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not periods:
        raise ValueError("periods must not be empty")
    if any(period <= 0 for period in periods):
        raise ValueError("periods must be positive")
    return periods


if __name__ == "__main__":
    raise SystemExit(main())
