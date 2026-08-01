from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.dependency_direction import find_dependency_violations

pytestmark = [pytest.mark.unit]


def _write(source_root: Path, module: str, source: str) -> None:
    path = source_root.joinpath(*module.split(".")).with_suffix(".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


@pytest.mark.parametrize(
    "source",
    [
        "import ainrf.api.app\n",
        "from ainrf.api import create_app\n",
        "import importlib\nimportlib.import_module('ainrf.api.app')\n",
        "import importlib\nimportlib.import_module('ainrf' + '.api.app')\n",
        "__import__('ainrf.api.app')\n",
        "APP = 'ainrf.api.server:create_development_app'\n",
        "COMMAND = ['python', '-m', 'ainrf.api.server']\n",
    ],
)
def test_guard_rejects_every_non_adapter_entry_form(tmp_path: Path, source: str) -> None:
    source_root = tmp_path
    _write(source_root, "ainrf.runtime", source)

    violations = find_dependency_violations(source_root)

    assert violations


def test_guard_allows_http_adapter_internal_dependencies(tmp_path: Path) -> None:
    source_root = tmp_path
    _write(source_root, "ainrf.api.cli", "from ainrf.api.server import run_http_server\n")
    _write(source_root, "ainrf.api.server", "APP = 'ainrf.api.app:create_app'\n")

    assert find_dependency_violations(source_root) == ()


def test_guard_rejects_product_import_cycles(tmp_path: Path) -> None:
    source_root = tmp_path
    _write(source_root, "ainrf.alpha", "from ainrf import beta\n")
    _write(source_root, "ainrf.beta", "from ainrf import alpha\n")

    violations = find_dependency_violations(source_root)

    assert any("product import cycle" in violation.message for violation in violations)


def test_repository_product_graph_obeys_dependency_direction() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    assert find_dependency_violations(repo_root / "src") == ()
