"""AST-validated, restricted execution for generated analysis code.

This is a defense-in-depth guard inside the isolated worker container, not a
replacement for container isolation.
"""

from __future__ import annotations

import ast
import builtins
from types import ModuleType
from typing import Any


ALLOWED_MODULES = {
    "scanpy",
    "anndata",
    "numpy",
    "pandas",
    "app.qc",
    "app.omics_scientist",
}
DANGEROUS_CALLS = {
    "open", "eval", "exec", "compile", "__import__", "input",
    "globals", "locals", "vars", "dir", "getattr", "setattr",
}
SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in ("abs", "bool", "dict", "enumerate", "float", "int", "len", "list", "max", "min", "range", "str", "sum", "tuple", "zip")
}


class SandboxViolation(ValueError):
    """Raised when generated code violates the sandbox policy."""


def _module_root(name: str) -> str:
    return name.split(".", 1)[0]


def validate_code(code: str) -> ast.Module:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise SandboxViolation(f"Generated code is not valid Python: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_MODULES and _module_root(alias.name) not in ALLOWED_MODULES:
                    raise SandboxViolation(f"Import is not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if not node.module or (node.module not in ALLOWED_MODULES and _module_root(node.module) not in ALLOWED_MODULES):
                raise SandboxViolation(f"Import is not allowed: {node.module}")
            if any(alias.name.startswith("__") for alias in node.names):
                raise SandboxViolation("Dunder imports are not allowed")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in DANGEROUS_CALLS:
                raise SandboxViolation(f"Call is not allowed: {node.func.id}")
            if isinstance(node.func, ast.Attribute) and node.func.attr.startswith("__"):
                raise SandboxViolation(f"Dunder call is not allowed: {node.func.attr}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise SandboxViolation(f"Dunder attribute is not allowed: {node.attr}")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            raise SandboxViolation(f"Dunder name is not allowed: {node.id}")
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            raise SandboxViolation("Defining functions or classes is not allowed")
    return tree


def execute_generated_code(code: str, context: dict[str, Any]) -> dict[str, Any]:
    """Validate and execute generated code with only approved globals."""
    validate_code(code)

    def safe_import(name: str, globals=None, locals=None, fromlist=(), level=0):
        if name not in ALLOWED_MODULES and _module_root(name) not in ALLOWED_MODULES:
            raise SandboxViolation(f"Import is not allowed: {name}")
        module = __import__(name, globals, locals, fromlist, level)
        if not isinstance(module, ModuleType):
            raise SandboxViolation(f"Invalid imported module: {name}")
        return module

    globals_dict = {
        "__builtins__": {**SAFE_BUILTINS, "__import__": safe_import},
        **context,
    }
    locals_dict: dict[str, Any] = {}
    exec(compile(validate_code(code), "<agent-generated>", "exec"), globals_dict, locals_dict)
    return {key: value for key, value in locals_dict.items() if not key.startswith("_")}
