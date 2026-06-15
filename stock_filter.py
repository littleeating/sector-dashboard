from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Font, PatternFill

from filter_engine import COL_MATCHED, COL_RULES, MissingFieldError, RuleConfigError, YES, evaluate_dataframe, to_number


COL_FILTER_TIME = "筛选时间"
COL_FIRST_RETURN = "近X日涨幅"
COL_SECOND_RETURN = "近A日涨幅"

OUTPUT_ALIASES = {
    "股票名称": ["股票名称", "名称", "股票简称", "证券简称"],
    "股票板块": ["股票板块", "板块", "所属板块", "行业", "所属行业"],
    "主营业务": ["主营业务", "公司主营业务", "主营构成", "经营范围"],
    "近1季度营收": ["近1季度营收", "最近季度营收", "营业收入_T0", "营业收入1", "营收1"],
    "近1季度净利润": ["近1季度净利润", "最近季度净利润", "净利润_T0", "净利润1"],
    "近1季度净利润增速": ["近1季度净利润增速", "最近季度净利润增速", "净利润增速_T0", "净利润增速1"],
    "近2季度营收": ["近2季度营收", "上1季度营收", "营业收入_T1", "营业收入2", "营收2"],
    "近2季度净利润": ["近2季度净利润", "上1季度净利润", "净利润_T1", "净利润2"],
    "近2季度净利润增速": ["近2季度净利润增速", "上1季度净利润增速", "净利润增速_T1", "净利润增速2"],
    "近3季度营收": ["近3季度营收", "上2季度营收", "营业收入_T2", "营业收入3", "营收3"],
    "近3季度净利润": ["近3季度净利润", "上2季度净利润", "净利润_T2", "净利润3"],
    "近3季度净利润增速": ["近3季度净利润增速", "上2季度净利润增速", "净利润增速_T2", "净利润增速3"],
    "近4季度营收": ["近4季度营收", "上3季度营收", "营业收入_T3", "营业收入4", "营收4"],
    "近4季度净利润": ["近4季度净利润", "上3季度净利润", "净利润_T3", "净利润4"],
    "近4季度净利润增速": ["近4季度净利润增速", "上3季度净利润增速", "净利润增速_T3", "净利润增速4"],
}


def main() -> int:
    args = parse_args()

    try:
        config = load_config(args.config)
        df = read_input(args.input)
        result = apply_return_filters(df, args.rise_days, args.rise_threshold, args.flat_days, args.flat_threshold)
        result = apply_optional_technical_filters(result, config)
        result[COL_FILTER_TIME] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        output_df = build_summary_output(result)
        write_output(output_df, args.output)
    except (FileNotFoundError, MissingFieldError, RuleConfigError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误: {exc}")
        return 1

    selected_count = len(output_df)
    print(f"筛选完成: 共处理 {len(df)} 行，入选 {selected_count} 行。")
    print(f"输出文件: {Path(args.output).resolve()}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="读取同花顺导出的 CSV/Excel 文件，并按 JSON 规则筛选股票。")
    parser.add_argument("--input", required=True, help="同花顺导出的 .xlsx/.xls/.csv 文件路径。")
    parser.add_argument("--rise-days", type=int, required=True, help="第一个条件：近 X 个交易日。")
    parser.add_argument("--rise-threshold", type=float, required=True, help="第一个条件：近 X 个交易日涨幅必须超过 Y%。")
    parser.add_argument("--flat-days", type=int, required=True, help="第二个条件：近 A 个交易日。")
    parser.add_argument("--flat-threshold", type=float, required=True, help="第二个条件：近 A 个交易日涨幅必须不超过 B%。")
    parser.add_argument("--config", default="", help="可选技术指标 JSON 配置路径；不填即不关注额外技术指标。")
    parser.add_argument("--output", required=True, help="输出 Excel 文件路径，例如 output/selected.xlsx。")
    return parser.parse_args()


def load_config(path: str | Path) -> dict[str, Any]:
    if not path:
        return {"rules": {"all": []}}
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"找不到配置文件: {config_path}")
    with config_path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def read_input(path: str | Path) -> pd.DataFrame:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"找不到输入文件: {input_path}")

    suffix = input_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        # 按文本读取，避免股票代码 000001 被自动转成数字 1。
        df = pd.read_excel(input_path, dtype=str)
    elif suffix == ".csv":
        df = _read_csv(input_path)
    else:
        raise ValueError("输入文件必须是 .xlsx、.xls 或 .csv。")

    if df.empty:
        raise ValueError("输入文件没有可筛选的数据行。")

    df = df.copy()
    df.columns = [str(column).strip() for column in df.columns]
    return df


def write_output(df: pd.DataFrame, path: str | Path, selected_only: bool = False) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_df = df[df[COL_MATCHED] == YES].copy() if selected_only else df.copy()
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        output_df.to_excel(writer, index=False, sheet_name="筛选结果")
        _format_sheet(writer, "筛选结果")


def _read_csv(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "gbk", "gb18030"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return pd.read_csv(path, encoding=encoding, dtype=str)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"无法识别 CSV 编码，请另存为 UTF-8 或 GBK。最后一次错误: {last_error}")


