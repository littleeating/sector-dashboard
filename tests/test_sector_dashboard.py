import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from sector_dashboard import (
    DEFAULT_TOP_N,
    BoardInfo,
    StockInfo,
    _build_context,
    _limit_boards,
    _load_sector_stock_histories,
    _load_board_infos,
    _load_board_infos_cached,
    _select_sina_board_pool,
    _aggregate_sector_histories_from_stocks,
    generate_live_dashboard,
    generate_sample_dashboard,
    render_dashboard,
)
from sector_data import AccessPolicy, CacheStore, SourceStatus
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
            "sector_stock_rankings": {
                "industry": {
                    5: {
                        "半导体": [
                            RankingRow("测试股份", 18.5, "2026-06-26", 12.3),
                        ]
                    }
                },
                "concept": {},
            },
            "sector_stock_chart_series": {
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
        self.assertIn('class="sector-row"', html)
        self.assertIn('data-stock-panel-key="industry-5-半导体"', html)
        self.assertIn('class="stock-detail"', html)
        self.assertIn("板块内涨幅前20名股票", html)
        self.assertIn("测试股份", html)
        self.assertIn("showSectorStocks", html)
        self.assertIn("showStockChart", html)
        self.assertIn('data-chart-key="stock-industry-5-半导体"', html)

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

            def fake_fetch_board_list(category: str, **_: object) -> pd.DataFrame:
                if category == "industry":
                    return fake_akshare.stock_board_industry_name_em()
                return fake_akshare.stock_board_concept_name_em()

            with patch("sector_dashboard.load_akshare", return_value=fake_akshare), patch(
                "sector_dashboard._fetch_eastmoney_board_history", side_effect=fake_fetch_history
            ), patch("sector_dashboard._fetch_akshare_board_list", side_effect=fake_fetch_board_list), patch(
                "sector_dashboard._load_sector_stock_histories", return_value={"industry": {}, "concept": {}}
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

    def test_build_context_adds_sector_stock_rankings_and_charts(self):
        dates = pd.bdate_range(end=pd.Timestamp("2026-06-26"), periods=6).strftime("%Y-%m-%d")
        sector_histories = {
            "SectorA": pd.DataFrame({"date": dates, "close": [100, 101, 102, 103, 104, 110]})
        }
        stock_histories = {
            "industry": {
                "SectorA": {
                    "FastStock": pd.DataFrame({"date": dates, "close": [10, 10, 11, 12, 13, 16]}),
                    "SlowStock": pd.DataFrame({"date": dates, "close": [10, 10, 10, 10, 10, 11]}),
                }
            },
            "concept": {},
        }

        context = _build_context(
            industry_histories=sector_histories,
            concept_histories={},
            periods=[2],
            top_n=2,
            source_statuses=[],
            quality={},
            sector_stock_histories=stock_histories,
        )

        stock_rows = context["sector_stock_rankings"]["industry"][2]["SectorA"]
        self.assertEqual([row.name for row in stock_rows], ["FastStock", "SlowStock"])
        self.assertEqual(len(context["sector_stock_chart_series"]["industry"][2]["SectorA"]), 2)
        self.assertTrue(context["quality"]["stock_rankings_enabled"])
        self.assertEqual(context["quality"]["stock_sector_count"], 1)

    def test_select_sina_board_pool_keeps_highest_current_change_boards(self):
        spot = pd.DataFrame(
            [
                {"板块": "Slow", "label": "slow", "涨跌幅": 1.0},
                {"板块": "Fast", "label": "fast", "涨跌幅": 5.0},
                {"板块": "Mid", "label": "mid", "涨跌幅": 3.0},
            ]
        )

        boards = _select_sina_board_pool(spot, limit=2)

        self.assertEqual(boards, [BoardInfo("Fast", "fast"), BoardInfo("Mid", "mid")])

    def test_aggregate_sector_histories_from_stocks_builds_equal_weight_index(self):
        histories = {
            "industry": {
                "SectorA": {
                    "Fast": pd.DataFrame({"date": ["2026-06-25", "2026-06-26"], "close": [10, 20]}),
                    "Flat": pd.DataFrame({"date": ["2026-06-25", "2026-06-26"], "close": [10, 10]}),
                }
            },
            "concept": {},
        }

        sector_histories = _aggregate_sector_histories_from_stocks(histories)

        self.assertEqual(sector_histories["industry"]["SectorA"]["date"].tolist(), ["2026-06-25", "2026-06-26"])
        self.assertEqual(sector_histories["industry"]["SectorA"]["close"].round(2).tolist(), [100.0, 150.0])

    def test_load_sector_stock_histories_fetches_ranked_boards_and_stock_histories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = CacheStore(Path(temp_dir), version="test")
            status = SourceStatus(source="eastmoney")
            policy = AccessPolicy(max_workers=1, min_delay=0, max_delay=0, retry_delays=())
            requested_boards: list[str] = []
            requested_stocks: list[str] = []

            def fake_constituents(board: BoardInfo, **_: object) -> list[StockInfo]:
                requested_boards.append(board.name)
                return [StockInfo("FastStock", "600000")]

            def fake_stock_history(stock: StockInfo, **_: object) -> pd.DataFrame:
                requested_stocks.append(stock.code)
                return pd.DataFrame({"date": ["2026-06-25", "2026-06-26"], "close": [10, 12]})

            with patch("sector_dashboard._fetch_eastmoney_board_constituents", side_effect=fake_constituents), patch(
                "sector_dashboard._fetch_eastmoney_stock_history", side_effect=fake_stock_history
            ):
                histories = _load_sector_stock_histories(
                    cache=cache,
                    akshare_client=object(),
                    periods=[1],
                    rankings_by_category={
                        "industry": {1: [RankingRow("SectorA", 1.0, "2026-06-26", 100)]},
                        "concept": {},
                    },
                    boards_by_category={"industry": {"SectorA": BoardInfo("SectorA", "BK0001")}, "concept": {}},
                    latest_date="2026-06-26",
                    start_date="20260601",
                    end_date="20260626",
                    status=status,
                    policy=policy,
                    stock_sector_limit=0,
                    stock_constituent_limit=0,
                )

        self.assertEqual(requested_boards, ["SectorA"])
        self.assertEqual(requested_stocks, ["600000"])
        self.assertIn("FastStock", histories["industry"]["SectorA"])

    def test_load_sector_stock_histories_prefers_repeated_candidate_stocks_and_uses_global_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = CacheStore(Path(temp_dir), version="test")
            status = SourceStatus(source="eastmoney")
            policy = AccessPolicy(max_workers=1, min_delay=0, max_delay=0, retry_delays=())
            requested_stocks: list[str] = []

            def fake_constituents(board: BoardInfo, **_: object) -> list[StockInfo]:
                if board.name == "SectorA":
                    return [
                        StockInfo("SharedStock", "600001"),
                        StockInfo("OnlyA", "600002"),
                    ]
                return [
                    StockInfo("SharedStock", "600001"),
                    StockInfo("OnlyB", "600003"),
                ]

            def fake_stock_history(stock: StockInfo, **_: object) -> pd.DataFrame:
                requested_stocks.append(stock.code)
                return pd.DataFrame({"date": ["2026-06-25", "2026-06-26"], "close": [10, 12]})

            with patch("sector_dashboard._fetch_eastmoney_board_constituents", side_effect=fake_constituents), patch(
                "sector_dashboard._fetch_eastmoney_stock_history", side_effect=fake_stock_history
            ):
                histories = _load_sector_stock_histories(
                    cache=cache,
                    akshare_client=object(),
                    periods=[5],
                    rankings_by_category={
                        "industry": {
                            5: [
                                RankingRow("SectorA", 10, "2026-06-26", 110),
                                RankingRow("SectorB", 9, "2026-06-26", 109),
                            ]
                        },
                        "concept": {},
                    },
                    boards_by_category={
                        "industry": {
                            "SectorA": BoardInfo("SectorA", "BK0001"),
                            "SectorB": BoardInfo("SectorB", "BK0002"),
                        },
                        "concept": {},
                    },
                    latest_date="2026-06-26",
                    start_date="20260601",
                    end_date="20260626",
                    status=status,
                    policy=policy,
                    stock_sector_limit=0,
                    stock_constituent_limit=0,
                    stock_candidate_limit=1,
                    request_budget=0,
                )

        self.assertEqual(list(histories["industry"]["SectorA"].keys()), ["SharedStock"])
        self.assertEqual(list(histories["industry"]["SectorB"].keys()), ["SharedStock"])
        self.assertEqual(requested_stocks, ["600001"])

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

    def test_load_board_infos_cached_falls_back_to_cached_list_when_fetch_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = CacheStore(Path(temp_dir), version="test")
            status = SourceStatus(source="eastmoney")
            cached = pd.DataFrame([{"板块名称": "半导体", "板块代码": "BK1036"}])
            cache.write_history("board_list", "industry", cached, data_date="2026-06-26")

            infos = _load_board_infos_cached(
                cache=cache,
                category="industry",
                latest_date="2026-06-29",
                fetcher=lambda: (_ for _ in ()).throw(ConnectionError("Remote end closed connection without response")),
                policy=AccessPolicy(max_workers=1, min_delay=0, max_delay=0, retry_delays=()),
                status=status,
            )

        self.assertEqual(infos, [BoardInfo("半导体", "BK1036")])
        self.assertEqual(status.cache_hits, 1)
        self.assertEqual(status.failed_requests, 1)
        self.assertIn("cached board list", "; ".join(status.messages))

    def test_load_board_infos_cached_uses_history_names_when_board_list_cache_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = CacheStore(Path(temp_dir), version="test")
            status = SourceStatus(source="eastmoney")
            cache.write_history(
                "concept",
                "CPO概念",
                pd.DataFrame({"date": ["2026-06-29"], "close": [100]}),
                data_date="2026-06-29",
            )

            infos = _load_board_infos_cached(
                cache=cache,
                category="concept",
                latest_date="2026-06-29",
                fetcher=lambda: (_ for _ in ()).throw(TimeoutError("concept board list timed out")),
                policy=AccessPolicy(max_workers=1, min_delay=0, max_delay=0, retry_delays=()),
                status=status,
            )

        self.assertEqual(infos, [BoardInfo("CPO概念", "")])
        self.assertIn("cached concept history names", "; ".join(status.messages))

    def test_limit_boards_keeps_all_when_limit_is_zero(self):
        boards = [BoardInfo("A", "BK1"), BoardInfo("B", "BK2")]

        self.assertEqual(_limit_boards(boards, 0), boards)
        self.assertEqual(_limit_boards(boards, 1), [boards[0]])


if __name__ == "__main__":
    unittest.main()
