from __future__ import annotations

import ast
import json
import re

from web_app.localperf.models import QualityResult


def _strip_fence(output: str) -> str:
    value = output.strip()
    match = re.fullmatch(r"```(?:python|json|sql)?\s*\n?(.*?)\n?```", value, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else value


def _python_quality(prompt_id: str, output: str) -> QualityResult:
    source = _strip_fence(output)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return QualityResult(passed=False, score=0, reason="invalid_python")
    forbidden = (ast.Import, ast.ImportFrom, ast.With, ast.AsyncWith, ast.Lambda, ast.ClassDef, ast.Global, ast.Nonlocal, ast.While, ast.AsyncFor)
    forbidden_names = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint"}
    if any(isinstance(node, forbidden) or isinstance(node, ast.Name) and node.id in forbidden_names for node in ast.walk(tree)):
        return QualityResult(passed=False, score=0, reason="unsafe_python")
    expected = "clamp" if prompt_id == "lp-07" else "deduplicate"
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == expected:
            return QualityResult(passed=False, score=0, reason="recursive_python")
        if isinstance(node, ast.Attribute) and not (
            isinstance(node.value, ast.Name) and node.value.id == "dict" and node.attr == "fromkeys"
        ):
            return QualityResult(passed=False, score=0, reason="unsafe_python")
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == expected]
    if len(functions) != 1:
        return QualityResult(passed=False, score=0, reason="missing_function")
    namespace: dict = {}
    try:
        exec(compile(tree, "<localperf-quality>", "exec"), {"__builtins__": {"min": min, "max": max, "set": set, "list": list, "dict": dict}}, namespace)
        function = namespace[expected]
        passed = function(10, 0, 5) == 5 and function(-1, 0, 5) == 0 if expected == "clamp" else function([1, 2, 1, 3, 2]) == [1, 2, 3]
    except Exception:
        passed = False
    return QualityResult(passed=passed, score=1.0 if passed else 0, reason="passed" if passed else "fixture_failed")


def evaluate_quality(prompt_id: str, output: str) -> QualityResult:
    if prompt_id in {"lp-07", "lp-08"}:
        return _python_quality(prompt_id, output)
    if prompt_id == "lp-09":
        try:
            value = json.loads(_strip_fence(output))
        except json.JSONDecodeError:
            return QualityResult(passed=False, score=0, reason="invalid_json")
        passed = value == {"status": "ok", "items": [1, 2]}
        return QualityResult(passed=passed, score=1.0 if passed else 0, reason="passed" if passed else "schema_mismatch")
    if prompt_id == "lp-10":
        sql = _strip_fence(output).strip().rstrip(";")
        passed = bool(re.fullmatch(r"SELECT\s+name\s+FROM\s+users\s+WHERE\s+id\s*=\s*\?", sql, re.IGNORECASE))
        return QualityResult(passed=passed, score=1.0 if passed else 0, reason="passed" if passed else "unsafe_or_invalid_sql")
    return QualityResult(passed=None, score=None, reason="not_scored")
