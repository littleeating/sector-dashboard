from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd


COL_MATCHED = "命中结果"
COL_RULES = "命中规则"
YES = "是"
NO = "否"

SUPPORTED_OPERATORS = {
    ">",
    ">=",
    "<",
    "<=",
    "==",
    "!=",
    "between",
    "contains",
    "not_contains",
    "in",
    "not_in",
    "is_empty",
    "not_empty",
}


@dataclass(frozen=True)
class FilterResult:
    matched: bool
    matched_rules: list[str]


class RuleConfigError(ValueError):
    """规则配置格式不正确时抛出。"""


class MissingFieldError(RuleConfigError):
    """输入文件缺少规则引用字段时抛出。"""


def validate_rules_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise RuleConfigError("规则配置必须是 JSON 对象。")
    if "rules" not in config:
        return {"rules": {"all": []}}
    if not isinstance(config["rules"], dict):
        raise RuleConfigError("rules 必须是一个规则分组对象。")
    return config


def collect_required_fields(rule: dict[str, Any]) -> set[str]:
    fields: set[str] = set()
    _walk_rule(rule, fields)
    return fields


def ensure_required_fields(rule: dict[str, Any], columns: Iterable[str]) -> None:
    available = {str(column).strip() for column in columns}
    required = collect_required_fields(rule)
    missing = sorted(field for field in required if field not in available)
    if missing:
        raise MissingFieldError("输入文件缺少规则引用字段: " + ", ".join(missing))


def evaluate_dataframe(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    config = validate_rules_config(config)
    root_rule = config["rules"]
    if _is_empty_group(root_rule):
        output = df.copy()
        output[COL_MATCHED] = YES
        output[COL_RULES] = ""
        return output

    ensure_required_fields(root_rule, df.columns)

    results = [evaluate_row(row, root_rule) for _, row in df.iterrows()]
    output = df.copy()
    output[COL_MATCHED] = [YES if result.matched else NO for result in results]
    output[COL_RULES] = ["; ".join(result.matched_rules) for result in results]
    return output


def evaluate_row(row: pd.Series, rule: dict[str, Any]) -> FilterResult:
    matched, matched_rules = _evaluate_rule(row, rule)
    return FilterResult(matched=matched, matched_rules=matched_rules)


def _walk_rule(rule: dict[str, Any], fields: set[str]) -> None:
    if not isinstance(rule, dict):
        raise RuleConfigError("每条规则必须是 JSON 对象。")

    if "field" in rule:
        field = rule.get("field")
        if not isinstance(field, str) or not field.strip():
            raise RuleConfigError("条件规则的 field 必须是非空字符串。")
        fields.add(field.strip())
        _validate_condition(rule)
        return

    logic_keys = [key for key in ("all", "any") if key in rule]
    if len(logic_keys) != 1:
        raise RuleConfigError("分组规则必须且只能包含 all 或 any。")

    children = rule[logic_keys[0]]
    if not isinstance(children, list):
        raise RuleConfigError(f"{logic_keys[0]} 必须是数组。")

    for child in children:
        _walk_rule(child, fields)


def _validate_condition(rule: dict[str, Any]) -> None:
    operator = rule.get("operator")
    if operator not in SUPPORTED_OPERATORS:
        raise RuleConfigError(f"不支持的操作符: {operator}")

    if operator in {"is_empty", "not_empty"}:
        return

    if "value" not in rule:
        raise RuleConfigError(f"字段 {rule.get('field')} 的条件缺少 value。")

    if operator == "between":
        value = rule.get("value")
        if not isinstance(value, list) or len(value) != 2:
            raise RuleConfigError("between 的 value 必须是两个元素的数组，例如 [0, 10]。")

    if operator in {"in", "not_in"} and not isinstance(rule.get("value"), list):
        raise RuleConfigError(f"{operator} 的 value 必须是数组。")


def _evaluate_rule(row: pd.Series, rule: dict[str, Any]) -> tuple[bool, list[str]]:
    if "field" in rule:
        matched = _evaluate_condition(row, rule)
        return matched, [_rule_name(rule)] if matched else []

    if "all" in rule:
        matched_rules: list[str] = []
        for child in rule["all"]:
            matched, child_matches = _evaluate_rule(row, child)
            if not matched:
                return False, []
            matched_rules.extend(child_matches)
        return True, [_rule_name(rule)] + matched_rules

    if "any" in rule:
        matched_rules = []
        for child in rule["any"]:
            matched, child_matches = _evaluate_rule(row, child)
            if matched:
                matched_rules.extend(child_matches)
        return bool(matched_rules), ([_rule_name(rule)] + matched_rules if matched_rules else [])

    raise RuleConfigError("分组规则必须包含 all 或 any。")


def _evaluate_condition(row: pd.Series, rule: dict[str, Any]) -> bool:
    field = str(rule["field"]).strip()
    operator = rule["operator"]
    actual = row[field]
    expected = rule.get("value")

    if operator == "is_empty":
        return _is_empty(actual)
    if operator == "not_empty":
        return not _is_empty(actual)

    if operator in {">", ">=", "<", "<=", "==", "!=", "between"}:
        actual_number = _to_number(actual)
        if operator == "between":
            low = _to_number(expected[0])
            high = _to_number(expected[1])
            return actual_number is not None and low is not None and high is not None and low <= actual_number <= high

        expected_number = _to_number(expected)
        if actual_number is not None and expected_number is not None:
            return _compare(actual_number, expected_number, operator)
        return _compare(_normalize_text(actual), _normalize_text(expected), operator)

    if operator in {"contains", "not_contains"}:
        actual_text = _normalize_text(actual)
        expected_text = _normalize_text(expected)
        contains = expected_text in actual_text
        return contains if operator == "contains" else not contains

    if operator in {"in", "not_in"}:
        actual_text = _normalize_text(actual)
        expected_values = {_normalize_text(item) for item in expected}
        found = actual_text in expected_values
        return found if operator == "in" else not found

    raise RuleConfigError(f"不支持的操作符: {operator}")


def _compare(actual: Any, expected: Any, operator: str) -> bool:
    if operator == ">":
        return actual > expected
    if operator == ">=":
        return actual >= expected
    if operator == "<":
        return actual < expected
    if operator == "<=":
        return actual <= expected
    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected
    raise RuleConfigError(f"不支持的比较操作符: {operator}")


def _rule_name(rule: dict[str, Any]) -> str:
    name = rule.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    if "field" in rule:
        return f"{rule.get('field')} {rule.get('operator')} {rule.get('value', '')}".strip()
    return "未命名分组"


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip() == ""


def _normalize_text(value: Any) -> str:
    if _is_empty(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _to_number(value: Any) -> float | None:
    if _is_empty(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    text = str(value).strip()
    if text in {"--", "-", "无", "nan", "NaN", "None"}:
        return None

    # 同花顺导出里常见百分号、中文逗号和千分位，这里先清洗再提取数字。
    text = text.replace(",", "").replace("，", "")
    text = text.replace("％", "%")
    if text.endswith("%"):
        text = text[:-1].strip()

    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def to_number(value: Any) -> float | None:
    return _to_number(value)


def _is_empty_group(rule: dict[str, Any]) -> bool:
    return (
        isinstance(rule, dict)
        and (("all" in rule and rule["all"] == []) or ("any" in rule and rule["any"] == []))
    )
