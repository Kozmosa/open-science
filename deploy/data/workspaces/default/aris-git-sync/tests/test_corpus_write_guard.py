"""Tests for templates/claude-hooks/corpus_write_guard.py — the PreToolUse guard that
denies Bash writes to the skill corpus. The safety property: it must BLOCK every casual
shell-write to a corpus path, and must NOT block reads / analysis / writes to .aris/."""

import json
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "templates" / "claude-hooks" / "corpus_write_guard.py"


def _run(tool_name, command):
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"command": command}})
    p = subprocess.run([sys.executable, str(GUARD)], input=payload,
                       capture_output=True, text=True)
    return p.returncode  # 2 = blocked, 0 = allowed


def test_blocks_corpus_writes():
    blocked = [
        "cat x > skills/foo/SKILL.md",
        "echo hi >> shared-references/acceptance-gate.md",
        "tee tools/provenance.py < /tmp/x",
        "sed -i 's/a/b/' skills/meta-optimize/SKILL.md",
        "cp /tmp/evil.md skills/foo/SKILL.md",
        "mv /tmp/x shared-references/foo.md",
        "python3 -c \"open('skills/foo/SKILL.md','w').write('x')\"",
        "dd if=/dev/zero of=tools/x.py",
        "echo x > ./skills/foo/SKILL.md",
        "touch skills/foo/NEW.md",
        "python3 -c \"from pathlib import Path; Path('skills/foo/SKILL.md').write_text('x')\"",
    ]
    for cmd in blocked:
        assert _run("Bash", cmd) == 2, f"should have BLOCKED: {cmd!r}"


def test_allows_reads_and_aris_writes():
    allowed = [
        "grep -c skill_invoke .aris/meta/events.jsonl",
        "wc -l .aris/meta/events.jsonl",
        "cat skills/meta-optimize/SKILL.md",            # READ a corpus file is fine
        "ls skills/",
        "echo report > .aris/meta/REPORT.md",            # write to scratch is fine
        "cat diff > .aris/meta/pending/01.diff",
        "python3 tools/provenance.py read skills/foo",   # read-only helper
        "git diff skills/",                              # read-only git
        "sed -n '1,5p' skills/foo/SKILL.md",             # sed WITHOUT -i = read
    ]
    for cmd in allowed:
        assert _run("Bash", cmd) == 0, f"should have ALLOWED: {cmd!r}"


def test_ignores_non_bash_tools():
    # Write/Edit are the LEGIT corpus-mutation path (for /meta-apply, for humans) — the
    # guard only governs Bash, so it must pass non-Bash tools straight through.
    assert _run("Write", "skills/foo/SKILL.md") == 0
    assert _run("Edit", "skills/foo/SKILL.md") == 0


def test_malformed_input_fails_open():
    p = subprocess.run([sys.executable, str(GUARD)], input="not json",
                       capture_output=True, text=True)
    assert p.returncode == 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS {t.__name__}"); passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {t.__name__}: {e}"); failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
