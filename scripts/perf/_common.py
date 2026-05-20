"""Shared utilities for the performance audit toolchain."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_BASE = REPO_ROOT / ".cache" / "perf-report"


def today_dir() -> Path:
    """Return and create the dated report directory for today."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = REPORT_BASE / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_summary(report_dir: Path) -> dict:
    """Read summary.json from a report directory, returning {} if missing."""
    path = report_dir / "summary.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def write_summary(report_dir: Path, data: dict) -> None:
    """Write summary.json to a report directory."""
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.json").write_text(json.dumps(data, indent=2))


def merge_json_files(dir_path: Path, glob_pattern: str) -> dict:
    """Merge all JSON files matching glob_pattern into a single dict keyed by filename stem."""
    merged: dict = {}
    for f in sorted(dir_path.glob(glob_pattern)):
        try:
            merged[f.stem] = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            merged[f.stem] = {"error": f"Failed to parse {f.name}"}
    return merged


def delta_table(prev: dict, curr: dict, metrics: list[tuple[str, str]]) -> str:
    """Build a terminal delta table comparing two summary dicts.

    Args:
        prev: Previous summary dict.
        curr: Current summary dict.
        metrics: List of (label, dotted_key_path) pairs, e.g. [("API login p50", "api.login.p50")].

    Returns:
        Formatted table string.
    """
    lines = [
        f"{'Metric':<40} {'Previous':>12} {'Current':>12} {'Delta':>10}",
        "-" * 74,
    ]

    def _get(d: dict, path: str):
        keys = path.split(".")
        v = d
        for k in keys:
            v = v.get(k, {}) if isinstance(v, dict) else {}
        return v if isinstance(v, (int, float)) else None

    for label, key_path in metrics:
        pv = _get(prev, key_path)
        cv = _get(curr, key_path)
        if pv is not None and cv is not None and pv != 0:
            delta = (cv - pv) / pv * 100
            pv_str = f"{pv:.1f}"
            cv_str = f"{cv:.1f}"
            delta_str = f"{delta:+.1f}%"
        else:
            pv_str = str(pv) if pv is not None else "N/A"
            cv_str = str(cv) if cv is not None else "N/A"
            delta_str = "N/A"
        lines.append(f"{label:<40} {pv_str:>12} {cv_str:>12} {delta_str:>10}")

    return "\n".join(lines)


def check_thresholds(summary: dict, thresholds: dict[str, float]) -> list[str]:
    """Check summary values against thresholds. Returns list of violation messages."""
    violations: list[str] = []
    for path, limit in thresholds.items():
        keys = path.split(".")
        v = summary
        for k in keys:
            v = v.get(k, {}) if isinstance(v, dict) else 0
        if isinstance(v, (int, float)) and v > limit:
            violations.append(f"{path}: {v:.1f} > {limit:.1f}")
    return violations


def fail(msg: str) -> None:
    """Print error and exit non-zero."""
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)
