#!/usr/bin/env python3
"""Performance audit orchestrator — run all or selected subsystems."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure the repo root is on sys.path so that "scripts.perf._common" resolves.
# Python 3.14+ no longer adds the current directory to sys.path by default.
_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.perf._common import (  # noqa: E402 - direct script execution needs repo root first
    today_dir,
    write_summary,
    read_summary,
    delta_table,
    check_thresholds,
    fail,
    REPORT_BASE,
)

BACKEND_TOOLS = ["db", "api-benchmark", "profile-hot"]
FRONTEND_TOOLS = ["bundle-report", "lighthouse"]
REACT_TOOLS = ["profiler"]

PERF_DIR = Path(__file__).resolve().parent

TOOL_MAP: dict[str, list[str]] = {
    "db": [sys.executable, str(PERF_DIR / "backend" / "analyze_db.py")],
    "api-benchmark": [
        sys.executable,
        "-m",
        "pytest",
        str(PERF_DIR / "backend" / "benchmark_api.py"),
        "--benchmark-only",
        "--benchmark-min-rounds=10",
    ],
    "profile-hot": [sys.executable, str(PERF_DIR / "backend" / "profile_hot.py")],
    "bundle-report": ["node", str(PERF_DIR / "frontend" / "bundle_report.mjs")],
    "lighthouse": ["node", str(PERF_DIR / "frontend" / "lighthouse.js")],
    "profiler": [sys.executable, str(PERF_DIR / "react" / "profiler_report.py"), "--report"],
}


def run_tool(name: str, report_dir: Path) -> bool:
    """Run a single tool. Returns True on success."""
    cmd = TOOL_MAP.get(name)
    if not cmd:
        print(f"Unknown tool: {name}")
        return False

    # For tools that need the report dir path appended
    if name == "api-benchmark":
        cmd = cmd + [f"--benchmark-json={report_dir}/api-benchmark.json"]
    elif name == "profiler":
        cmd = cmd + [str(report_dir / "react-render.json")]

    print(f"\n{'=' * 60}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'=' * 60}")
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", "")
    repo_root = str(Path(__file__).resolve().parent.parent.parent)
    if repo_root not in env["PYTHONPATH"]:
        env["PYTHONPATH"] = f"{repo_root}:{env['PYTHONPATH']}" if env["PYTHONPATH"] else repo_root
    try:
        subprocess.run(cmd, check=True, timeout=600, env=env)
        return True
    except subprocess.CalledProcessError:
        print(f"Tool '{name}' failed with non-zero exit code")
        return False
    except subprocess.TimeoutExpired:
        print(f"Tool '{name}' timed out (10 min)")
        return False


def build_summary(report_dir: Path, results: dict[str, bool]) -> dict:
    """Build a summary.json from tool outputs."""
    summary: dict = {"date": report_dir.name, "results": results}

    # DB summary
    db_summary = report_dir / "db-summary.json"
    if db_summary.exists():
        summary["db"] = json.loads(db_summary.read_text())

    # API benchmark summary
    api_file = report_dir / "api-benchmark.json"
    if api_file.exists():
        try:
            api_data = json.loads(api_file.read_text())
            summary["api"] = {}
            for bench in api_data.get("benchmarks", []):
                name = bench["name"].replace("test_", "").replace("[", "_").replace("]", "")
                summary["api"][name] = {
                    "p50": bench["stats"]["median"],
                    "p95": bench["stats"]["p95"],
                    "p99": bench["stats"]["p99"],
                    "ops": round(bench["stats"]["ops"], 2),
                }
        except Exception:
            summary["api"] = {"error": "Failed to parse benchmark results"}

    # Bundle summary
    bundle_file = report_dir / "bundle-stats.json"
    if bundle_file.exists():
        try:
            bundle_data = json.loads(bundle_file.read_text())
            total_raw = sum(c["rawBytes"] for c in bundle_data.get("chunks", []))
            total_gzip = sum(c["gzipBytes"] for c in bundle_data.get("chunks", []))
            summary["bundle"] = {
                "totalRawKB": round(total_raw / 1024, 1),
                "totalGzipKB": round(total_gzip / 1024, 1),
                "chunkCount": len(bundle_data.get("chunks", [])),
                "warnings": bundle_data.get("warnings", []),
            }
        except Exception:
            summary["bundle"] = {"error": "Failed to parse bundle stats"}

    return summary


def do_diff() -> None:
    """Compare the two most recent report directories."""
    dirs = sorted(
        [d for d in REPORT_BASE.iterdir() if d.is_dir() and (d / "summary.json").exists()],
        reverse=True,
    )
    if len(dirs) < 2:
        fail("Need at least 2 report directories with summary.json for diff")

    curr_dir, prev_dir = dirs[0], dirs[1]
    prev = read_summary(prev_dir)
    curr = read_summary(curr_dir)

    metrics: list[tuple[str, str]] = []
    for key in curr.get("api", {}):
        for stat in ["p50", "p95", "p99"]:
            metrics.append((f"API {key} {stat}", f"api.{key}.{stat}"))
    for key in ["totalRawKB", "totalGzipKB"]:
        metrics.append((f"Bundle {key}", f"bundle.{key}"))

    table = delta_table(prev, curr, metrics)
    print(f"\nPerformance Delta: {prev_dir.name} -> {curr_dir.name}")
    print(table)

    diff_path = curr_dir / "delta.txt"
    diff_path.write_text(table)
    print(f"\nDelta saved to {diff_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scholar-Agent Performance Audit")
    parser.add_argument("--target", choices=["backend", "frontend", "db", "all"], default="all")
    parser.add_argument(
        "--ci",
        action="store_true",
        help="JSON summary output, exit non-zero on threshold violation",
    )
    parser.add_argument("--diff", action="store_true", help="Compare two most recent reports")
    parser.add_argument(
        "--threshold",
        help="Comma-separated threshold rules, e.g. 'api.create_task_minimal.p95=800'",
    )
    args = parser.parse_args()

    if args.diff:
        do_diff()
        return

    report_dir = today_dir()

    tools: list[str] = []
    if args.target == "all":
        tools = BACKEND_TOOLS + FRONTEND_TOOLS
    elif args.target == "backend":
        tools = BACKEND_TOOLS
    elif args.target == "frontend":
        tools = FRONTEND_TOOLS
    elif args.target == "db":
        tools = ["db"]

    results: dict[str, bool] = {}
    for tool in tools:
        results[tool] = run_tool(tool, report_dir)

    summary = build_summary(report_dir, results)
    write_summary(report_dir, summary)

    if args.ci:
        print(json.dumps(summary, indent=2))
    else:
        success = sum(1 for v in results.values() if v)
        total = len(results)
        print(f"\n{'=' * 60}")
        print(f"Performance audit complete: {success}/{total} tools passed")
        print(f"Report directory: {report_dir}")

    threshold_map: dict[str, float] = {}
    if args.threshold:
        for rule in args.threshold.split(","):
            path, val = rule.split("=")
            threshold_map[path] = float(val)

    if threshold_map:
        violations = check_thresholds(summary, threshold_map)
        if violations:
            for v in violations:
                print(f"THRESHOLD VIOLATION: {v}")
            if args.ci:
                sys.exit(1)

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
