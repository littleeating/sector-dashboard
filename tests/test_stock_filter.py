import unittest

import pandas as pd

from stock_filter import apply_return_filters, build_summary_output, get_recent_return_series


class StockFilterTest(unittest.TestCase):
    def test_direct_recent_return_columns(self):
        df = pd.DataFrame(
            [
                {"名称": "A", "近20日涨幅": "35%", "近5日涨幅": "8%"},
                {"名称": "B", "近20日涨幅": "25%", "近5日涨幅": "4%"},
                {"名称": "C", "近20日涨幅": "40%", "近5日涨幅": "12%"},
            ]
        )

        result = apply_return_filters(df, rise_days=20, rise_threshold=30, flat_days=5, flat_threshold=10)

        self.assertEqual(result["名称"].tolist(), ["A"])

    def test_calculate_recent_return_from_prices(self):
        df = pd.DataFrame([{"最新价": "13", "20日前收盘价": "10"}])

        result = get_recent_return_series(df, 20)

        self.assertAlmostEqual(float(result.iloc[0]), 30.0)

    def test_summary_output_uses_aliases(self):
        df = pd.DataFrame(
            [
                {
                    "名称": "A",
                    "行业": "计算机",
                    "主营业务": "软件服务",
                    "近1季度营收": "10亿",
                    "近1季度净利润": "1亿",
                    "近1季度净利润增速": "20%",
                    "近2季度营收": "9亿",
                    "近2季度净利润": "0.9亿",
                    "近2季度净利润增速": "18%",
                    "近3季度营收": "8亿",
                    "近3季度净利润": "0.8亿",
                    "近3季度净利润增速": "15%",
                    "近4季度营收": "7亿",
                    "近4季度净利润": "0.7亿",
                    "近4季度净利润增速": "12%",
                    "近X日涨幅": 35,
                    "近A日涨幅": 8,
                    "命中规则": "测试",
                    "筛选时间": "2026-06-15 10:00:00",
                }
            ]
        )

        result = build_summary_output(df)

        self.assertEqual(result.loc[0, "股票名称"], "A")
        self.assertEqual(result.loc[0, "股票板块"], "计算机")
        self.assertIn("近4季度净利润增速", result.columns)


if __name__ == "__main__":
    unittest.main()