def _format_sheet(writer: pd.ExcelWriter, sheet_name: str) -> None:
    sheet = writer.sheets[sheet_name]
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    header_fill = PatternFill(fill_type="solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font

    for column_cells in sheet.columns:
        values = [str(cell.value) if cell.value is not None else "" for cell in column_cells]
        width = min(max(max(len(value) for value in values) + 2, 10), 32)
        sheet.column_dimensions[column_cells[0].column_letter].width = width

        # 股票代码列按文本格式输出，避免 Excel 打开时丢失前导零。
        header = str(column_cells[0].value or "")
        if header in {"代码", "code", "Code", "stock_code", "Stock Code"}:
            for cell in column_cells[1:]:
                cell.number_format = "@"


def apply_return_filters(
    df: pd.DataFrame,
    rise_days: int,
    rise_threshold: float,
    flat_days: int,
    flat_threshold: float,
) -> pd.DataFrame:
    if rise_days <= 0 or flat_days <= 0:
        raise ValueError("交易日参数必须大于 0。")

    output = df.copy()
    first_return = get_recent_return_series(output, rise_days)
    second_return = get_recent_return_series(output, flat_days)
    output[COL_FIRST_RETURN] = first_return
    output[COL_SECOND_RETURN] = second_return

    matched = (first_return > rise_threshold) & (second_return <= flat_threshold)
    output[COL_MATCHED] = matched.map(lambda value: YES if value else "否")
    output[COL_RULES] = matched.map(
        lambda value: f"近{rise_days}日涨幅>{rise_threshold}%; 近{flat_days}日涨幅<={flat_threshold}%" if value else ""
    )
    return output[output[COL_MATCHED] == YES].copy()


def apply_optional_technical_filters(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if not has_active_rules(config):
        return df.copy()

    original_rules = df[COL_RULES].copy() if COL_RULES in df.columns else pd.Series([""] * len(df), index=df.index)
    evaluated = evaluate_dataframe(df, config)
    evaluated = evaluated[evaluated[COL_MATCHED] == YES].copy()
    evaluated[COL_RULES] = [
        _join_rules(original_rules.loc[index], evaluated.loc[index, COL_RULES])
        for index in evaluated.index
    ]
    return evaluated


def get_recent_return_series(df: pd.DataFrame, days: int) -> pd.Series:
    direct_column = find_column(df, return_column_candidates(days), required=False)
    if direct_column:
        return df[direct_column].map(to_number)

    current_column = find_column(df, ["最新价", "现价", "收盘价", "最新收盘价"], required=False)
    past_column = find_column(
        df,
        [
            f"{days}日前收盘价",
            f"{days}交易日前收盘价",
            f"{days}个交易日前收盘价",
            f"{days}日前价格",
            f"{days}日前收盘",
        ],
        required=False,
    )
    if current_column and past_column:
        current = df[current_column].map(to_number)
        past = df[past_column].map(to_number)
        return (current / past - 1) * 100

    raise MissingFieldError(
        "找不到近"
        f"{days}"
        "个交易日涨幅字段。请在导出文件中加入类似 "
        f"“近{days}日涨幅” 的列，或同时提供“最新价”和“{days}日前收盘价”。"
    )


def return_column_candidates(days: int) -> list[str]:
    return [
        f"近{days}日涨幅",
        f"近{days}个交易日涨幅",
        f"近{days}日涨跌幅",
        f"近{days}个交易日涨跌幅",
        f"{days}日涨幅",
        f"{days}日涨跌幅",
        f"{days}个交易日涨幅",
        f"{days}个交易日涨跌幅",
    ]


def build_summary_output(df: pd.DataFrame) -> pd.DataFrame:
    output = pd.DataFrame()
    missing: list[str] = []
    for output_name, candidates in OUTPUT_ALIASES.items():
        column = find_column(df, candidates, required=False)
        if column:
            output[output_name] = df[column]
        else:
            missing.append(output_name)
            output[output_name] = ""

    output[COL_FIRST_RETURN] = df[COL_FIRST_RETURN]
    output[COL_SECOND_RETURN] = df[COL_SECOND_RETURN]
    if COL_RULES in df.columns:
        output[COL_RULES] = df[COL_RULES]
    output[COL_FILTER_TIME] = df[COL_FILTER_TIME]

    if missing:
        print("提示: 以下输出字段在输入文件中未找到，已留空: " + ", ".join(missing))
    return output


def find_column(df: pd.DataFrame, candidates: list[str], required: bool = True) -> str | None:
    columns = {str(column).strip(): str(column).strip() for column in df.columns}
    normalized = {_normalize_column_name(column): column for column in columns}
    for candidate in candidates:
        if candidate in columns:
            return columns[candidate]
        normalized_candidate = _normalize_column_name(candidate)
        if normalized_candidate in normalized:
            return normalized[normalized_candidate]
    if required:
        raise MissingFieldError("输入文件缺少字段，候选列名: " + ", ".join(candidates))
    return None


def _normalize_column_name(value: str) -> str:
    return str(value).strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def has_active_rules(config: dict[str, Any]) -> bool:
    rules = config.get("rules")
    if not isinstance(rules, dict):
        return False
    if "field" in rules:
        return True
    for key in ("all", "any"):
        children = rules.get(key)
        if isinstance(children, list) and children:
            return True
    return False


def _join_rules(*parts: str) -> str:
    return "; ".join(part for part in parts if isinstance(part, str) and part.strip())


if __name__ == "__main__":
    raise SystemExit(main())
