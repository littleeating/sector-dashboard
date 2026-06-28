import tempfile
import unittest
from pathlib import Path

import pandas as pd

from sector_dashboard import BoardInfo, _limit_boards, _load_board_infos, generate_sample_dashboard, render_dashboard
from sector_data import SourceStatus
from sector_momentum import RankingRow, TrendPoint, TrendSeries


class SectorDashboardRenderTest(unittest.TestCase):
    def test_render_dashboard_contains_sections_periods_status_and_svg(self):
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
            "source_statuses": [SourceStatus(source="eastmoney", requests=1, cache_hits=2)],
            "quality": {"history_short": 3},
        }

        html = render_dashboard(context)

        self.assertIn("板块动量看板", html)
        self.assertIn("行业板块", html)
        self.assertIn("概念板块", html)
        for period in [5, 10, 20, 30, 45, 60]:
            self.assertIn(f"{period}日", html)
        self.assertIn("eastmoney", html)
        self.assertIn("<svg", html)
        self.assertIn("半导体", html)

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
            "source_statuses": [],
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
            self.assertIn("<svg", html)

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
