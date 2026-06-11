"""Tests for tools/capture_filter.py — anti-self-poisoning capture filter."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import capture_filter as cf  # noqa: E402


def test_flags_env_failures():
    assert "env_failure" in cf.screen("pip install failed: No module named torch")
    assert "env_failure" in cf.screen("./run.sh: command not found")
    assert "env_failure" in cf.screen("Traceback ... ModuleNotFoundError: numpy")
    assert "env_failure" in cf.screen("open('x'): No such file or directory")


def test_flags_transient_errors():
    assert "transient_error" in cf.screen("got HTTP 429 rate limit, retried and it worked")
    assert "transient_error" in cf.screen("RuntimeError: CUDA out of memory")
    assert "transient_error" in cf.screen("connection refused, server was rebooting")


def test_flags_negative_tool_claims():
    # Only ARIS-infra-QUALIFIED phrasing flags (bare model names do not).
    for s in [
        "the codex mcp can't handle files over 2k lines",
        "the gemini mcp is broken for image review",
        "the codex reviewer cannot see the results directory",
        "don't use the oracle reviewer, it always fails",
        "manual-review doesn't work in headless mode",
        "wandb is down again",
        "the codex cli always hangs on large prompts",
    ]:
        assert "negative_tool_claim" in cf.screen(s), f"missed: {s!r}"


def test_does_not_flag_legitimate_research_findings():
    """FP-critical: research claims about a MODEL/METHOD — incl. ones NAMED like ARIS
    tools (Gemini/Codex/Oracle/GPT-5 as research subjects) — must NOT flag."""
    clean = [
        "The model can't generalize to out-of-distribution data.",
        "Our method fails on long sequences beyond 4k tokens.",
        "The diffusion model is unstable at high learning rates.",
        "The baseline cannot exceed 70% accuracy on this split.",
        "We find that attention does not help on this task.",
        "Idea: test whether contrastive pretraining improves OOD robustness.",
        "Claim: method X beats baseline Y by 4 points on COCO.",
        # codex's flagged research phrasings — bare model/infra names must NOT flag:
        "Oracle cannot improve accuracy when the proxy labels are noisy.",
        "Gemini cannot solve the compositional reasoning benchmark zero-shot.",
        "GPT-5.5 cannot reliably prove the theorem without symbolic verification.",
        "Codex does not pass the HumanEval-style variant with hidden state.",
        "The API does not expose gradients, so the method uses score estimates.",
        "The server cannot support synchronous aggregation under straggler delays.",
        "The GPU cannot fit the full batch without activation checkpointing.",
        "The tool does not assume access to ground-truth labels.",
        "The reviewer cannot verify the proof because Lemma 2 is underspecified.",
        "The CLI does not support streaming inputs in the evaluated baseline.",
    ]
    for s in clean:
        assert cf.screen(s) == [], f"false positive on research text: {s!r} -> {cf.screen(s)}"


def test_clean_returns_empty_and_dedups():
    assert cf.screen("") == []
    assert cf.screen("A solid, well-scoped research idea about scaling laws.") == []
    # multiple hits of the same class dedup to one reason
    r = cf.screen("No module named torch; also No such file or directory")
    assert r.count("env_failure") == 1


def test_reason_detail_nonempty():
    for reason in ("env_failure", "transient_error", "negative_tool_claim"):
        assert reason in cf.reason_detail(reason) or len(cf.reason_detail(reason)) > 10


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
