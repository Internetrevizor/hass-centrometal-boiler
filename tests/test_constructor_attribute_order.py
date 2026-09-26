"""Static guard against reading an attribute before it is assigned.

`WebBoilerSystem.__init__` once read `self.refresh_interval` one line above the
assignment that creates it, which raised AttributeError and failed setup for
every user. The test that would have caught it needs Home Assistant installed,
which the sandbox this code is written in does not have — so this check parses
the source instead and needs nothing but the standard library.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "centrometal_boiler"


def _class_level_names(cls: ast.ClassDef) -> set[str]:
    """Methods and class attributes — these exist before __init__ runs."""
    names: set[str] = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _self_attribute_order_violations(func: ast.FunctionDef, known: set[str]) -> list[str]:
    """Return `self.x` reads in `func` that happen before `self.x = ...`."""
    assigned: set[str] = set(known)
    violations: list[str] = []

    # Statement by statement, in source order: a read inside a statement that
    # also assigns the name still counts as a read of the previous value.
    for statement in func.body:
        reads = {
            n.attr
            for n in ast.walk(statement)
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "self"
            and isinstance(n.ctx, ast.Load)
        }
        for name in sorted(reads - assigned):
            violations.append(f"{func.name}: self.{name} read on line {statement.lineno} before assignment")
        for n in ast.walk(statement):
            if (
                isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Name)
                and n.value.id == "self"
                and isinstance(n.ctx, ast.Store)
            ):
                assigned.add(n.attr)
    return violations


def test_constructors_do_not_read_attributes_before_assigning_them() -> None:
    problems: list[str] = []
    for path in sorted(INTEGRATION.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for func in (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"):
                for violation in _self_attribute_order_violations(func, _class_level_names(cls)):
                    problems.append(f"{path.relative_to(ROOT)}: {cls.name}.{violation}")
    assert not problems, "attribute read before assignment:\n  " + "\n  ".join(problems)
