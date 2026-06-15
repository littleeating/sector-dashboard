from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Font, PatternFill

from filter_engine import COL_MATCHED, MissingFieldError, RuleConfigError, YES, evaluate_dataframe


COL_FILTER_TIME = "\u7b5b\u9009\u65f6\u95f4"


def main() -> int:
    args = parse_args()

    try:
        config = load_config(args.config)
        df = read_input(args.input)
        result = evaluate_dataframe(df, config)
        result[COL_FILTER_TIME] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        write_output(result, args.output, selected_only=args.selected_only)
    except (FileNotFoundError, MissingFieldError, RuleConfigError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}")
        return 1

    selected_count = int((result[COL_MATCHED] == YES).sum())
    print(f"Done: {len(result)} rows processed, {selected_count} selected.")
    print(f"Output: {Path(args.output).resolve()}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter stocks from Tonghuashun-exported CSV/Excel files using JSON rules."
    )
    parser.add_argument("--input", required=True, help="Input .xlsx/.xls/.csv path exported from Tonghuashun.")
    parser.add_argument("--config", required=True, help="JSON rule config path.")
    parser.add_argument("--output", required=True, help="Output Excel path, for example output/selected.xlsx.")
    parser.add_argument(
        "--selected-only",
        action="store_true",
        help="Only output selected rows. By default all rows are output with match columns.",
    )
    return parser.parse_args()


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def read_input(path: str | Path) -> pd.DataFrame:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    suffix = input_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(input_path, dtype=str)
    elif suffix == ".csv":
        df = _read_csv(input_path)
    else:
        raise ValueError("Input file must be .xlsx, .xls, or .csv.")

    if df.empty:
        raise ValueError("Input file has no data rows.")

    df = df.copy()
    df.columns = [str(column).strip() for column in df.columns]
    return df


def write_output(df: pd.DataFrame, path: str | Path, selected_only: bool = False) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_df = df[df[COL_MATCHED] == YES].copy() if selected_only else df.copy()
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        output_df.to_excel(writer, index=False, sheet_name="\u7b5b\u9009\u7ed3\u679c")
        _format_sheet(writer, "\u7b5b\u9009\u7ed3\u679c")


def _read_csv(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "gbk", "gb18030"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return pd.read_csv(path, encoding=encoding, dtype=str)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"Could not read CSV encoding. Save as UTF-8 or GBK. Last error: {last_error}")


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

        header = str(column_cells[0].value or "")
        if header in {"\u4ee3\u7801", "code", "Code", "stock_code", "Stock Code"}:
            for cell in column_cells[1:]:
                cell.number_format = "@"


if __name__ == "__main__":
    raise SystemExit(main())
