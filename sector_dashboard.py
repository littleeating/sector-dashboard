from __future__ import annotations

import argparse
import html
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from sector_data import AccessPolicy, CacheStore, SourceStatus, get_or_fetch_history, load_akshare
from sector_momentum import RankingRow, TrendPoint, TrendSeries, build_trend_series, rank_sectors


DEFAULT_PERIODS = [5, 10, 20, 30, 45, 60]
DEFAULT_TOP_N = 20
LIVE_CACHE_VERSION = "akshare-board-name-v2"
SOURCE_LABELS = {
    "industry": "东方财富行业板块（AKShare）",
    "concept": "东方财富概念板块（AKShare）",
}


@dataclass(frozen=True)
class BoardInfo:
    name: str
    code: str


def render_dashboard(context: dict[str, Any]) -> str:
    periods = [int(period) for period in context["periods"]]
    industry_rankings = context["industry_rankings"]
    concept_rankings = context["concept_rankings"]
    period_chart_series = context.get("period_chart_series", {"industry": {}, "concept": {}})
    source_labels = context.get("source_labels", SOURCE_LABELS)
    source_statuses = context.get("source_statuses", [])
    quality = context.get("quality", {})

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
            _render_chart_panels(context.get("trend_series", []), period_chart_series),
            "</section>",
            _render_rankings("行业板块", "industry", source_labels.get("industry", ""), industry_rankings, periods),
            _render_rankings("概念板块", "concept", source_labels.get("concept", ""), concept_rankings, periods),
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
        points = " ".join(
            f"{x_for_date(point.date):.2f},{y_at(point.return_pct):.2f}"
            for point in item.points
        )
        parts.append(f'<polyline class="trend" points="{points}" stroke="{color}" />')
        for point in item.points:
            x = x_for_date(point.date)
            y = y_at(point.return_pct)
            parts.append(
                f'<circle class="daily-point" cx="{x:.2f}" cy="{y:.2f}" r="2.8" fill="{color}"><title>{html.escape(point.date)}: {point.return_pct:.2f}%</title></circle>'
            )
        legend_x = pad_left + (index % 5) * 176
        row_y = legend_y + (index // 5) * 20
        parts.append(f'<line x1="{legend_x}" y1="{row_y}" x2="{legend_x + 20}" y2="{row_y}" stroke="{color}" stroke-width="2.5" />')
        parts.append(f'<text class="legend" x="{legend_x + 28}" y="{row_y + 4}">{html.escape(item.name)}</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def _render_chart_panels(
    overview_series: list[TrendSeries],
    period_chart_series: dict[str, dict[int, list[TrendSeries]]],
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
) -> str:
    cards = []
    for period in periods:
        rows = rankings.get(period, [])
        if rows:
            body = "\n".join(
                f"<tr><td>{rank}</td><td>{html.escape(row.name)}</td><td>{row.return_pct:.2f}%</td><td>{row.latest_close:.2f}</td></tr>"
                for rank, row in enumerate(rows, start=1)
            )
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
    context = _build_context(
        industry_histories=_sample_histories(_sample_industry_names(), base=1000),
        concept_histories=_sample_histories(_sample_concept_names(), base=900),
        periods=DEFAULT_PERIODS,
        top_n=DEFAULT_TOP_N,
        source_statuses=[SourceStatus(source="sample", requests=0, cache_hits=0)],
        quality={"mode": "sample"},
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
    board_limit: int = 0,
) -> Path:
    # max_workers is validated and reported, but requests stay sequential in v1 to respect source limits.
    policy = AccessPolicy(max_workers=max_workers, min_delay=min_delay, max_delay=max_delay)
    cache = CacheStore(cache_dir, version=LIVE_CACHE_VERSION)
    status = SourceStatus(source="eastmoney")
    ak = load_akshare()
    today = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")

    industry_boards = _limit_boards(_load_board_infos(lambda: ak.stock_board_industry_name_em()), board_limit)
    concept_boards = _limit_boards(_load_board_infos(lambda: ak.stock_board_concept_name_em()), board_limit)

    industry_histories = _load_histories(
        cache=cache,
        category="industry",
        boards=industry_boards,
        latest_date=today,
        status=status,
        policy=policy,
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
        fetcher_factory=lambda board: lambda: _fetch_eastmoney_board_history(
            board,
            start_date=start_date,
            end_date=end_date,
            endpoint="https://91.push2his.eastmoney.com/api/qt/stock/kline/get",
        ),
    )

    context = _build_context(
        industry_histories=industry_histories,
        concept_histories=concept_histories,
        periods=periods,
        top_n=top_n,
        source_statuses=[status],
        quality={"max_workers": policy.max_workers},
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_dashboard(context), encoding="utf-8")
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成行业和概念板块动量静态网页。")
    parser.add_argument("--output", default="output/sector_dashboard/index.html", help="输出 HTML 路径。")
    parser.add_argument("--sample", action="store_true", help="使用内置样例数据离线生成网页。")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="每个周期展示前 N 名。")
    parser.add_argument("--periods", default="5,10,20,30,45,60", help="逗号分隔的交易日周期。")
    parser.add_argument("--cache-dir", default="cache/sector_dashboard", help="缓存目录。")
    parser.add_argument("--max-workers", type=int, default=1, help="外部请求并行度，硬上限为 2；v1 仍顺序请求。")
    parser.add_argument("--min-delay", type=float, default=1.2, help="外部请求之间的最小随机延迟秒数。")
    parser.add_argument("--max-delay", type=float, default=2.5, help="外部请求之间的最大随机延迟秒数。")
    parser.add_argument("--board-limit", type=int, default=0, help="仅用于验证的每类板块数量限制；0 表示全量。")
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
            cache_dir=args.cache_dir,
            max_workers=args.max_workers,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
            board_limit=args.board_limit,
        )
    print(f"板块动量看板已生成: {output.resolve()}")
    return 0


