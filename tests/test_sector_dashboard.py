import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from sector_dashboard import (
    DEFAULT_TOP_N,
    BoardInfo,
    _build_context,
    _limit_boards,
    _load_board_infos,
    generate_live_dashboard,
    generate_sample_dashboard,
    render_dashboard,
)
from sector_data import SourceStatus
from sector_momentum import RankingRow, TrendPoint, TrendSeries


class SectorDashboardRenderTest(unittest.TestCase):
    def test_render_dashboard_contains_sources_period_buttons_status_and_svg(self):
        rankings = {
            5: [RankingRow("半导体", 12.34, "2026-06-26", 1234.5)],
            10: [RankingRow("机器人", 21.0, "2026-06-26", 2222.2)],
            20: [],
            30: [],
            45: [],
            60: [],
        }
        context = {
            "data_date": "2026-06-26",
            "generated_at": "2026-06-28 16:30:00",
            "periods": [5, 10, 20, 30, 45, 60],
            "industry_rankings": rankings,
            "concept_rankings": rankings,
            "industry_count": 2,
            "concept_count": 2,
            "trend_series": [
                TrendSeries(
                    name="半导体",
                    points=[
                        TrendPoint("2026-06-24", 0.0),
                        TrendPoint("2026-06-25", 5.0),
                        TrendPoint("2026-06-26", 12.34),
                    ],
                )
            ],
            "period_chart_series": {
                "industry": {
                    5: [
                        TrendSeries(
                            name="半导体",
                            points=[
                                TrendPoint("2026-06-24", 0.0),
                                TrendPoint("2026-06-25", 5.0),
                            ],
                        )
                    ]
                },
                "concept": {
                    10: [
                        TrendSeries(
                            name="机器人",
                            points=[
                                TrendPoint("2026-06-24", 0.0),
                                TrendPoint("2026-06-25", 6.0),
                            ],
                        )
                    ]
                },
            },
            "source_statuses": [SourceStatus(source="eastmoney", requests=1, cache_hits=2)],
            "source_labels": {
                "industry": "东方财富行业板块（AKShare）",
                "concept": "东方财富概念板块（AKShare）",
            },
            "quality": {"history_short": 3},
        }

        html = render_dashboard(context)

        self.assertIn("板块动量看板", html)
        self.assertIn("行业板块", html)
        self.assertIn("概念板块", html)
        self.assertIn("东方财富行业板块（AKShare）", html)
        self.assertIn("东方财富概念板块（AKShare）", html)
        for period in [5, 10, 20, 30, 45, 60]:
            self.assertIn(f"{period}日", html)
        self.assertIn("eastmoney", html)
        self.assertIn("<svg", html)
        self.assertIn("半导体", html)
        self.assertIn('data-chart-key="industry-5"', html)
        self.assertIn('data-chart-key="concept-10"', html)
        self.assertIn("showPeriodChart", html)
        self.assertIn("selectLegendSeries", html)
        self.assertIn('class="series-group" data-series-id="series-0"', html)
        self.assertIn('class="legend-item" data-series-id="series-0"', html)
        self.assertIn("chart-panel.has-selection", html)

    def test_render_dashboard_escapes_sector_names(self):
        context = {
            "data_date": "2026-06-26",
            "generated_at": "2026-06-28 16:30:00",
            "periods": [5],
            "industry_rankings": {
                5: [RankingRow("<script>alert(1)</script>", 1.0, "2026-06-26", 1.0)]
            },
            "concept_rankings": {5: []},
            "industry_count": 1,
            "concept_count": 0,
            "trend_series": [],
            "period_chart_series": {"industry": {5: []}, "concept": {5: []}},
            "source_statuses": [],
            "source_labels": {"industry": "来源", "concept": "来源"},
            "quality": {},
        }

        html = render_dashboard(context)

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_generate_sample_dashboard_writes_html_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "index.html"

            generate_sample_dashboard(output)

            html = output.read_text(encoding="utf-8")
            self.assertIn("板块动量看板", html)
            self.assertIn("行业板块", html)
            self.assertIn("概念板块", html)
            self.assertIn("东方财富行业板块（AKShare）", html)
            self.assertIn("房地产开发", html)
            self.assertIn("创新药", html)
            self.assertNotIn("行业板块25", html)
            self.assertNotIn("概念板块25", html)
            self.assertIn("<svg", html)

    def test_svg_chart_has_axis_titles_and_readable_text_classes(self):
        context = {
            "data_date": "2026-06-26",
            "generated_at": "2026-06-28 16:30:00",
            "periods": [5],
            "industry_rankings": {5: []},
            "concept_rankings": {5: []},
            "industry_count": 0,
            "concept_count": 0,
            "trend_series": [
                TrendSeries(
                    name="半导体",
                    points=[
                        TrendPoint("2026-06-24", 0.0),
                        TrendPoint("2026-06-25", 5.0),
                    ],
                )
            ],
            "period_chart_series": {"industry": {5: []}, "concept": {5: []}},
            "source_statuses": [],
            "source_labels": {"industry": "来源", "concept": "来源"},
            "quality": {},
        }

        html = render_dashboard(context)

        self.assertIn("涨幅", html)
        self.assertIn("时间", html)
        self.assertIn(".axis-title", html)
        self.assertIn(".legend", html)

    def test_svg_chart_marks_each_daily_point_and_axis_tick(self):
        context = {
            "data_date": "2026-06-26",
            "generated_at": "2026-06-28 16:30:00",
            "periods": [5],
            "industry_rankings": {5: []},
            "concept_rankings": {5: []},
            "industry_count": 0,
            "concept_count": 0,
            "trend_series": [
                TrendSeries(
                    name="半导体",
                    points=[
                        TrendPoint("2026-06-24", 0.0),
                        TrendPoint("2026-06-25", 5.0),
                        TrendPoint("2026-06-26", 12.34),
                    ],
                )
            ],
            "period_chart_series": {"industry": {5: []}, "concept": {5: []}},
            "source_statuses": [],
            "source_labels": {"industry": "来源", "concept": "来源"},
            "quality": {},
        }

        html = render_dashboard(context)

        self.assertEqual(html.count('class="daily-point"'), 3)
        self.assertEqual(html.count('class="day-tick"'), 3)
        self.assertIn("<title>2026-06-26: 12.34%</title>", html)

    def test_svg_chart_keeps_daily_ticks_but_thins_crowded_date_labels(self):
        points = [
            TrendPoint(date.strftime("%Y-%m-%d"), float(index))
            for index, date in enumerate(pd.bdate_range("2026-05-01", periods=24))
        ]
        context = {
            "data_date": "2026-06-03",
            "generated_at": "2026-06-28 16:30:00",
            "periods": [20],
            "industry_rankings": {20: []},
            "concept_rankings": {20: []},
            "industry_count": 0,
            "concept_count": 0,
            "trend_series": [TrendSeries(name="半导体", points=points)],
            "period_chart_series": {"industry": {20: []}, "concept": {20: []}},
            "source_statuses": [],
            "source_labels": {"industry": "来源", "concept": "来源"},
            "quality": {},
        }

        html = render_dashboard(context)

        self.assertEqual(html.count('class="day-tick"'), 24)
        self.assertEqual(html.count('class="daily-point"'), 24)
        self.assertLess(html.count('class="day-label"'), 24)
        self.assertIn(">05-01</text>", html)
        self.assertIn(">06-03</text>", html)

    def test_live_dashboard_fetches_histories_from_eastmoney_by_board_code(self):
        class FakeAkshare:
            def stock_board_industry_name_em(self) -> pd.DataFrame:
                return pd.DataFrame([{"板块名称": "半导体", "板块代码": "BK1036"}])

            def stock_board_concept_name_em(self) -> pd.DataFrame:
                return pd.DataFrame([{"板块名称": "机器人概念", "板块代码": "BK0820"}])

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_akshare = FakeAkshare()
            requested_codes: list[str] = []

            def fake_fetch_history(board: BoardInfo, **_: object) -> pd.DataFrame:
                requested_codes.append(board.code)
                return pd.DataFrame({"date": ["2026-06-24", "2026-06-25"], "close": [100, 110]})

            with patch("sector_dashboard.load_akshare", return_value=fake_akshare), patch(
                "sector_dashboard._fetch_eastmoney_board_history", side_effect=fake_fetch_history
            ):
                generate_live_dashboard(
                    Path(temp_dir) / "index.html",
                    periods=[1],
                    top_n=1,
                    cache_dir=Path(temp_dir) / "cache",
                    max_workers=1,
                    min_delay=0,
                    max_delay=0,
                    board_limit=1,
                )

        self.assertEqual(requested_codes, ["BK1036", "BK0820"])

    def test_default_top_n_is_twenty(self):
        self.assertEqual(DEFAULT_TOP_N, 20)

    def test_build_context_keeps_twenty_ranked_rows_and_period_chart_series(self):
        dates = pd.bdate_range(end=pd.Timestamp("2026-06-26"), periods=70).strftime("%Y-%m-%d")
        histories = {
            f"行业{i:02d}": pd.DataFrame(
                {
                    "date": dates,
                    "close": [100 + day + i for day in range(70)],
                }
            )
            for i in range(25)
        }

        context = _build_context(
            industry_histories=histories,
            concept_histories={},
            periods=[5],
            top_n=20,
            source_statuses=[],
            quality={},
        )

        self.assertEqual(len(context["industry_rankings"][5]), 20)
        self.assertEqual(len(context["period_chart_series"]["industry"][5]), 20)
        self.assertEqual(context["source_labels"]["industry"], "东方财富行业板块（AKShare）")

    def test_load_board_infos_preserves_name_and_code(self):
        frame = pd.DataFrame(
            [
                {"板块名称": "半导体", "板块代码": "BK1036"},
                {"板块名称": "银行", "板块代码": "BK0475"},
            ]
        )

        infos = _load_board_infos(lambda: frame)

        self.assertEqual(infos[0].name, "半导体")
        self.assertEqual(infos[0].code, "BK1036")

    def test_limit_boards_keeps_all_when_limit_is_zero(self):
        boards = [BoardInfo("A", "BK1"), BoardInfo("B", "BK2")]

        self.assertEqual(_limit_boards(boards, 0), boards)
        self.assertEqual(_limit_boards(boards, 1), [boards[0]])


if __name__ == "__main__":
    unittest.main()
