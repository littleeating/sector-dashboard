from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd


COL_MATCHED = "\u547d\u4e2d\u7ed3\u679c"
COL_RULES = "\u547d\u4e2d\u89c4\u5219"
YES = "\u662f"
NO = "\u5426"

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
    """Raised when the rule configuration is invalid."""


class MissingFieldError(RuleConfigError):
    """Raised when input data does not contain a required rule field."""


def validate_rules_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise RuleConfigError("Rule config must be a JSON object.")
    if "rules" not in config:
        raise RuleConfigError("Rule config must contain a rules root node.")
    if not isinstance(config["rules"], dict):
        raise RuleConfigError("rules must be a rule group object.")
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
        raise MissingFieldError("Input file is missing rule fields: " + ", ".join(missing))


def evaluate_dataframe(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    config = validate_rules_config(config)
    root_rule = config["rules"]
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
        raise RuleConfigError("Each rule must be a JSON object.")

    if "field" in rule:
        field = rule.get("field")
        if not isinstance(field, str) or not field.strip():
            raise RuleConfigError("Condition field must be a non-empty string.")
        fields.add(field.strip())
        _validate_condition(rule)
        return

    logic_keys = [key for key in ("all", "any") if key in rule]
    if len(logic_keys) != 1:
        raise RuleConfigError("A group rule must contain exactly one of all or any.")

    children = rule[logic_keys[0]]
    if not isinstance(children, list) or not children:
        raise RuleConfigError(f"{logic_keys[0]} must be a non-empty array.")

    for child in children:
        _walk_rule(child, fields)


def _validate_condition(rule: dict[str, Any]) -> None:
    operator = rule.get("operator")
    if operator not in SUPPORTED_OPERATORS:
        raise RuleConfigError(f"Unsupported operator: {operator}")

    if operator in {"is_empty", "not_empty"}:
        return

    if "value" not in rule:
        raise RuleConfigError(f"Condition for field {rule.get('field')} is missing value.")

    if operator == "between":
        value = rule.get("value")
        if not isinstance(value, list) or len(value) != 2:
            raise RuleConfigError("between value must be a two-item array, for example [0, 10].")

    if operator in {"in", "not_in"} and not isinstance(rule.get("value"), list):
        raise RuleConfigError(f"{operator} value must be an array.")


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

    raise RuleConfigError("A group rule must contain all or any.")


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

    raise RuleConfigError(f"Unsupported operator: {operator}")


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
    raise RuleConfigError(f"Unsupported comparison operator: {operator}")


def _rule_name(rule: dict[str, Any]) -> str:
    name = rule.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    if "field" in rule:
        return f"{rule.get('field')} {rule.get('operator')} {rule.get('value', '')}".strip()
    return "Unnamed group"


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
    if text in {"--", "-", "\u65e0", "nan", "NaN", "None"}:
        return None

    text = text.replace(",", "").replace("\uff0c", "")
    text = text.replace("\uff05", "%")
    if text.endswith("%"):
        text = text[:-1].strip()

    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None
