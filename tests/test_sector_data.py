import tempfile
import unittest
from pathlib import Path

import pandas as pd

from sector_data import (
    AccessPolicy,
    CacheStore,
    SourceStatus,
    SuspiciousLimitError,
    fetch_with_policy,
    get_or_fetch_history,
    is_suspicious_limit_error,
)


class SectorDataTest(unittest.TestCase):
    def test_access_policy_defaults_to_single_worker_and_safe_delay(self):
        policy = AccessPolicy()

        self.assertEqual(policy.max_workers, 1)
        self.assertGreaterEqual(policy.min_delay, 1.2)
        self.assertLessEqual(policy.max_delay, 2.5)

    def test_access_policy_rejects_more_than_two_workers(self):
        with self.assertRaises(ValueError):
            AccessPolicy(max_workers=3)

    def test_cache_hit_skips_external_fetch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = CacheStore(Path(temp_dir))
            cached = pd.DataFrame({"date": ["2026-06-26"], "close": [100.0]})
            cache.write_history("industry", "半导体", cached, data_date="2026-06-26")
            calls = []

            def fetcher():
                calls.append("called")
                return pd.DataFrame({"date": ["2026-06-27"], "close": [101.0]})

            result = get_or_fetch_history(
                cache=cache,
                category="industry",
                name="半导体",
                latest_date="2026-06-26",
                fetcher=fetcher,
                policy=AccessPolicy(min_delay=0, max_delay=0),
                status=SourceStatus(source="eastmoney"),
                sleeper=lambda _: None,
            )

            self.assertEqual(calls, [])
            self.assertEqual(result.iloc[0]["close"], 100.0)

    def test_fetch_with_policy_retries_twice_then_records_failure(self):
        attempts = []

        def fetcher():
            attempts.append("try")
            raise TimeoutError("timeout")

        status = SourceStatus(source="eastmoney")

        with self.assertRaises(TimeoutError):
            fetch_with_policy(
                fetcher,
                policy=AccessPolicy(min_delay=0, max_delay=0, retry_delays=(0, 0)),
                status=status,
                sleeper=lambda _: None,
            )

        self.assertEqual(len(attempts), 3)
        self.assertEqual(status.retries, 2)
        self.assertEqual(status.failed_requests, 1)

    def test_suspicious_limit_signal_stops_new_requests(self):
        self.assertTrue(is_suspicious_limit_error(Exception("HTTP 429 Too Many Requests")))
        self.assertTrue(is_suspicious_limit_error(Exception("请登录后继续访问")))

        status = SourceStatus(source="eastmoney")

        with self.assertRaises(SuspiciousLimitError):
            fetch_with_policy(
                lambda: (_ for _ in ()).throw(Exception("HTTP 403 Forbidden")),
                policy=AccessPolicy(min_delay=0, max_delay=0),
                status=status,
                sleeper=lambda _: None,
            )

        self.assertTrue(status.limited)
        self.assertIn("疑似限流", status.messages[0])


if __name__ == "__main__":
    unittest.main()
