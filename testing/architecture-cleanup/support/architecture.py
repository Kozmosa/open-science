"""Static architecture inventories used only by the P0-P6 cleanup guards."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import TypedDict

from fastapi import FastAPI


class ImportEdge(TypedDict):
    source: str
    target: str


class InterfaceItem(TypedDict):
    module: str
    name: str
    kind: str
    signature: str


class FrontendViolation(TypedDict):
    source: str
    target: str
    rule: str


class RouteItem(TypedDict):
    method: str
    path: str
    name: str
    deprecated: bool


_TS_IMPORT_RE = re.compile(
    r"(?:from\s+|import\s*\(\s*)[\"']([^\"']+)[\"']",
    re.MULTILINE,
)


def stable_digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def python_import_edges(repo_root: Path) -> list[ImportEdge]:
    source_root = repo_root / "src" / "ainrf"
    edges: set[tuple[str, str]] = set()
    for path in sorted(source_root.rglob("*.py")):
        source = _python_module(source_root, path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                target = _resolve_import_from(source, node)
                targets = [target] if target else []
            else:
                continue
            for target in targets:
                if target == "ainrf" or target.startswith("ainrf."):
                    edges.add((source, target))
    return [ImportEdge(source=source, target=target) for source, target in sorted(edges)]


def python_public_interface(repo_root: Path) -> list[InterfaceItem]:
    source_root = repo_root / "src" / "ainrf"
    items: list[InterfaceItem] = []
    for path in sorted(source_root.rglob("*.py")):
        module = _python_module(source_root, path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and not node.name.startswith("_"):
                items.append(
                    InterfaceItem(
                        module=module,
                        name=node.name,
                        kind="async-function"
                        if isinstance(node, ast.AsyncFunctionDef)
                        else "function",
                        signature=_function_signature(node),
                    )
                )
            elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                items.append(
                    InterfaceItem(module=module, name=node.name, kind="class", signature="")
                )
                for child in node.body:
                    if isinstance(
                        child, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ) and not child.name.startswith("_"):
                        items.append(
                            InterfaceItem(
                                module=module,
                                name=f"{node.name}.{child.name}",
                                kind=(
                                    "async-method"
                                    if isinstance(child, ast.AsyncFunctionDef)
                                    else "method"
                                ),
                                signature=_function_signature(child),
                            )
                        )
    return sorted(items, key=lambda item: (item["module"], item["name"], item["kind"]))


def import_cycles(edges: list[ImportEdge]) -> list[list[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    modules = {edge["source"] for edge in edges}
    for edge in edges:
        target = edge["target"]
        while target not in modules and "." in target:
            target = target.rsplit(".", 1)[0]
        if target in modules and target != edge["source"]:
            graph[edge["source"]].add(target)

    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(module: str) -> None:
        nonlocal index
        indices[module] = index
        lowlinks[module] = index
        index += 1
        stack.append(module)
        on_stack.add(module)
        for target in sorted(graph[module]):
            if target not in indices:
                visit(target)
                lowlinks[module] = min(lowlinks[module], lowlinks[target])
            elif target in on_stack:
                lowlinks[module] = min(lowlinks[module], indices[target])
        if lowlinks[module] == indices[module]:
            component: list[str] = []
            while True:
                target = stack.pop()
                on_stack.remove(target)
                component.append(target)
                if target == module:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for module in sorted(modules):
        if module not in indices:
            visit(module)
    return sorted(components)


def forbidden_backend_imports(edges: list[ImportEdge]) -> list[ImportEdge]:
    return [
        edge
        for edge in edges
        if not edge["source"].startswith("ainrf.api")
        and (edge["target"] == "ainrf.api" or edge["target"].startswith("ainrf.api."))
    ]


def frontend_layer_violations(repo_root: Path) -> list[FrontendViolation]:
    source_root = repo_root / "frontend" / "src"
    violations: list[FrontendViolation] = []
    for path in sorted(source_root.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or not path.is_file():
            continue
        source = path.relative_to(source_root).as_posix()
        source_layer = source.split("/", 1)[0]
        for specifier in _TS_IMPORT_RE.findall(path.read_text(encoding="utf-8")):
            target = _resolve_frontend_import(source_root, path, specifier)
            if target is None:
                continue
            target_layer = target.split("/", 1)[0]
            rule = _frontend_rule(source_layer, target_layer)
            if rule:
                violations.append(FrontendViolation(source=source, target=target, rule=rule))
    return sorted(violations, key=lambda item: (item["rule"], item["source"], item["target"]))


def openapi_inventory() -> tuple[dict[str, object], list[RouteItem]]:
    from ainrf.api.app import ROUTERS
    from ainrf.api.routes.metrics import create_metrics_router
    from ainrf.api.config import ApiConfig

    app = FastAPI()
    for router in ROUTERS:
        app.include_router(router)
        app.include_router(router, prefix="/v1")
        app.include_router(router, prefix="/api")
    app.include_router(
        create_metrics_router(ApiConfig(api_key_hashes=frozenset(), state_root=Path("/tmp")))
    )
    schema = app.openapi()
    routes: list[RouteItem] = []
    paths = schema.get("paths", {})
    assert isinstance(paths, dict)
    for path, operations in paths.items():
        assert isinstance(operations, dict)
        for method, operation in operations.items():
            if method.lower() not in {"delete", "get", "head", "options", "patch", "post", "put"}:
                continue
            assert isinstance(operation, dict)
            routes.append(
                RouteItem(
                    method=method.upper(),
                    path=str(path),
                    name=str(operation.get("operationId", "")),
                    deprecated=bool(operation.get("deprecated", False)),
                )
            )
    return schema, sorted(routes, key=lambda item: (item["path"], item["method"]))


def _python_module(source_root: Path, path: Path) -> str:
    relative = path.relative_to(source_root)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(["ainrf", *parts])


def _resolve_import_from(source: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package = source.split(".")[:-1]
    if node.level > len(package):
        return None
    base = package[: len(package) - node.level + 1]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    arguments = [argument.arg for argument in node.args.posonlyargs]
    if node.args.posonlyargs:
        arguments.append("/")
    arguments.extend(argument.arg for argument in node.args.args)
    if node.args.vararg:
        arguments.append(f"*{node.args.vararg.arg}")
    elif node.args.kwonlyargs:
        arguments.append("*")
    arguments.extend(argument.arg for argument in node.args.kwonlyargs)
    if node.args.kwarg:
        arguments.append(f"**{node.args.kwarg.arg}")
    return f"({','.join(arguments)})"


def _resolve_frontend_import(source_root: Path, source: Path, specifier: str) -> str | None:
    if specifier.startswith("@/"):
        relative = specifier[2:]
    elif specifier == "@design-system":
        relative = "design-system"
    elif specifier.startswith("@design-system/"):
        relative = f"design-system/{specifier.removeprefix('@design-system/')}"
    elif specifier.startswith("@features/"):
        relative = f"features/{specifier.removeprefix('@features/')}"
    elif specifier.startswith("@shared/"):
        relative = f"shared/{specifier.removeprefix('@shared/')}"
    elif specifier.startswith("."):
        relative = (
            (source.parent / specifier).resolve().relative_to(source_root.resolve()).as_posix()
        )
    else:
        return None
    return relative.removesuffix(".tsx").removesuffix(".ts")


def _frontend_rule(source_layer: str, target_layer: str) -> str | None:
    if source_layer == "shared" and target_layer in {
        "app",
        "components",
        "design-system",
        "features",
        "pages",
    }:
        return "shared-must-not-depend-upward"
    if source_layer == "design-system" and target_layer in {
        "app",
        "components",
        "features",
        "pages",
    }:
        return "design-system-must-not-depend-on-product"
    if source_layer == "features" and target_layer in {"app", "pages"}:
        return "features-must-not-depend-on-composition"
    if source_layer == "components" and target_layer == "features":
        return "components-features-cycle-risk"
    return None
