from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class RankingRow:
    name: str
    return_pct: float
    latest_date: str
    latest_close: float


@dataclass(frozen=True)
class TrendPoint:
    date: str
    return_pct: float


@dataclass(frozen=True)
class TrendSeries:
    name: str
    points: list[TrendPoint]
    code: str | None = None


def compute_return(history: pd.DataFrame, period: int) -> float | None:
    prepared = _prepare_history(history)
    if period <= 0:
        raise ValueError("period must be greater than 0")
    if len(prepared) <= period:
        return None

    current = float(prepared.iloc[-1]["close"])
    past = float(prepared.iloc[-period - 1]["close"])
    if past == 0:
        return None
    return round((current / past - 1) * 100, 2)


def rank_sectors(
    histories: dict[str, pd.DataFrame],
    periods: list[int],
    top_n: int,
) -> tuple[dict[int, list[RankingRow]], dict[str, int]]:
    if top_n <= 0:
        raise ValueError("top_n must be greater than 0")

    rankings: dict[int, list[RankingRow]] = {}
    quality = {"history_short": 0}
    short_seen: set[str] = set()

    for period in periods:
        rows: list[RankingRow] = []
        for name, raw_history in histories.items():
            prepared = _prepare_history(raw_history)
            return_pct = compute_return(prepared, period)
            if return_pct is None:
                short_seen.add(name)
                continue
            latest = prepared.iloc[-1]
            rows.append(
                RankingRow(
                    name=name,
                    return_pct=return_pct,
                    latest_date=str(latest["date"]),
                    latest_close=float(latest["close"]),
                )
            )
        rankings[period] = sorted(rows, key=lambda row: row.return_pct, reverse=True)[:top_n]

    quality["history_short"] = len(short_seen)
    return rankings, quality


def build_trend_series(
    histories: dict[str, pd.DataFrame],
    selected_names: list[str],
    lookback: int,
) -> list[TrendSeries]:
    if lookback <= 0:
        raise ValueError("lookback must be greater than 0")

    series: list[TrendSeries] = []
    for name in selected_names:
        if name not in histories:
            continue
        raw_history = histories[name]
        code = None
        if "code" in raw_history.columns:
            codes = raw_history["code"].dropna().map(str)
            if not codes.empty:
                code = str(codes.iloc[-1])
        prepared = _prepare_history(raw_history).tail(lookback)
        if prepared.empty:
            continue

        base = float(prepared.iloc[0]["close"])
        if base == 0:
            continue

        points = [
            TrendPoint(date=str(row["date"]), return_pct=round((float(row["close"]) / base - 1) * 100, 2))
            for _, row in prepared.iterrows()
        ]
        series.append(TrendSeries(name=name, points=points, code=code))
    return series


def _prepare_history(history: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "close"}
    missing = required - set(history.columns)
    if missing:
        raise ValueError("history is missing columns: " + ", ".join(sorted(missing)))

    prepared = history.loc[:, ["date", "close"]].copy()
    prepared["date"] = prepared["date"].map(str)
    prepared["close"] = prepared["close"].map(_to_float)
    prepared = prepared.dropna(subset=["close"])
    return prepared.sort_values("date").reset_index(drop=True)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
