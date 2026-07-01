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
    _fetch_eastmoney_stock_history,
    _fetch_eastmoney_market_snapshot_for_date,
    _fetch_eastmoney_clist_rows,
    _limit_boards,
    _load_stock_kline_data,
    _load_sector_stock_histories,
    _load_board_infos,
    _load_board_infos_cached,
    _map_boards_to_sina_labels,
    _select_sina_board_pool,
    _aggregate_sector_histories_from_stocks,
    _collect_stock_kline_targets,
    _kline_records,
    _merge_kline_snapshot_metrics,
    _write_kline_files,
    _sina_symbol,
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
        self.assertIn("板块内涨幅前10名股票", html)
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
        self.assertEqual(html.count('class="last-return-label"'), 1)
        self.assertIn(">+12.34%</text>", html)

    def test_stock_chart_panel_includes_linked_kline_shell_and_stock_code(self):
        context = {
            "data_date": "2026-06-26",
            "generated_at": "2026-06-28 16:30:00",
            "periods": [5],
            "industry_rankings": {5: []},
            "concept_rankings": {5: []},
            "industry_count": 0,
            "concept_count": 0,
            "trend_series": [],
            "period_chart_series": {"industry": {5: []}, "concept": {5: []}},
            "sector_stock_chart_series": {
                "industry": {
                    5: {
                        "SectorA": [
                            TrendSeries(
                                name="FastStock",
                                points=[TrendPoint("2026-06-25", 0.0), TrendPoint("2026-06-26", 12.0)],
                                code="600001",
                            )
                        ]
                    }
                }
            },
            "source_statuses": [],
            "source_labels": {"industry": "来源", "concept": "来源"},
            "quality": {},
        }

        html = render_dashboard(context)

        self.assertIn('class="stock-linked-layout"', html)
        self.assertIn('class="kline-pane"', html)
        self.assertIn('data-stock-code="600001"', html)
        self.assertIn("loadKlineForLegend", html)
        self.assertIn("fetchLocalKline", html)
        self.assertIn("data/kline/", html)
        self.assertIn("MA5", html)
        self.assertNotIn("push2his.eastmoney.com/api/qt/stock/kline/get", html)

    def test_collect_stock_kline_targets_deduplicates_stock_codes(self):
        context = {
            "sector_stock_chart_series": {
                "industry": {
                    5: {
                        "SectorA": [
                            TrendSeries("FastStock", [TrendPoint("2026-06-26", 1.0)], code="600001"),
                            TrendSeries("OtherName", [TrendPoint("2026-06-26", 2.0)], code="600001"),
                        ]
                    }
                },
                "concept": {
                    10: {
                        "SectorB": [
                            TrendSeries("SlowStock", [TrendPoint("2026-06-26", 3.0)], code="000002"),
                        ]
                    }
                },
            }
        }

        targets = _collect_stock_kline_targets(context)

        self.assertEqual(targets, {"600001": "FastStock", "000002": "SlowStock"})

    def test_write_kline_files_outputs_local_json_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            frame = pd.DataFrame(
                [
                    {
                        "date": "2026-06-25",
                        "open": 10.0,
                        "close": 11.0,
                        "high": 11.5,
                        "low": 9.8,
                        "volume": 100,
                        "amount": 2000,
                        "turnover": float("nan"),
                        "pe_dynamic": 18.5,
                        "float_market_cap": 3200000000,
                    }
                ]
            )

            written = _write_kline_files(
                output_dir=output_dir,
                kline_data={"600001": ("FastStock", frame)},
            )

            self.assertEqual(written, 1)
            payload = (output_dir / "data" / "kline" / "600001.json").read_text(encoding="utf-8")
            self.assertIn('"code": "600001"', payload)
            self.assertIn('"name": "FastStock"', payload)
            self.assertIn('"open": 10.0', payload)
            self.assertIn('"turnover": null', payload)
            self.assertIn('"pe_dynamic": 18.5', payload)
            self.assertIn('"float_market_cap": 3200000000.0', payload)

    def test_kline_records_calculates_close_change_pct_when_missing(self):
        frame = pd.DataFrame(
            [
                {"date": "2026-06-24", "open": 10.0, "close": 10.0, "high": 10.5, "low": 9.8},
                {"date": "2026-06-25", "open": 10.1, "close": 11.0, "high": 11.2, "low": 10.0},
                {"date": "2026-06-26", "open": 11.0, "close": 10.45, "high": 11.1, "low": 10.3},
            ]
        )

        records = _kline_records(frame)

        self.assertIsNone(records[0]["change_pct"])
        self.assertAlmostEqual(records[1]["change_pct"], 10.0)
        self.assertAlmostEqual(records[2]["change_pct"], -5.0)

    def test_render_dashboard_kline_metrics_include_close_change_pct(self):
        html = render_dashboard(
            {
                "data_date": "2026-06-26",
                "generated_at": "2026-06-28 16:30:00",
                "periods": [5],
                "industry_rankings": {5: []},
                "concept_rankings": {5: []},
                "industry_count": 0,
                "concept_count": 0,
                "trend_series": [],
                "period_chart_series": {"industry": {5: []}, "concept": {5: []}},
                "stock_rankings": {},
                "stock_trend_series": {},
                "stock_kline_files": {},
                "statuses": [],
                "quality": {},
            }
        )

        self.assertIn("metric('涨跌幅', percentText(selected.changePct)", html)
        self.assertIn("function percentText(value) {\n  return value === null || value === undefined", html)

    def test_merge_kline_snapshot_metrics_adds_same_day_valuation_fields(self):
        kline = pd.DataFrame(
            [
                {"date": "2026-06-25", "open": 10.0, "close": 11.0, "high": 11.5, "low": 9.8},
                {"date": "2026-06-26", "open": 11.0, "close": 12.0, "high": 12.5, "low": 10.8},
            ]
        )
        snapshot = pd.DataFrame(
            [
                {
                    "code": "600001",
                    "date": "2026-06-25",
                    "turnover": 1.2,
                    "pe_dynamic": 18.5,
                    "float_market_cap": 3200000000,
                },
                {
                    "code": "600001",
                    "date": "2026-06-26",
                    "turnover": 1.6,
                    "pe_dynamic": 19.0,
                    "float_market_cap": 3500000000,
                },
            ]
        )

        merged = _merge_kline_snapshot_metrics({"600001": ("FastStock", kline)}, snapshot)

        merged_frame = merged["600001"][1]
        self.assertEqual(merged_frame["turnover"].tolist(), [1.2, 1.6])
        self.assertEqual(merged_frame["pe_dynamic"].tolist(), [18.5, 19.0])
        self.assertEqual(merged_frame["float_market_cap"].tolist(), [3200000000, 3500000000])

    def test_load_stock_kline_data_uses_code_cache_key_and_reads_legacy_name_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = CacheStore(Path(temp_dir), version="test")
            legacy = pd.DataFrame(
                [
                    {
                        "date": "2026-06-26",
                        "open": 10.0,
                        "close": 12.0,
                        "high": 12.5,
                        "low": 9.8,
                    }
                ]
            )
            cache.write_history("stock_kline/sina", "600001_FastStock", legacy, data_date="2026-07-01")
            status = SourceStatus(source="test")
            policy = AccessPolicy(max_workers=1, min_delay=0, max_delay=0, retry_delays=())

            data = _load_stock_kline_data(
                cache=cache,
                targets={"600001": "FastStock"},
                latest_date="2026-07-01",
                start_date="20260601",
                end_date="20260630",
                status=status,
                policy=policy,
                timeout_seconds=20,
                cache_only=True,
                source="sina",
            )

            self.assertIn("600001", data)
            self.assertIsNotNone(cache.read_history("stock_kline/sina", "600001"))
            self.assertEqual(status.cache_hits, 1)

    def test_fetch_eastmoney_market_snapshot_for_date_maps_valuation_fields(self):
        payload = {
            "result": {
                "count": 1,
                "data": [
                    {
                        "SECURITY_CODE": "600001",
                        "SECURITY_NAME_ABBR": "FastStock",
                        "TRADE_DATE": "2026-06-26 00:00:00",
                        "CLOSE_PRICE": 12.0,
                        "CHANGE_RATE": 5.5,
                        "NOTLIMITED_MARKETCAP_A": 3200000000,
                        "FREE_SHARES_A": 266666666,
                        "PE_TTM": 18.5,
                    }
                ],
            },
            "success": True,
        }

        with patch("sector_dashboard._fetch_eastmoney_datacenter_payload", return_value=payload):
            frame, total = _fetch_eastmoney_market_snapshot_for_date(
                "2026-06-26",
                page=1,
                page_size=5000,
                timeout_seconds=20,
            )

        self.assertEqual(total, 1)
        row = frame.iloc[0].to_dict()
        self.assertEqual(row["float_market_cap"], 3200000000)
        self.assertEqual(row["free_shares"], 266666666)
        self.assertEqual(row["pe_dynamic"], 18.5)

    def test_stock_snapshot_histories_preserve_stock_code_for_kline_linking(self):
        from sector_dashboard import _snapshot_histories_for_constituents

        history = pd.DataFrame(
            [
                {"code": "600001", "name": "FastStock", "date": "2026-06-25", "close": 10},
                {"code": "600001", "name": "FastStock", "date": "2026-06-26", "close": 12},
            ]
        )

        histories = _snapshot_histories_for_constituents(
            constituents=[StockInfo("FastStock", "600001")],
            snapshot_by_code={"600001": history},
        )

        self.assertEqual(histories["FastStock"]["code"].tolist(), ["600001", "600001"])

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

    def test_build_context_limits_sector_stock_rows_with_stock_top_n(self):
        dates = pd.bdate_range(end=pd.Timestamp("2026-06-26"), periods=6).strftime("%Y-%m-%d")
        stock_histories = {
            "industry": {
                "SectorA": {
                    f"Stock{i:02d}": pd.DataFrame({"date": dates, "close": [10, 10, 10, 10, 10, 10 + i]})
                    for i in range(15)
                }
            },
            "concept": {},
        }

        context = _build_context(
            industry_histories={"SectorA": pd.DataFrame({"date": dates, "close": [100, 101, 102, 103, 104, 110]})},
            concept_histories={},
            periods=[2],
            top_n=20,
            stock_top_n=10,
            source_statuses=[],
            quality={},
            sector_stock_histories=stock_histories,
        )

        self.assertEqual(len(context["sector_stock_rankings"]["industry"][2]["SectorA"]), 10)
        self.assertEqual(len(context["sector_stock_chart_series"]["industry"][2]["SectorA"]), 10)

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

    def test_map_boards_to_sina_labels_keeps_only_name_matches(self):
        boards = [BoardInfo("创新药", "BK0001"), BoardInfo("Missing", "BK0002")]
        spot = pd.DataFrame([{"板块": "创新药", "label": "gn_cxy"}])

        mapped = _map_boards_to_sina_labels(boards, spot)

        self.assertEqual(mapped, {"创新药": BoardInfo("创新药", "gn_cxy")})

    def test_map_boards_to_sina_labels_uses_conservative_normalized_matches(self):
        boards = [
            BoardInfo("BC电池概念", "BK0001"),
            BoardInfo("半导体设备", "BK0002"),
            BoardInfo("虚拟机器人", "BK0003"),
            BoardInfo("电子", "BK0002"),
            BoardInfo("Missing", "BK0003"),
        ]
        spot = pd.DataFrame(
            [
                {"板块": "BC电池", "label": "gn_bc"},
                {"板块": "半导体", "label": "gn_semi"},
                {"板块": "机器人概念", "label": "gn_robot"},
                {"板块": "计算机、通信和其他电子设备制造业", "label": "hy_electronics"},
            ]
        )

        mapped = _map_boards_to_sina_labels(boards, spot)

        self.assertEqual(
            mapped,
            {
                "BC电池概念": BoardInfo("BC电池概念", "gn_bc"),
                "半导体设备": BoardInfo("半导体设备", "gn_semi"),
                "虚拟机器人": BoardInfo("虚拟机器人", "gn_robot"),
            },
        )

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

    def test_sina_symbol_maps_beijing_920_codes_to_bj_prefix(self):
        self.assertEqual(_sina_symbol("920058"), "bj920058")
        self.assertEqual(_sina_symbol("600000"), "sh600000")
        self.assertEqual(_sina_symbol("300750"), "sz300750")

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

    def test_load_sector_stock_histories_can_use_sina_for_stock_history_with_eastmoney_constituents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = CacheStore(Path(temp_dir), version="test")
            status = SourceStatus(source="hybrid")
            policy = AccessPolicy(max_workers=1, min_delay=0, max_delay=0, retry_delays=())
            requested_constituents: list[str] = []
            requested_sina_stocks: list[str] = []

            def fake_constituents(board: BoardInfo, **_: object) -> list[StockInfo]:
                requested_constituents.append(board.code)
                return [StockInfo("FastStock", "600000")]

            def fake_sina_history(stock: StockInfo, **_: object) -> pd.DataFrame:
                requested_sina_stocks.append(stock.code)
                return pd.DataFrame({"date": ["2026-06-25", "2026-06-26"], "close": [10, 12]})

            with patch("sector_dashboard._fetch_eastmoney_board_constituents", side_effect=fake_constituents), patch(
                "sector_dashboard._fetch_sina_stock_history", side_effect=fake_sina_history
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
                    source="eastmoney",
                    stock_history_source="sina",
                )

        self.assertEqual(requested_constituents, ["BK0001"])
        self.assertEqual(requested_sina_stocks, ["600000"])
        self.assertIn("FastStock", histories["industry"]["SectorA"])

    def test_load_sector_stock_histories_uses_eastmoney_snapshot_without_per_stock_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = CacheStore(Path(temp_dir), version="test")
            status = SourceStatus(source="eastmoney")
            policy = AccessPolicy(max_workers=1, min_delay=0, max_delay=0, retry_delays=())
            constituents = [StockInfo(f"Stock{i:02d}", f"6000{i:02d}") for i in range(12)]
            snapshot = pd.DataFrame(
                [
                    {
                        "code": stock.code,
                        "name": stock.name,
                        "close": 10 + index,
                        "return_pct": index,
                    }
                    for index, stock in enumerate(constituents)
                ]
            )

            snapshot["date"] = "2026-06-26"

            with patch("sector_dashboard._fetch_eastmoney_board_constituents", return_value=constituents), patch(
                "sector_dashboard._fetch_eastmoney_snapshot_dates", return_value=["2026-06-26"], create=True
            ), patch(
                "sector_dashboard._fetch_eastmoney_market_snapshot_for_date",
                return_value=(snapshot, len(snapshot)),
                create=True,
            ) as snapshot_fetcher, patch("sector_dashboard._fetch_eastmoney_stock_history") as stock_history_fetcher:
                histories = _load_sector_stock_histories(
                    cache=cache,
                    akshare_client=object(),
                    periods=[5],
                    rankings_by_category={
                        "industry": {5: [RankingRow("SectorA", 1.0, "2026-06-26", 100)]},
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
                    stock_candidate_limit=0,
                    stock_top_n=10,
                    source="eastmoney",
                    stock_history_source="eastmoney_snapshot",
                )

        self.assertEqual(snapshot_fetcher.call_count, 1)
        self.assertEqual(stock_history_fetcher.call_count, 0)
        self.assertEqual(list(histories["industry"]["SectorA"].keys()), [f"Stock{i:02d}" for i in range(12)])

    def test_load_sector_stock_histories_uses_sixty_day_snapshot_series(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = CacheStore(Path(temp_dir), version="test")
            status = SourceStatus(source="eastmoney")
            policy = AccessPolicy(max_workers=1, min_delay=0, max_delay=0, retry_delays=())
            constituents = [StockInfo("FastStock", "600001"), StockInfo("SlowStock", "600002")]
            snapshots = {
                "2026-06-25": pd.DataFrame(
                    [
                        {"code": "600001", "name": "FastStock", "date": "2026-06-25", "close": 10, "return_pct": 0, "turnover": 1.2, "pe_dynamic": 20, "float_market_cap": 1000},
                        {"code": "600002", "name": "SlowStock", "date": "2026-06-25", "close": 10, "return_pct": 0},
                    ]
                ),
                "2026-06-26": pd.DataFrame(
                    [
                        {"code": "600001", "name": "FastStock", "date": "2026-06-26", "close": 15, "return_pct": 50, "turnover": 1.5, "pe_dynamic": 22, "float_market_cap": 1200},
                        {"code": "600002", "name": "SlowStock", "date": "2026-06-26", "close": 11, "return_pct": 10},
                    ]
                ),
            }

            with patch("sector_dashboard._fetch_eastmoney_board_constituents", return_value=constituents), patch(
                "sector_dashboard._fetch_eastmoney_snapshot_dates", return_value=["2026-06-25", "2026-06-26"], create=True
            ), patch(
                "sector_dashboard._fetch_eastmoney_market_snapshot_for_date",
                side_effect=lambda trade_date, **_: (snapshots[trade_date], len(snapshots[trade_date])),
                create=True,
            ), patch("sector_dashboard._fetch_eastmoney_stock_history") as stock_history_fetcher:
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
                    stock_candidate_limit=0,
                    stock_top_n=10,
                    source="eastmoney",
                    stock_history_source="eastmoney_snapshot",
                )

        self.assertEqual(stock_history_fetcher.call_count, 0)
        self.assertEqual(histories["industry"]["SectorA"]["FastStock"]["date"].tolist(), ["2026-06-25", "2026-06-26"])
        self.assertEqual(histories["industry"]["SectorA"]["FastStock"]["close"].tolist(), [10, 15])
        self.assertEqual(histories["industry"]["SectorA"]["FastStock"]["turnover"].tolist(), [1.2, 1.5])
        self.assertEqual(histories["industry"]["SectorA"]["FastStock"]["pe_dynamic"].tolist(), [20, 22])
        self.assertEqual(histories["industry"]["SectorA"]["FastStock"]["float_market_cap"].tolist(), [1000, 1200])

    def test_fetch_eastmoney_clist_rows_falls_back_to_delay_endpoint_once(self):
        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {"data": {"diff": [{"f12": "600000", "f14": "测试股份"}]}}

        requested_urls: list[str] = []

        def fake_get(url: str, **_: object) -> FakeResponse:
            import requests

            requested_urls.append(url)
            if len(requested_urls) == 1:
                raise requests.exceptions.ConnectionError("Remote end closed connection without response")
            return FakeResponse()

        with patch("requests.get", side_effect=fake_get):
            rows = _fetch_eastmoney_clist_rows(
                "https://82.push2.eastmoney.com/api/qt/clist/get",
                {"pn": "1"},
                timeout_seconds=3,
            )

        self.assertEqual(rows, [{"f12": "600000", "f14": "测试股份"}])
        self.assertEqual(requested_urls[1], "https://push2delay.eastmoney.com/api/qt/clist/get")

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
