"""Tests for tools/evidence_check.py — deterministic evidence pre-check."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import evidence_check as ec  # noqa: E402


def _write(d, rel, text):
    p = Path(d) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_verified_string_value():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "results/eval.md", "Our method reaches SOTA on COCO with a 4-point gain.")
        assert ec.check_claim("4-point gain", "results/eval.md", d)["status"] == "verified"
        assert ec.check_claim("SOTA on COCO", "results/eval.md", d)["status"] == "verified"


def test_numeric_equality_matches_trailing_zeros():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "r.json", '{"mAP": 73.20, "acc": "0.912%"}')
        assert ec.check_claim("73.2", "r.json", d)["status"] == "verified"     # 73.2 == 73.20
        assert ec.check_claim("0.912%", "r.json", d)["status"] == "verified"


def test_bare_number_does_not_false_match_a_different_number():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "r.txt", "baseline accuracy was 73.5 percent")
        # "73" must NOT be reported verified by substring of "73.5".
        assert ec.check_claim("73", "r.txt", d)["status"] == "value_not_found"
        # but the real number is found.
        assert ec.check_claim("73.5", "r.txt", d)["status"] == "verified"


def test_path_missing():
    with tempfile.TemporaryDirectory() as d:
        assert ec.check_claim("73.2", "results/nope.json", d)["status"] == "path_missing"


def test_value_not_found():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "r.txt", "the accuracy was 50.0")
        assert ec.check_claim("99.9", "r.txt", d)["status"] == "value_not_found"


def test_glob_source():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "results/seed1/metrics.json", '{"f1": 0.88}')
        _write(d, "results/seed2/metrics.json", '{"f1": 0.91}')
        assert ec.check_claim("0.91", "results/*/metrics.json", d)["status"] == "verified"
        assert ec.check_claim("0.77", "results/*/metrics.json", d)["status"] == "value_not_found"


def test_batch_summary_and_unparseable():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "r.json", '{"x": 12.5}')
        out = ec.check_batch([
            {"id": "c1", "value": "12.5", "source": "r.json"},   # verified
            {"id": "c2", "value": "99",   "source": "r.json"},   # value_not_found
            {"id": "c3", "value": "1",    "source": "gone.json"},# path_missing
            {"id": "c4"},                                        # unparseable
        ], d)
        statuses = {r["id"]: r["status"] for r in out["results"]}
        assert statuses == {"c1": "verified", "c2": "value_not_found",
                            "c3": "path_missing", "c4": "unparseable"}
        assert out["summary"]["verified"] == 1


def test_verified_means_exists_not_correct():
    """A verified result asserts the evidence EXISTS, never that the claim holds."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "r.txt", "random_seed = 42")
        # 42 exists in the file, so it 'verifies' — but whether 42 SUPPORTS any
        # claim is the jury's call, not this gate's. The status is about existence.
        assert ec.check_claim("42", "r.txt", d)["status"] == "verified"


