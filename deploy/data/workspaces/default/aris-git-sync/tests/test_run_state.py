"""Tests for tools/run_state.py — resumable run-state with the done/accepted split."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import run_state as rs  # noqa: E402

PHASES = ["W1", "W1.5", "W2", "W3"]


def _tmp():
    return tempfile.TemporaryDirectory()


def test_start_creates_pending_phases():
    with _tmp() as d:
        st = rs.start_run(d, "run-a", PHASES)
        assert [p["phase"] for p in st["phases"]] == PHASES
        assert all(p["status"] == "pending" for p in st["phases"])
        # resume of a fresh run points at the first phase
        assert rs.resume_point(d, "run-a")["phase"] == "W1"


def test_start_is_idempotent():
    with _tmp() as d:
        rs.start_run(d, "run-a", PHASES)
        rs.set_status(d, "run-a", "W1", "done")
        again = rs.start_run(d, "run-a", PHASES)  # must NOT clobber progress
        assert rs._find_phase(again, "W1")["status"] == "done"


def test_set_status_cannot_write_accepted():
    with _tmp() as d:
        rs.start_run(d, "run-a", PHASES)
        for ok in ("running", "done", "failed"):
            rs.set_status(d, "run-a", "W1", ok)
        try:
            rs.set_status(d, "run-a", "W1", "accepted")
            raised = False
        except ValueError:
            raised = True
        assert raised, "set_status must refuse to write 'accepted'"


def test_accept_requires_verdict_and_reviewer():
    with _tmp() as d:
        rs.start_run(d, "run-a", PHASES)
        for vid, rev in (("", "codex"), ("codex:1", ""), ("", "")):
            try:
                rs.accept(d, "run-a", "W1", vid, rev)
                raised = False
            except ValueError:
                raised = True
            assert raised, f"accept must require both verdict_id and reviewer (got {vid!r},{rev!r})"
        rs.set_status(d, "run-a", "W1", "done")  # accept now requires the phase be done
        st = rs.accept(d, "run-a", "W1", "codex:019e", "codex-gpt-5.5")
        ph = rs._find_phase(st, "W1")
        assert ph["status"] == "accepted" and ph["verdict_id"] == "codex:019e" and ph["reviewer"] == "codex-gpt-5.5"


def test_accept_requires_phase_done():
    with _tmp() as d:
        rs.start_run(d, "run-a", PHASES)
        # Cannot accept a phase that never ran (still pending).
        try:
            rs.accept(d, "run-a", "W1", "v:1", "codex")
            raised = False
        except ValueError:
            raised = True
        assert raised, "accept must refuse a non-done phase without force"
        # --force overrides (e.g. a purely deterministic phase with no executor step).
        rs.accept(d, "run-a", "W1", "v:1", "deterministic:x", force=True)
        assert rs._find_phase(rs._load(d, "run-a"), "W1")["status"] == "accepted"
        # The normal path: done → accept.
        rs.set_status(d, "run-a", "W2", "done")
        rs.accept(d, "run-a", "W2", "v:2", "codex")
        assert rs._find_phase(rs._load(d, "run-a"), "W2")["status"] == "accepted"


def test_skipped_is_terminal_for_resume():
    with _tmp() as d:
        rs.start_run(d, "run-a", PHASES)
        rs.set_status(d, "run-a", "W1", "done"); rs.accept(d, "run-a", "W1", "v", "codex")
        rs.set_status(d, "run-a", "W1.5", "skipped")   # phase doesn't apply to this run
        rs.set_status(d, "run-a", "W2", "done"); rs.accept(d, "run-a", "W2", "v", "codex")
        rs.set_status(d, "run-a", "W3", "skipped")
        # Only accepted/skipped are terminal → all terminal → resume COMPLETE.
        assert rs.resume_point(d, "run-a") is None


def test_resume_skips_only_accepted_not_done():
    """The load-bearing invariant: a `done`-but-unaccepted phase is STILL a resume target."""
    with _tmp() as d:
        rs.start_run(d, "run-a", PHASES)
        rs.set_status(d, "run-a", "W1", "done")
        rs.accept(d, "run-a", "W1", "codex:1", "codex")     # W1 accepted
        rs.set_status(d, "run-a", "W1.5", "done")           # W1.5 done but NOT accepted (crashed before audit)
        # resume must return W1.5 (first non-accepted), NOT W2 — done != accepted.
        assert rs.resume_point(d, "run-a")["phase"] == "W1.5"
        # accept W1.5, then resume advances to W2 (still pending).
        rs.accept(d, "run-a", "W1.5", "codex:2", "codex")
        assert rs.resume_point(d, "run-a")["phase"] == "W2"


def test_resume_none_when_all_accepted():
    with _tmp() as d:
        rs.start_run(d, "run-a", PHASES)
        for ph in PHASES:
            rs.set_status(d, "run-a", ph, "done")
            rs.accept(d, "run-a", ph, f"v:{ph}", "deterministic:test")
        assert rs.resume_point(d, "run-a") is None


def test_invalid_run_id_rejected():
    with _tmp() as d:
        for bad in ("../escape", "a/b", "a b", "a;rm"):
            try:
                rs.start_run(d, bad, PHASES)
                raised = False
            except ValueError:
                raised = True
            assert raised, f"invalid run_id {bad!r} must be rejected"


def test_unknown_phase_raises():
    with _tmp() as d:
        rs.start_run(d, "run-a", PHASES)
        try:
            rs.set_status(d, "run-a", "W9", "done")
            raised = False
        except KeyError:
            raised = True
        assert raised


def test_state_is_valid_json_on_disk():
    import json
    with _tmp() as d:
        rs.start_run(d, "run-a", PHASES)
        rs.set_status(d, "run-a", "W1", "done", artifact="x/y.md")
        p = Path(d) / ".aris" / "runs" / "run-a.json"
        state = json.loads(p.read_text())  # must parse
        assert rs._find_phase(state, "W1")["artifact"] == "x/y.md"


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
