"""受限公式解释器：只处理白名单 AST 节点，绝不执行用户文本。"""
from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Any


class CalculationError(ValueError):
    pass


ALLOWED_FUNCTIONS = {
    "abs": abs, "min": min, "max": max, "round": round, "sqrt": math.sqrt,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "radians": math.radians,
    "degrees": math.degrees, "log": math.log, "exp": math.exp, "pow": pow,
}
ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load, ast.Call,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.BoolOp, ast.And, ast.Or,
)


def evaluate_expression(expression: str, values: dict[str, float]) -> float | bool:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculationError(f"表达式语法错误：{exc.msg}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise CalculationError(f"表达式包含不允许的语法：{type(node).__name__}")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS):
            raise CalculationError("只允许使用内置数学函数")
        if isinstance(node, ast.Name) and node.id not in values and node.id not in ALLOWED_FUNCTIONS:
            raise CalculationError(f"缺少参数：{node.id}")
    try:
        return eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, {**ALLOWED_FUNCTIONS, **values})
    except (ArithmeticError, ValueError, TypeError) as exc:
        raise CalculationError(f"计算失败：{exc}") from exc


def interpolate(rows: list[dict[str, float]], input_key: str, output_key: str, value: float) -> float:
    rows = sorted(rows, key=lambda row: float(row[input_key]))
    if len(rows) < 2:
        raise CalculationError("插值表至少需要两行")
    if value < float(rows[0][input_key]) or value > float(rows[-1][input_key]):
        raise CalculationError(f"参数 {input_key} 超出表格范围")
    for left, right in zip(rows, rows[1:]):
        x1, x2 = float(left[input_key]), float(right[input_key])
        if x1 <= value <= x2:
            y1, y2 = float(left[output_key]), float(right[output_key])
            return y1 if x1 == x2 else y1 + (value - x1) * (y2 - y1) / (x2 - x1)
    return float(rows[-1][output_key])


@dataclass
class Evaluation:
    value: float
    trace: list[dict[str, Any]]


def evaluate_rule(rule: dict[str, Any], values: dict[str, float]) -> Evaluation:
    for condition in rule.get("conditions", []):
        if not bool(evaluate_expression(condition["expression"], values)):
            raise CalculationError(condition.get("message") or f"不满足适用条件：{condition['expression']}")
    kind = rule.get("kind", "expression")
    if kind == "expression":
        value = evaluate_expression(rule["expression"], values)
        if isinstance(value, bool):
            raise CalculationError("公式表达式必须返回数值")
        return Evaluation(float(value), [{"type": "expression", "expression": rule["expression"], "value": float(value)}])
    table = rule.get("table", {})
    source = table.get("input")
    if source not in values:
        raise CalculationError(f"缺少查表参数：{source}")
    rows = table.get("rows", [])
    if kind == "lookup":
        match = next((row for row in rows if float(row[source]) == float(values[source])), None)
        if match is None:
            raise CalculationError(f"参数 {source} 没有对应表格值")
        value = float(match[table["output"]])
    elif kind == "interpolation":
        value = interpolate(rows, source, table["output"], float(values[source]))
    else:
        raise CalculationError("未知计算规则类型")
    return Evaluation(value, [{"type": kind, "input": source, "value": values[source], "result": value}])
