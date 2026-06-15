import unittest

import pandas as pd

from filter_engine import COL_MATCHED, COL_RULES, MissingFieldError, YES, evaluate_dataframe


CODE = "\u4ee3\u7801"
NAME = "\u540d\u79f0"
PCT_CHANGE = "\u6da8\u8dcc\u5e45"
TURNOVER = "\u6362\u624b\u7387"
VOLUME_RATIO = "\u91cf\u6bd4"
PE = "\u5e02\u76c8\u7387"
MARKET_CAP = "\u603b\u5e02\u503c"
CONCEPT = "\u6982\u5ff5"
NOTE = "\u5907\u6ce8"


class FilterEngineTest(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame(
            [
                {
                    CODE: "000001",
                    NAME: "A",
                    PCT_CHANGE: "3.5%",
                    TURNOVER: "4.2%",
                    VOLUME_RATIO: "1.3",
                    PE: "30",
                    MARKET_CAP: "120",
                    CONCEPT: "\u4eba\u5de5\u667a\u80fd; \u91d1\u878d\u79d1\u6280",
                    NOTE: "",
                },
                {
                    CODE: "000002",
                    NAME: "B",
                    PCT_CHANGE: "8.1%",
                    TURNOVER: "1.2%",
                    VOLUME_RATIO: "0.8",
                    PE: "100",
                    MARKET_CAP: "40",
                    CONCEPT: "\u5730\u4ea7",
                    NOTE: "\u89c2\u5bdf",
                },
            ]
        )

    def test_nested_all_any_rules(self):
        config = {
            "rules": {
                "name": "\u7ec4\u5408\u89c4\u5219",
                "all": [
                    {"field": PCT_CHANGE, "operator": "between", "value": [0, 7], "name": "\u6da8\u5e45\u5408\u9002"},
                    {"field": TURNOVER, "operator": ">=", "value": 2, "name": "\u6362\u624b\u5145\u5206"},
                    {
                        "name": "\u57fa\u672c\u9762\u6216\u9898\u6750",
                        "any": [
                            {"field": PE, "operator": "between", "value": [0, 80], "name": "\u4f30\u503c\u53ef\u63a5\u53d7"},
                            {"field": CONCEPT, "operator": "contains", "value": "\u4eba\u5de5\u667a\u80fd", "name": "AI"},
                        ],
                    },
                ],
            }
        }

        result = evaluate_dataframe(self.df, config)

        self.assertEqual(result.loc[0, COL_MATCHED], YES)
        self.assertNotEqual(result.loc[1, COL_MATCHED], YES)
        self.assertIn("\u7ec4\u5408\u89c4\u5219", result.loc[0, COL_RULES])
        self.assertIn("AI", result.loc[0, COL_RULES])

    def test_text_and_empty_operators(self):
        config = {
            "rules": {
                "any": [
                    {"field": CONCEPT, "operator": "not_contains", "value": "\u5730\u4ea7", "name": "not real estate"},
                    {"field": NOTE, "operator": "is_empty", "name": "empty note"},
                ]
            }
        }

        result = evaluate_dataframe(self.df, config)

        self.assertEqual(result.loc[0, COL_MATCHED], YES)
        self.assertNotEqual(result.loc[1, COL_MATCHED], YES)

    def test_in_operator(self):
        config = {
            "rules": {
                "any": [
                    {"field": CODE, "operator": "in", "value": ["000001", "600000"], "name": "watchlist"}
                ]
            }
        }

        result = evaluate_dataframe(self.df, config)

        self.assertEqual(result.loc[0, COL_MATCHED], YES)
        self.assertNotEqual(result.loc[1, COL_MATCHED], YES)

    def test_missing_field_raises_error(self):
        config = {"rules": {"field": "missing", "operator": ">=", "value": 1}}

        with self.assertRaises(MissingFieldError):
            evaluate_dataframe(self.df, config)


if __name__ == "__main__":
    unittest.main()
