from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DependencyViolation:
    path: Path
    line: int
    message: str


def find_dependency_violations(source_root: Path) -> tuple[DependencyViolation, ...]:
    """Return forbidden HTTP Adapter dependencies and product import cycles."""

    modules = {
        _module_name(source_root, path): path
        for path in sorted(source_root.rglob("*.py"))
        if "__pycache__" not in path.parts
    }
    edges: dict[str, set[str]] = {module: set() for module in modules}
    violations: list[DependencyViolation] = []
    adapter_prefix = "".join(("ainrf", ".api"))

    for module, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for target, line in _import_targets(tree, module):
            resolved = _known_module(target, modules)
            if resolved is not None and resolved != module:
                edges[module].add(resolved)
            if not _is_http_adapter(module) and _is_http_adapter(target):
                violations.append(
                    DependencyViolation(
                        path,
                        line,
                        f"{module} statically depends on the HTTP Adapter via {target}",
                    )
                )
        if not _is_http_adapter(module):
            reported_lines: set[int] = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.expr):
                    continue
                value = _constant_string(node)
                if (
                    value is not None
                    and _is_adapter_entry(value, adapter_prefix)
                    and node.lineno not in reported_lines
                ):
                    reported_lines.add(node.lineno)
                    violations.append(
                        DependencyViolation(
                            path,
                            node.lineno,
                            f"{module} contains an HTTP Adapter string entry",
                        )
                    )

    for cycle in _find_cycles(edges):
        first = modules[cycle[0]]
        violations.append(
            DependencyViolation(
                first,
                1,
                "product import cycle: " + " -> ".join((*cycle, cycle[0])),
            )
        )
    return tuple(sorted(violations, key=lambda item: (str(item.path), item.line, item.message)))


def _module_name(source_root: Path, path: Path) -> str:
    relative = path.relative_to(source_root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_targets(tree: ast.AST, module: str) -> Iterable[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(module, node.module, node.level)
            if base:
                yield base, node.lineno
                for alias in node.names:
                    if alias.name != "*":
                        yield f"{base}.{alias.name}", node.lineno


def _resolve_import_from(module: str, imported: str | None, level: int) -> str:
    if level == 0:
        return imported or ""
    package = module.split(".")[:-1]
    keep = len(package) - level + 1
    prefix = package[: max(keep, 0)]
    if imported:
        prefix.extend(imported.split("."))
    return ".".join(prefix)


def _known_module(target: str, modules: dict[str, Path]) -> str | None:
    candidate = target
    while candidate:
        if candidate in modules:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def _is_http_adapter(module: str) -> bool:
    prefix = "".join(("ainrf", ".api"))
    return module == prefix or module.startswith(prefix + ".")


def _is_adapter_entry(value: str, prefix: str) -> bool:
    return value == prefix or value.startswith(prefix + ".") or value.startswith(prefix + ":")


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left)
        right = _constant_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            part = _constant_string(value)
            if part is None:
                return None
            parts.append(part)
        return "".join(parts)
    return None


def _find_cycles(edges: dict[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    visited: set[str] = set()
    active: list[str] = []
    active_set: set[str] = set()
    cycles: set[tuple[str, ...]] = set()

    def visit(module: str) -> None:
        visited.add(module)
        active.append(module)
        active_set.add(module)
        for target in sorted(edges[module]):
            if target not in visited:
                visit(target)
            elif target in active_set:
                start = active.index(target)
                cycle = tuple(active[start:])
                rotations = tuple(cycle[index:] + cycle[:index] for index in range(len(cycle)))
                cycles.add(min(rotations))
        active.pop()
        active_set.remove(module)

    for module in sorted(edges):
        if module not in visited:
            visit(module)
    return tuple(sorted(cycles))
