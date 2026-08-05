from __future__ import annotations

from pathlib import Path
import re


_CLAUDE_IMPORT_STUB = "@PROJECT_BASIS.md\n@AGENTS.md\n"
_GOVERNED_MARKDOWN = (
    Path("AGENTS.md"),
    Path("docs/documentation-governance.md"),
    Path("frontend/README.md"),
    Path("src/ainrf/README.md"),
)
_REQUIRED_PATHS = (
    Path("PROJECT_BASIS.md"),
    Path("AGENTS.md"),
    Path("CLAUDE.md"),
    Path("deploy/config/CLAUDE.md"),
    Path("deploy/config/entrypoint.py"),
    Path("src/ainrf/harness_engine/engines/agent_sdk.py"),
    Path("frontend/src/generated/transport/README.md"),
    Path(".rules/deployment.md"),
    Path(".rules/frontend-and-testing.md"),
    Path(".rules/git-workflow.md"),
    Path(".rules/multi-tenant-permissions.md"),
    Path(".rules/staging-environment.md"),
    Path(".rules/worktree-working-guide.md"),
)
_REQUIRED_AGENTS_HEADINGS = (
    "## Authority and Conflict Handling",
    "## Working Principles",
    "## Context Routing",
    "## Generated Artifacts",
    "## Agent Instruction Planes",
)
_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _read(repo_root: Path, relative_path: Path) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


def _check_local_links(repo_root: Path, relative_path: Path, text: str) -> list[str]:
    violations: list[str] = []
    for raw_target in _MARKDOWN_LINK.findall(text):
        target = raw_target.strip().strip("<>")
        if target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        target_without_anchor = target.split("#", maxsplit=1)[0]
        if not target_without_anchor:
            continue
        resolved = (repo_root / relative_path.parent / target_without_anchor).resolve()
        try:
            resolved.relative_to(repo_root.resolve())
        except ValueError:
            violations.append(f"{relative_path}: local link escapes repository: {target}")
            continue
        if not resolved.exists():
            violations.append(f"{relative_path}: broken local link: {target}")
    return violations


def find_instruction_violations(repo_root: Path) -> list[str]:
    violations: list[str] = []

    for relative_path in _REQUIRED_PATHS:
        if not (repo_root / relative_path).is_file():
            violations.append(f"missing required instruction path: {relative_path}")

    if violations:
        return violations

    claude_text = _read(repo_root, Path("CLAUDE.md"))
    if claude_text != _CLAUDE_IMPORT_STUB:
        violations.append(
            "CLAUDE.md must remain the exact @PROJECT_BASIS.md + @AGENTS.md import stub"
        )

    project_basis = _read(repo_root, Path("PROJECT_BASIS.md"))
    if "任何 Agent 都不得修改本文件" not in project_basis:
        violations.append("PROJECT_BASIS.md must retain its user-only modification guard")

    agents_text = _read(repo_root, Path("AGENTS.md"))
    for heading in _REQUIRED_AGENTS_HEADINGS:
        if heading not in agents_text:
            violations.append(f"AGENTS.md is missing required section: {heading}")
    for retired_reference in ("src/ainrf/tasks/", "src/ainrf/task_harness/"):
        if retired_reference in agents_text:
            violations.append(f"AGENTS.md references retired path: {retired_reference}")

    runtime_prompt = _read(repo_root, Path("deploy/config/CLAUDE.md"))
    if "ALL Claude Code sessions spawned by the OpenScience" not in runtime_prompt:
        violations.append("runtime operator CLAUDE.md no longer declares its session scope")

    entrypoint = _read(repo_root, Path("deploy/config/entrypoint.py"))
    if 'shutil.copyfile(src, out_dir / "CLAUDE.md")' not in entrypoint:
        violations.append("container entrypoint no longer installs the runtime CLAUDE.md")

    agent_sdk = _read(repo_root, Path("src/ainrf/harness_engine/engines/agent_sdk.py"))
    if "_copy_user_claude_md(config_tmp)" not in agent_sdk:
        violations.append("Agent SDK no longer carries runtime CLAUDE.md into its config")

    backend_readme = _read(repo_root, Path("src/ainrf/README.md"))
    if "Backend 配置使用 `AINRF_*`" not in backend_readme:
        violations.append("src/ainrf/README.md must state the canonical AINRF_* config namespace")
    for retired_reference in ("src/ainrf/tasks/", "src/ainrf/task_harness/"):
        if retired_reference in backend_readme:
            violations.append(f"src/ainrf/README.md references retired path: {retired_reference}")

    for relative_path in _GOVERNED_MARKDOWN:
        text = _read(repo_root, relative_path)
        violations.extend(_check_local_links(repo_root, relative_path, text))

    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    violations = find_instruction_violations(repo_root)
    for violation in violations:
        print(f"agent-instructions: {violation}")
    if violations:
        return 1
    print("agent-instructions: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
