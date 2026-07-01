from __future__ import annotations

import argparse
import html as htmlmod
import re
from datetime import datetime, timedelta
from pathlib import Path

from sector_data import AccessPolicy, CacheStore, SourceStatus
from sector_dashboard import _load_stock_kline_data, _write_kline_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从已生成页面抽取入榜股票，并补齐本地 K 线快照。")
    parser.add_argument("--html", default="output/sector_dashboard/index.html", help="已生成的 HTML 文件。")
    parser.add_argument("--output-dir", default="output/sector_dashboard", help="网站输出目录。")
    parser.add_argument("--cache-dir", default="cache/sector_dashboard", help="缓存目录。")
    parser.add_argument("--cache-version", default="akshare-board-name-v2", help="缓存版本。")
    parser.add_argument("--request-budget", type=int, default=460, help="本轮最多新增请求数。")
    parser.add_argument("--min-delay", type=float, default=4.0, help="最小随机延迟秒数。")
    parser.add_argument("--max-delay", type=float, default=8.0, help="最大随机延迟秒数。")
    parser.add_argument("--timeout", type=float, default=15.0, help="单只股票 K 线请求超时秒数。")
    parser.add_argument("--lookback-days", type=int, default=180, help="向前请求的自然日窗口。")
    parser.add_argument("--source", choices=["eastmoney", "sina"], default="sina", help="K 线快照数据源。")
    parser.add_argument("--cache-only", action="store_true", help="只把已有缓存写到网站目录。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    html_text = Path(args.html).read_text(encoding="utf-8")
    targets: dict[str, str] = {}
    for code, name in re.findall(r'data-stock-code="([^"]+)"[^>]*data-stock-name="([^"]*)"', html_text):
        targets.setdefault(code, htmlmod.unescape(name) or code)

    print(f"targets={len(targets)}", flush=True)
    cache = CacheStore(args.cache_dir, version=args.cache_version)
    status = SourceStatus(source="eastmoney-local-kline")
    policy = AccessPolicy(max_workers=1, min_delay=args.min_delay, max_delay=args.max_delay)
    end = datetime.now()
    kline_data = _load_stock_kline_data(
        cache=cache,
        targets=targets,
        latest_date=end.strftime("%Y-%m-%d"),
        start_date=(end - timedelta(days=args.lookback_days)).strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        status=status,
        policy=policy,
        timeout_seconds=args.timeout,
        cache_only=args.cache_only,
        request_budget=args.request_budget,
        source=args.source,
    )
    written = _write_kline_files(output_dir=Path(args.output_dir), kline_data=kline_data)
    print(f"written={written}", flush=True)
    print(status.as_dict(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