def test_no_false_verified_adversarial():
    """Every fabricated value codex flagged must NOT be 'verified'; real ones still must."""
    cases = [
        # (value, file_text, must_verify)
        ("1",                 "decay = 1e-5",              False),  # 1e-5 is one token, no spurious "1"
        ("-5",                "lr range 1-5 and 1e-5",     False),  # no spurious negative token
        ("1e-5",              "value 11e-5 here",          False),  # not a substring of 11e-5
        ("5%",                "seed = 5",                  False),  # percent must match percent
        ("50",                "we use resnet50",           False),  # not embedded in a word
        ("5",                 "abc5def token",             False),  # not embedded in a word
        ("1.0000000001",      "x = 1.0000000002",          False),  # exact decimal, no float epsilon
        ("10000000000000001", "n=10000000000000000",       False),  # big-int exactness
        ("1",                 "n = 1,000",                 False),  # thousands grouping not split
        ("0",                 "n = 1,000",                 False),
        ("234.5",             "loss = 1,234.5",            False),  # grouped number whole-token
        ("1",                 "count 1 000 items",         False),  # space grouping not split
        (".5",                "acc = 10.5",                False),  # leading-decimal not substring
        ("1.",                "x = 11.",                   False),  # trailing-decimal not substring
        ("1",                 "ratio 1/2",                 False),  # fraction not split
        ("2",                 "ratio 1/2",                 False),
        ("2026",              "run date 2026-05-30",       False),  # date components not split
        ("5",                 "run date 2026-05-30",       False),
        ("30",                "run date 2026-05-30",       False),
        ("12",                "at 12:30 utc",              False),  # time not split
        ("1.2",               "version 1.2.3",             False),  # version not split
        ("1",                 "euro 1.000,5 eur",          False),  # locale decimal not split
        ("73.2",              '{"mAP": 73.20}',            True),   # trailing-zero equality
        ("1e-5",              "decay = 1e-5",              True),   # sci-notation equality
        ("5%",                "dropout = 5%",              True),   # percent matches percent
        ("0",                 "bias = 0",                  True),   # zero is a real value
        ("1,000",             "n = 1,000",                 True),   # grouped value ≡ grouped token
        ("1000",              "n = 1,000",                 True),   # 1000 ≡ 1,000 (numeric equality)
        (".5",                "acc = 0.5",                 True),   # .5 ≡ 0.5
        # normal-sentence positives (must NOT be over-rejected by the boundaries):
        ("73.2",              "mAP: 73.2 on the test set", True),   # colon-space before is fine
        ("0.91",              "f1 = 0.91, acc = 0.93",     True),   # trailing comma-space is sentence
        ("100",               "(100 epochs)",              True),   # parens are a good boundary
    ]
    with tempfile.TemporaryDirectory() as d:
        for value, text, want in cases:
            _write(d, "f.txt", text)
            got = ec.check_claim(value, "f.txt", d)["status"] == "verified"
            assert got == want, f"{value!r} vs {text!r}: verified={got}, want {want}"


def test_no_false_verified_unicode_delimiters():
    """Unicode minus/dash/fullwidth/space constructs must NOT yield a false verified."""
    cases = [
        ("5.2", "loss −5.2 here",   False),  # U+2212 MINUS, not [+-] sign
        ("5",   "delta −5",          False),
        ("20",  "range 10–20 ok",   False),  # U+2013 EN DASH
        ("20",  "range 10—20 ok",   False),  # U+2014 EM DASH
        ("1",   "n 1 234.5 x",      False),  # U+2009 THIN SPACE grouping
        ("234.5", "n 1 234.5 x",    False),
        ("1",   "id 1，000 x",        False),  # U+FF0C FULLWIDTH COMMA
        ("1",   "t 1：2 x",           False),  # U+FF1A FULLWIDTH COLON
        ("2",   "t 1／2 x",           False),  # U+FF0F FULLWIDTH SLASH
        ("1",   "n 1 000 x",         False),  # U+00A0 NBSP grouping
    ]
    with tempfile.TemporaryDirectory() as d:
        for value, text, want in cases:
            _write(d, "f.txt", text)
            got = ec.check_claim(value, "f.txt", d)["status"] == "verified"
            assert got == want, f"{value!r} vs {text!r}: verified={got}, want {want}"


def test_no_false_verified_multiwhitespace_grouping():
    """Whitespace grouping with 1+ whitespace of any kind must fail closed."""
    cases = [
        ("1",   "n 1 234 x",     False),  # single space
        ("234", "n 1 234 x",     False),
        ("1",   "n 1  234 x",    False),  # two spaces
        ("234", "n 1  234 x",    False),
        ("1",   "n 1 \t 234 x",  False),  # mixed run (space tab space)
        ("1",   "n 1\n234 x",    False),  # newline
        # not grouping (not exactly 3 digits) → the standalone number still verifies:
        ("2345", "n 1  2345 x",  True),
        ("1",   "got 1 and 50",  True),   # plain separate numbers, not grouping
    ]
    with tempfile.TemporaryDirectory() as d:
        for value, text, want in cases:
            _write(d, "f.txt", text)
            got = ec.check_claim(value, "f.txt", d)["status"] == "verified"
            assert got == want, f"{value!r} vs {text!r}: verified={got}, want {want}"


def test_value_zero_checkable_in_batch():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "r.json", '{"bias": 0}')
        out = ec.check_batch([{"id": "c", "value": 0, "source": "r.json"},
                              {"id": "e", "value": "", "source": "r.json"}], d)
        st = {r["id"]: r["status"] for r in out["results"]}
        assert st["c"] == "verified"      # 0 must not be 'unparseable'
        assert st["e"] == "unparseable"   # empty string is unparseable


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
