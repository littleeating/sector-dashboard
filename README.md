# Tonghuashun Stock Export Filter

This project reads a CSV/Excel stock list exported from Tonghuashun, filters rows with JSON rules, and writes the result to an Excel workbook.

## Run

If this machine does not have Python on `PATH`, use the bundled Codex Python:

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' stock_filter.py --input data/input.template.xlsx --config config/rules.example.json --output output/selected.xlsx
```

Only write selected rows:

```powershell
& 'C:\Users\AERO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' stock_filter.py --input data/input.template.xlsx --config config/rules.example.json --output output/selected.xlsx --selected-only
```

## Input

Supported formats: `.xlsx`, `.xls`, `.csv`.

CSV files are read with these encodings in order: `utf-8-sig`, `gbk`, `gb18030`.

The first row must contain field names. The included template uses these columns:

- Stock code
- Stock name
- Percent change
- Turnover rate
- Volume ratio
- PE ratio
- Market cap
- Industry
- Concept

The actual workbook columns are in Chinese to match common Tonghuashun exports. Percent values such as `3.5%` and comma-formatted values such as `1,234.56` are supported.

## Rules

Rules live in JSON. The root object must contain `rules`.

Groups:

- `all`: every child condition must match
- `any`: at least one child condition must match

Operators:

- Numeric: `>`, `>=`, `<`, `<=`, `==`, `!=`, `between`
- Text: `contains`, `not_contains`, `in`, `not_in`
- Empty checks: `is_empty`, `not_empty`

If the config references a column that does not exist in the input file, the script stops and prints the missing fields.

## Output

The output Excel workbook contains the original columns plus:

- Match result
- Matched rules
- Filter time

The actual output column names are Chinese: match result, matched rules, and filter time.

## Notes

Version 1 filters only columns already exported by Tonghuashun. It does not calculate historical K-line indicators such as MACD, moving averages, or KDJ yet.
