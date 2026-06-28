import unittest

import pandas as pd

from sector_momentum import build_trend_series, compute_return, rank_sectors


def history(prices: list[float], start: str = "2026-01-01") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.bdate_range(start=start, periods=len(prices)).strftime("%Y-%m-%d"),
            "close": prices,
        }
    )


class SectorMomentumTest(unittest.TestCase):
    def test_compute_return_uses_close_price_n_trading_days_ago(self):
        data = history([10, 11, 12, 15, 18, 20])

        result = compute_return(data, 5)

        self.assertAlmostEqual(result, 100.0)

    def test_compute_return_returns_none_when_history_is_short(self):
        data = history([10, 11, 12])

        result = compute_return(data, 5)

        self.assertIsNone(result)

    def test_rank_sectors_returns_top_n_by_period_and_skips_short_history(self):
        histories = {
            "半导体": history([10, 12, 14, 16, 18, 20]),
            "银行": history([10, 10.5, 11, 11.5, 12, 12.5]),
            "短历史": history([10, 11]),
        }

        rankings, quality = rank_sectors(histories, periods=[5], top_n=1)

        self.assertEqual(rankings[5][0].name, "半导体")
        self.assertAlmostEqual(rankings[5][0].return_pct, 100.0)
        self.assertEqual(quality["history_short"], 1)

    def test_build_trend_series_rebases_to_first_visible_close(self):
        histories = {
            "半导体": history([10, 12, 15, 20]),
            "银行": history([20, 19, 18, 22]),
        }

        series = build_trend_series(histories, selected_names=["半导体", "银行"], lookback=3)

        semiconductor = next(item for item in series if item.name == "半导体")
        bank = next(item for item in series if item.name == "银行")
        self.assertEqual([point.return_pct for point in semiconductor.points], [0.0, 25.0, 66.67])
        self.assertEqual([point.return_pct for point in bank.points], [0.0, -5.26, 15.79])


if __name__ == "__main__":
    unittest.main()
