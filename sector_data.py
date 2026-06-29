from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd


class SuspiciousLimitError(RuntimeError):
    """Raised when a source looks like it is limiting or blocking access."""


@dataclass(frozen=True)
class AccessPolicy:
    max_workers: int = 1
    min_delay: float = 1.2
    max_delay: float = 2.5
    retry_delays: tuple[float, ...] = (3.0, 8.0)

    def __post_init__(self) -> None:
        if self.max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if self.max_workers > 2:
            raise ValueError("max_workers must not exceed 2")
        if self.min_delay < 0 or self.max_delay < 0:
            raise ValueError("delay values must not be negative")
        if self.min_delay > self.max_delay:
            raise ValueError("min_delay must not exceed max_delay")


@dataclass
class SourceStatus:
    source: str
    requests: int = 0
    cache_hits: int = 0
    failed_requests: int = 0
    retries: int = 0
    limited: bool = False
    messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "requests": self.requests,
            "cache_hits": self.cache_hits,
            "failed_requests": self.failed_requests,
            "retries": self.retries,
            "limited": self.limited,
            "messages": self.messages,
        }


class CacheStore:
    def __init__(self, root: str | Path, version: str = "v1"):
        self.root = Path(root)
        self.version = version

    def read_history(self, category: str, name: str) -> tuple[pd.DataFrame, str] | None:
        path = self._history_path(category, name)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("cache_version", "v1") != self.version:
            return None
        return pd.DataFrame(payload["rows"]), str(payload["data_date"])

    def write_history(self, category: str, name: str, history: pd.DataFrame, data_date: str) -> None:
        path = self._history_path(category, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cache_version": self.version,
            "data_date": data_date,
            "rows": history.to_dict(orient="records"),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_history_names(self, category: str) -> list[str]:
        directory = self.root / category
        if not directory.exists():
            return []
        names: list[str] = []
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("cache_version", "v1") == self.version:
                names.append(path.stem)
        return names

    def _history_path(self, category: str, name: str) -> Path:
        return self.root / category / f"{_safe_filename(name)}.json"


def get_or_fetch_history(
    *,
    cache: CacheStore,
    category: str,
    name: str,
    latest_date: str,
    fetcher: Callable[[], pd.DataFrame],
    policy: AccessPolicy,
    status: SourceStatus,
    sleeper: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    cached = cache.read_history(category, name)
    if cached is not None:
        history, cached_date = cached
        if cached_date == latest_date:
            status.cache_hits += 1
            return history

    history = fetch_with_policy(fetcher, policy=policy, status=status, sleeper=sleeper)
    cache.write_history(category, name, history, data_date=latest_date)
    return history


def fetch_with_policy(
    fetcher: Callable[[], pd.DataFrame],
    *,
    policy: AccessPolicy,
    status: SourceStatus,
    sleeper: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    if status.limited:
        raise SuspiciousLimitError("疑似限流，已停止访问")

    attempts = len(policy.retry_delays) + 1
    for attempt in range(attempts):
        if attempt == 0:
            _sleep_between_requests(policy, sleeper)
        try:
            status.requests += 1
            return fetcher()
        except Exception as exc:
            if is_suspicious_limit_error(exc):
                status.limited = True
                status.failed_requests += 1
                message = f"疑似限流，已停止访问: {exc}"
                status.messages.append(message)
                raise SuspiciousLimitError(message) from exc

            if attempt >= attempts - 1:
                status.failed_requests += 1
                raise

            status.retries += 1
            sleeper(policy.retry_delays[attempt] + random.uniform(0, 0.5))

    raise RuntimeError("unreachable fetch retry state")


def is_suspicious_limit_error(error: Exception) -> bool:
    text = str(error).lower()
    suspicious_patterns = [
        "403",
        "429",
        "too many requests",
        "forbidden",
        "captcha",
        "验证码",
        "登录",
        "login",
    ]
    return any(pattern in text for pattern in suspicious_patterns)


def load_akshare() -> object:
    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 akshare，请先安装依赖后再运行实时数据模式。") from exc
    return ak


def _sleep_between_requests(policy: AccessPolicy, sleeper: Callable[[float], None]) -> None:
    delay = random.uniform(policy.min_delay, policy.max_delay)
    sleeper(delay)


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value.strip(), flags=re.UNICODE)
    return safe.strip("._") or "unnamed"