def _build_context(
    *,
    industry_histories: dict[str, pd.DataFrame],
    concept_histories: dict[str, pd.DataFrame],
    periods: list[int],
    top_n: int,
    source_statuses: list[SourceStatus],
    quality: dict[str, Any],
) -> dict[str, Any]:
    industry_rankings, industry_quality = rank_sectors(industry_histories, periods, top_n)
    concept_rankings, concept_quality = rank_sectors(concept_histories, periods, top_n)
    selected_names = _selected_trend_names(industry_rankings, concept_rankings)
    all_histories = {**industry_histories, **concept_histories}
    trend_series = build_trend_series(all_histories, selected_names, lookback=max(periods) + 1)
    period_chart_series = {
        "industry": _build_period_chart_series(industry_histories, industry_rankings),
        "concept": _build_period_chart_series(concept_histories, concept_rankings),
    }
    data_date = _latest_data_date(all_histories)
    merged_quality = {
        **quality,
        "industry_history_short": industry_quality["history_short"],
        "concept_history_short": concept_quality["history_short"],
    }
    return {
        "data_date": data_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "periods": periods,
        "industry_rankings": industry_rankings,
        "concept_rankings": concept_rankings,
        "industry_count": len(industry_histories),
        "concept_count": len(concept_histories),
        "trend_series": trend_series,
        "period_chart_series": period_chart_series,
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


def _load_board_infos(fetcher: Any) -> list[BoardInfo]:
    frame = fetcher()
    required = {"板块名称", "板块代码"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("板块清单缺少字段: " + ", ".join(sorted(missing)))
    cleaned = frame.loc[:, ["板块名称", "板块代码"]].dropna()
    return [BoardInfo(name=str(row["板块名称"]), code=str(row["板块代码"])) for _, row in cleaned.iterrows()]


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
) -> dict[str, pd.DataFrame]:
    histories: dict[str, pd.DataFrame] = {}
    for board in boards:
        if status.limited:
            break
        try:
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
