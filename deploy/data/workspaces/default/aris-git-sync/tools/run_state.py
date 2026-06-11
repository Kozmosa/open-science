#!/usr/bin/env python3
"""Resumable run-state for ARIS multi-phase workflows.

A long ARIS workflow (research-pipeline, paper-writing, idea-discovery) can fail
mid-run, and today there is no record of *which phase* already finished — a
resume restarts from scratch. This helper models a run as an ordered list of
phases with status, so resume can pick up where it left off.

The ARIS increment over a naive "resume = reopen" (which is all Hermes does):
the phase status enum SPLITS execution from acceptance —

    done      executor (Claude) finished writing the artifact.
              EXECUTION-COMPLETENESS — a safe SAME-MODEL self-report.
    accepted  a CROSS-MODEL reviewer (codex/gemini) OR a deterministic verifier
              returned a positive verdict, recorded with a verdict id + reviewer.
    skipped   the phase does not apply to this run (e.g. paper-writing when
              AUTO_WRITE=false) — a deterministic config decision, terminal.

Resume resolves FORWARD to the first phase that is NOT terminal ({accepted,
skipped}) — never the first non-`done`. So a phase the executor self-considered
"done" but that crashed before its cross-model audit is RE-VALIDATED on resume,
never silently skipped. Acceptance-gate rule made operational: a loop can DRIVE
resume, it cannot ACQUIT a phase past itself.

Structurally enforced: `set` may only write pending/running/done/failed/skipped;
only `accept` writes `accepted`, and it REQUIRES a verdict id + reviewer AND that
the phase already be `done` (use --force to override) — you cannot acquit a phase
that never ran, nor mark one accepted without recording who acquitted it.

State at ``<root>/.aris/runs/<run_id>.json`` (file-based, no DB). Single-writer
contract (one orchestrator per run); a best-effort flock guards against a
concurrent resumer. See shared-references/resumable-runs.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

try:
    import fcntl  # POSIX
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore

EXECUTOR_STATUSES = {"pending", "running", "done", "failed", "skipped"}
TERMINAL_STATUSES = {"accepted", "skipped"}  # resume skips these
ALL_STATUSES = EXECUTOR_STATUSES | {"accepted"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_path(root: str, run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_.")
    if not safe or safe != run_id or run_id in (".", ".."):
        raise ValueError(f"invalid run_id {run_id!r} (use [A-Za-z0-9-_.])")
    return Path(root) / ".aris" / "runs" / f"{run_id}.json"


@contextmanager
def _lock(root: str, run_id: str) -> Iterator[None]:
    """Best-effort advisory lock for the load-modify-save of one run.

    Single-writer is the contract; this only guards against a stray concurrent
    resumer. No-op where fcntl is unavailable.
    """
    p = _run_path(root, run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        yield
        return
    lock_path = p.with_suffix(".lock")
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def _load(root: str, run_id: str) -> dict:
    p = _run_path(root, run_id)
    if not p.exists():
        raise FileNotFoundError(f"no run state at {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _save(root: str, run_id: str, state: dict) -> None:
    p = _run_path(root, run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    state["updated"] = _now()
    # Unique temp in the same dir → atomic replace, no shared-tmp clobber.
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{run_id}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        finally:
            raise


def start_run(root: str, run_id: str, phases: list[str]) -> dict:
    """Create a run with ordered phases, all `pending` (idempotent: won't clobber)."""
    with _lock(root, run_id):
        if _run_path(root, run_id).exists():
            return _load(root, run_id)
        state = {
            "run_id": run_id,
            "created": _now(),
            "updated": _now(),
            "phases": [{"phase": ph, "status": "pending", "artifact": None,
                        "verdict_id": None, "reviewer": None, "updated": _now()} for ph in phases],
        }
        _save(root, run_id, state)
        return state


def _find_phase(state: dict, phase: str) -> dict:
    for ph in state["phases"]:
        if ph["phase"] == phase:
            return ph
    raise KeyError(f"phase {phase!r} not in run (have: {[p['phase'] for p in state['phases']]})")


def set_status(root: str, run_id: str, phase: str, status: str, artifact: Optional[str] = None) -> dict:
    """Executor-side status. running/done/failed/skipped — NOT accepted (use accept())."""
    if status not in EXECUTOR_STATUSES:
        raise ValueError(
            f"set_status may only write {sorted(EXECUTOR_STATUSES)}; "
            f"'accepted' is reserved for accept() (needs a cross-model/deterministic verdict).")
    with _lock(root, run_id):
        state = _load(root, run_id)
        ph = _find_phase(state, phase)
        ph["status"] = status
        if artifact is not None:
            ph["artifact"] = artifact
        ph["updated"] = _now()
        _save(root, run_id, state)
        return state


def accept(root: str, run_id: str, phase: str, verdict_id: str, reviewer: str, force: bool = False) -> dict:
    """Mark a phase `accepted` — REQUIRES a recorded verdict id + reviewer, and
    (unless force) that the phase already be `done`.

    Call ONLY from a cross-model reviewer verdict (codex/gemini) or a deterministic
    verifier (verify_papers.py, verify_paper_audits.sh, a passing test, exit 0).
    The executor (Claude) must never call this on its own self-report.

    `verdict_id` should be a durable handle: the reviewer thread/trace id, or the
    path/sha of the verifier's report — not just a label.
    """
    if not verdict_id or not reviewer:
        raise ValueError("accept requires a non-empty verdict_id AND reviewer — "
                         "a phase cannot be accepted without recording who acquitted it.")
    with _lock(root, run_id):
        state = _load(root, run_id)
        ph = _find_phase(state, phase)
        if not force and ph["status"] not in ("done", "accepted"):
            raise ValueError(
                f"phase {phase!r} is {ph['status']!r}, not 'done' — cannot accept a phase that "
                f"has not completed execution. Set it 'done' first, or pass force=True.")
        # Self-acquittal tripwire: the cross-model invariant means the reviewer
        # family must differ from the executor (Claude). A reviewer recorded as a
        # Claude model is almost certainly self-acquittal — warn loudly.
        low = reviewer.lower()
        if low.startswith("claude") or "claude-opus" in low or "claude-sonnet" in low:
            print(f"⚠️  accept: reviewer={reviewer!r} looks like the executor family (Claude). "
                  f"A cross-model verdict must come from a DIFFERENT family (codex/gemini) or a "
                  f"deterministic verifier. Recording anyway, but this is likely self-acquittal.",
                  file=sys.stderr)
        ph["status"] = "accepted"
        ph["verdict_id"] = verdict_id
        ph["reviewer"] = reviewer
        ph["updated"] = _now()
        _save(root, run_id, state)
        return state


def resume_point(root: str, run_id: str) -> Optional[dict]:
    """First phase whose status is NOT terminal ({accepted, skipped}) — the resume
    target — or None if the run is complete.

    A `done`-but-not-`accepted` phase IS a resume target: its cross-model audit is
    still owed and must run before the next phase proceeds.
    """
    state = _load(root, run_id)
    for ph in state["phases"]:
        if ph["status"] not in TERMINAL_STATUSES:
            return ph
    return None


def _print_status(state: dict) -> None:
    print(f"run {state['run_id']}  (updated {state.get('updated', '?')})")
    glyph = {"pending": "·", "running": "▶", "done": "✓(unaccepted)",
             "failed": "✗", "accepted": "✅", "skipped": "⊘(skipped)"}
    for ph in state["phases"]:
        line = f"  {glyph.get(ph['status'], '?'):>14}  {ph['phase']}  [{ph['status']}]"
        if ph["status"] == "accepted":
            line += f"  ← {ph['reviewer']} / {ph['verdict_id']}"
        elif ph["artifact"]:
            line += f"  → {ph['artifact']}"
        print(line)
    rp = next((p for p in state["phases"] if p["status"] not in TERMINAL_STATUSES), None)
    print(f"  resume → {rp['phase'] if rp else 'COMPLETE (all phases accepted/skipped)'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="ARIS resumable run-state (done vs accepted).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("root"); s.add_argument("run_id"); s.add_argument("--phases", required=True, help="comma-separated phase names")
    s = sub.add_parser("set"); s.add_argument("root"); s.add_argument("run_id"); s.add_argument("phase"); s.add_argument("status", choices=sorted(EXECUTOR_STATUSES)); s.add_argument("--artifact")
    s = sub.add_parser("accept"); s.add_argument("root"); s.add_argument("run_id"); s.add_argument("phase"); s.add_argument("--verdict-id", required=True); s.add_argument("--reviewer", required=True); s.add_argument("--force", action="store_true")
    s = sub.add_parser("resume"); s.add_argument("root"); s.add_argument("run_id")
    s = sub.add_parser("status"); s.add_argument("root"); s.add_argument("run_id")
    s = sub.add_parser("list"); s.add_argument("root")
    a = ap.parse_args()

    try:
        if a.cmd == "start":
            _print_status(start_run(a.root, a.run_id, [p.strip() for p in a.phases.split(",") if p.strip()]))
        elif a.cmd == "set":
            _print_status(set_status(a.root, a.run_id, a.phase, a.status, a.artifact))
        elif a.cmd == "accept":
            _print_status(accept(a.root, a.run_id, a.phase, a.verdict_id, a.reviewer, force=a.force))
        elif a.cmd == "resume":
            rp = resume_point(a.root, a.run_id)
            if rp is None:
                print("COMPLETE"); return 0
            print(rp["phase"])  # machine-readable: the resume target phase name
            print(json.dumps(rp), file=sys.stderr)
        elif a.cmd == "status":
            _print_status(_load(a.root, a.run_id))
        elif a.cmd == "list":
            d = Path(a.root) / ".aris" / "runs"
            for f in sorted(d.glob("*.json")) if d.exists() else []:
                print(f.stem)
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr); return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
