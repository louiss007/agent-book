from __future__ import annotations

import re
from typing import Any

_TYPE_CHECKS = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> list[str]:
    """按 JSON Schema 的子集校验参数，返回可直接回传模型的错误列表。"""
    errors: list[str] = []
    _validate(schema, arguments, "arguments", errors)
    return errors


def _validate(schema: Any, value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(schema, dict):
        return

    expected = schema.get("type")
    if expected is not None:
        expected_types = expected if isinstance(expected, list) else [expected]
        checks = [_TYPE_CHECKS.get(name) for name in expected_types]
        if any(check is not None for check in checks) and not any(
            check is not None and check(value) for check in checks
        ):
            errors.append(
                f"{path}: 期望类型 {' / '.join(map(str, expected_types))}，"
                f"实际是 {type(value).__name__}"
            )
            return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 必须是 {schema['enum']!r} 之一")

    if isinstance(value, str):
        _validate_string(schema, value, path, errors)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _validate_number(schema, value, path, errors)
    elif isinstance(value, dict):
        _validate_object(schema, value, path, errors)
    elif isinstance(value, list):
        _validate_array(schema, value, path, errors)

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for option in all_of:
            _validate(option, value, path, errors)

    for keyword in ("anyOf", "oneOf"):
        options = schema.get(keyword)
        if not isinstance(options, list) or not options:
            continue
        matches = 0
        for option in options:
            trial: list[str] = []
            _validate(option, value, path, trial)
            if not trial:
                matches += 1
        if keyword == "anyOf" and matches == 0:
            errors.append(f"{path}: 不满足 anyOf 中的任何一项")
        if keyword == "oneOf" and matches != 1:
            errors.append(f"{path}: 必须恰好满足 oneOf 中的一项")


def _validate_string(
    schema: dict[str, Any], value: str, path: str, errors: list[str]
) -> None:
    if "minLength" in schema and len(value) < schema["minLength"]:
        errors.append(f"{path}: 长度不能小于 {schema['minLength']}")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        errors.append(f"{path}: 长度不能大于 {schema['maxLength']}")
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            if re.search(pattern, value) is None:
                errors.append(f"{path}: 不匹配模式 {pattern!r}")
        except re.error:
            pass


def _validate_number(
    schema: dict[str, Any], value: float, path: str, errors: list[str]
) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: 不能小于 {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{path}: 不能大于 {schema['maximum']}")
    if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
        errors.append(f"{path}: 必须大于 {schema['exclusiveMinimum']}")
    if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
        errors.append(f"{path}: 必须小于 {schema['exclusiveMaximum']}")


def _validate_object(
    schema: dict[str, Any], value: dict[str, Any], path: str, errors: list[str]
) -> None:
    required = schema.get("required", [])
    if isinstance(required, list):
        for key in required:
            if isinstance(key, str) and key not in value:
                errors.append(f"{path}: 缺少必填字段 '{key}'")

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    additional = schema.get("additionalProperties", True)

    for key, item in value.items():
        if key in properties:
            _validate(properties[key], item, f"{path}.{key}", errors)
        elif additional is False:
            errors.append(f"{path}: 不允许字段 '{key}'")
        elif isinstance(additional, dict):
            _validate(additional, item, f"{path}.{key}", errors)


def _validate_array(
    schema: dict[str, Any], value: list[Any], path: str, errors: list[str]
) -> None:
    if "minItems" in schema and len(value) < schema["minItems"]:
        errors.append(f"{path}: 元素个数不能少于 {schema['minItems']}")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        errors.append(f"{path}: 元素个数不能多于 {schema['maxItems']}")
    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for index, item in enumerate(value):
            _validate(item_schema, item, f"{path}[{index}]", errors)
