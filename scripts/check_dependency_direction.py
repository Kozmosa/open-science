from __future__ import annotations

from pathlib import Path

from ainrf.dependency_direction import find_dependency_violations


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    violations = find_dependency_violations(repo_root / "src")
    for violation in violations:
        path = violation.path.relative_to(repo_root)
        print(f"{path}:{violation.line}: {violation.message}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
