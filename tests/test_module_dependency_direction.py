"""Architecture dependency direction tests for non-HTTP Modules."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]


def test_non_http_modules_do_not_depend_on_http_adapter() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    roots = (
        repository_root / "src" / "ainrf" / "domain",
        repository_root / "src" / "ainrf" / "domain_migration",
        repository_root / "src" / "ainrf" / "harness_engine",
    )
    violations: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = node.module if isinstance(node, ast.ImportFrom) else None
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
                imported = [module] if module is not None else names
                if any(name == "ainrf.api" or name.startswith("ainrf.api.") for name in imported):
                    violations.append(
                        f"{path.relative_to(repository_root)}:{getattr(node, 'lineno', 0)}"
                    )
    assert violations == [], "non-HTTP Module imports HTTP Adapter: " + ", ".join(violations)
