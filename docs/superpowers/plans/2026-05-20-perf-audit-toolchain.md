# Performance Audit Toolchain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a sustainable full-stack performance audit toolchain covering backend API benchmarks, py-spy hotspot sampling, SQLite index analysis, frontend bundle analysis, Lighthouse audits, and React Profiler reporting.

**Architecture:** A `scripts/perf/` directory with independent sub-tools per subsystem, orchestrated by `run-all.py`. Each tool outputs to `.cache/perf-report/YYYY-MM-DD/`. The orchestrator supports `--target` filtering, `--ci` JSON mode, `--diff` historical comparison, and `--threshold` regression gating.

**Tech Stack:** Python (pytest-benchmark, py-spy), Node (rollup-plugin-visualizer, lhci), React.Profiler API

---

## File Map

| File | Responsibility |
|------|---------------|
| `scripts/perf/__init__.py` | Package marker |
| `scripts/perf/_common.py` | Shared: date-based report dir, JSON merge, delta table formatter, threshold checker |
| `scripts/perf/run-all.py` | Orchestrator: CLI with `--target`, `--ci`, `--diff`, `--threshold` |
| `scripts/perf/backend/__init__.py` | Package marker |
| `scripts/perf/backend/analyze_db.py` | SQLite schema scan, EXPLAIN QUERY PLAN, missing-index report |
| `scripts/perf/backend/benchmark_api.py` | pytest-benchmark suite for API endpoint latency |
| `scripts/perf/backend/profile_hot.py` | py-spy attach helper + workload trigger script |
| `scripts/perf/frontend/bundle_report.mjs` | Vite build + visualizer + chunk-size scanner |
| `scripts/perf/frontend/lighthouse.js` | LHCI collect/assert config |
| `scripts/perf/react/profiler_report.py` | Parse React.Profiler JSON export into ranked table |
| `frontend/vite.config.ts` | Add visualizer plugin (conditional) |
| `frontend/src/App.tsx` | Add conditional `<React.Profiler>` wrapper |
| `.github/workflows/perf-check.yml` | Manual CI workflow trigger |
| `pyproject.toml` | Add `pytest-benchmark` dependency |
| `frontend/package.json` | Add `rollup-plugin-visualizer`, `@lhci/cli` devDeps |

---

### Task 1: Shared Infrastructure

**Files:**
- Create: `scripts/perf/__init__.py`
- Create: `scripts/perf/_common.py`
- Create: `scripts/perf/backend/__init__.py`

- [ ] **Step 1: Create `scripts/perf/__init__.py`**

```python
"""Performance audit toolchain."""
```

- [ ] **Step 2: Create `scripts/perf/backend/__init__.py`**

```python
"""Backend performance measurement tools."""
```

- [ ] **Step 3: Write `scripts/perf/_common.py`**

```python
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
```

- [ ] **Step 4: Verify module imports**

```bash
uv run python -c "from scripts.perf._common import today_dir, write_summary, delta_table; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add scripts/perf/__init__.py scripts/perf/_common.py scripts/perf/backend/__init__.py
git commit -m "feat(perf): add shared infrastructure for performance audit toolchain"
```

---

### Task 2: Database Index Analyzer

**Files:**
- Create: `scripts/perf/backend/analyze_db.py`

- [ ] **Step 1: Write `scripts/perf/backend/analyze_db.py`**

```python
"""SQLite index analyzer — scans all project databases for missing indexes."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATE_ROOT = Path.home() / ".ainrf" / "runtime"

# Column names frequently used in WHERE / JOIN / ORDER BY clauses that should be indexed
WATCH_COLUMNS = {
    "task_harness_tasks": ["project_id", "status", "environment_id", "workspace_id", "session_id", "owner_user_id", "created_at"],
    "task_harness_output_events": ["kind"],
    "task_harness_edges": ["project_id", "source_task_id", "target_task_id"],
    "managed_tasks": ["environment_id", "status", "task_id"],
    "task_terminal_bindings": ["status", "ownership_user_id", "agent_write_state"],
    "task_sessions": ["project_id", "status", "created_at"],
    "task_attempts": ["session_id", "parent_attempt_id", "status"],
    "users": ["username", "status"],
    "refresh_tokens": ["user_id", "expires_at"],
}

# Queries to EXPLAIN — these represent common API call paths
EXPLAIN_QUERIES: dict[str, list[tuple[str, str]]] = {
    "task_harness.sqlite3": [
        ("list_tasks_by_project",
         "SELECT task_id FROM task_harness_tasks WHERE project_id = ? AND status != 'archived'"),
        ("list_output_by_task",
         "SELECT seq, kind, data FROM task_harness_output_events WHERE task_id = ? AND seq > ?"),
        ("list_edges_by_project",
         "SELECT edge_id, source_task_id, target_task_id FROM task_harness_edges WHERE project_id = ?"),
    ],
    "auth.sqlite3": [
        ("login_lookup", "SELECT id, password_hash, role, status FROM users WHERE username = ?"),
        ("list_collaborators",
         "SELECT user_id, role FROM project_collaborators WHERE project_id = ?"),
    ],
    "sessions.sqlite3": [
        ("list_sessions",
         "SELECT session_id, title, status FROM task_sessions WHERE project_id = ? ORDER BY created_at DESC"),
        ("list_attempts",
         "SELECT attempt_id, status, started_at FROM task_attempts WHERE session_id = ? ORDER BY started_at DESC"),
    ],
}


def get_tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]


def get_indexed_columns(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Return {table_name: {indexed_column_names}} including PK columns."""
    indexed: dict[str, set[str]] = {}
    for (tbl,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        cols: set[str] = set()
        # Primary key columns
        pk_rows = conn.execute(f"PRAGMA table_info('{tbl}')")
        for row in pk_rows:
            if row[5]:  # pk flag
                cols.add(row[1])
        # Index columns
        idx_rows = conn.execute(f"PRAGMA index_list('{tbl}')")
        for idx_row in idx_rows:
            info_rows = conn.execute(f"PRAGMA index_info('{idx_row[1]}')")
            for info_row in info_rows:
                cols.add(info_row[2])
        indexed[tbl] = cols
    return indexed


def analyze_db(db_path: Path) -> dict:
    """Analyze a single SQLite database. Returns findings dict."""
    findings: dict[str, list[str]] = {"missing_indexes": [], "full_scans": [], "tables": []}
    if not db_path.exists():
        findings["error"] = f"Database not found: {db_path}"
        return findings

    conn = sqlite3.connect(str(db_path))
    try:
        tables = get_tables(conn)
        findings["tables"] = tables
        indexed = get_indexed_columns(conn)

        # Check missing indexes
        for tbl in tables:
            if tbl in WATCH_COLUMNS:
                need = WATCH_COLUMNS[tbl]
                have = indexed.get(tbl, set())
                for col in need:
                    if col not in have:
                        findings["missing_indexes"].append(f"{db_path.name}:{tbl}.{col}")

        # EXPLAIN QUERY PLAN for core queries
        db_key = db_path.name
        if db_key in EXPLAIN_QUERIES:
            for label, query in EXPLAIN_QUERIES[db_key]:
                try:
                    plan_rows = conn.execute(f"EXPLAIN QUERY PLAN {query}", ("?",) * query.count("?")).fetchall()
                    plan_text = "\n".join(
                        f"  {r[0]}|{r[1]}|{r[2]}|{r[3]}"
                        for r in plan_rows
                    )
                    if "SCAN TABLE" in plan_text:
                        findings["full_scans"].append(f"{db_key}:{label}\n{plan_text}")
                except Exception:
                    findings["full_scans"].append(f"{db_key}:{label} (EXPLAIN failed)")

    finally:
        conn.close()

    return findings


def render_report(all_findings: dict[str, dict]) -> str:
    """Render findings as a Markdown report."""
    lines = ["# Database Index Analysis Report", "", f"**State root:** `{STATE_ROOT}`", ""]
    for db_key, findings in sorted(all_findings.items()):
        lines.append(f"## {db_key}")
        lines.append("")
        if "error" in findings:
            lines.append(f"**Error:** {findings['error']}")
            lines.append("")
            continue

        lines.append(f"Tables: {', '.join(findings.get('tables', []))}")
        lines.append("")

        missing = findings.get("missing_indexes", [])
        if missing:
            lines.append("### Missing Indexes")
            for m in sorted(missing):
                lines.append(f"- `CREATE INDEX ON {m.split(':')[1]}` — `{m}`")
            lines.append("")

        scans = findings.get("full_scans", [])
        if scans:
            lines.append("### Full Table Scans")
            for s in scans:
                lines.append(f"```\n{s}\n```")
            lines.append("")
        else:
            lines.append("*No full table scans detected in core queries.*")
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    from scripts.perf._common import today_dir

    report_dir = today_dir()
    all_findings: dict[str, dict] = {}

    for db_name in ["auth.sqlite3", "sessions.sqlite3", "task_harness.sqlite3", "terminal_state.sqlite3"]:
        db_path = STATE_ROOT / db_name
        all_findings[db_name] = analyze_db(db_path)

    report_md = render_report(all_findings)
    out_path = report_dir / "db-index-report.md"
    out_path.write_text(report_md)
    print(f"Database index report written to {out_path}")

    # Also write JSON summary for the master summary
    import json
    (report_dir / "db-summary.json").write_text(json.dumps({
        db: {
            "missing_index_count": len(f.get("missing_indexes", [])),
            "full_scan_count": len(f.get("full_scans", [])),
        }
        for db, f in all_findings.items()
    }, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the analyzer**

```bash
uv run python scripts/perf/backend/analyze_db.py
```

Expected: creates `.cache/perf-report/YYYY-MM-DD/db-index-report.md` and `db-summary.json`.

- [ ] **Step 3: Commit**

```bash
git add scripts/perf/backend/analyze_db.py
git commit -m "feat(perf): add SQLite index analyzer with EXPLAIN QUERY PLAN checker"
```

---

### Task 3: API Benchmark Suite

**Files:**
- Create: `scripts/perf/backend/benchmark_api.py`
- Modify: `pyproject.toml` (add dependency)

- [ ] **Step 1: Add `pytest-benchmark` to `pyproject.toml`**

Add `"pytest-benchmark>=5.1"` to the `dependencies` list in `pyproject.toml`.

- [ ] **Step 2: Install the new dependency**

```bash
uv sync
```

- [ ] **Step 3: Write `scripts/perf/backend/benchmark_api.py`**

```python
"""API latency benchmarks using pytest-benchmark.

Usage: uv run pytest scripts/perf/backend/benchmark_api.py --benchmark-only --benchmark-json=.cache/perf-report/YYYY-MM-DD/api-benchmark.json

Requires a running AINRF server at http://127.0.0.1:8000 with a test admin user.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

BASE_URL = os.environ.get("AINRF_PERF_BASE_URL", "http://127.0.0.1:8000")
ADMIN_USER = os.environ.get("AINRF_PERF_USER", "perf-admin")
ADMIN_PASS = os.environ.get("AINRF_PERF_PASS", "perf-test-pass")


def _admin_headers(client: httpx.Client) -> dict:
    """Get admin JWT headers, registering the perf user if needed."""
    # Try login
    resp = client.post(f"{BASE_URL}/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
    if resp.status_code == 200:
        token = resp.json()["access_token"]
    else:
        # Register then activate
        client.post(f"{BASE_URL}/auth/register", json={
            "username": ADMIN_USER, "display_name": "Perf Admin", "password": ADMIN_PASS,
        })
        # Login — will fail if must_change_password or pending
        resp2 = client.post(f"{BASE_URL}/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        if resp2.status_code != 200:
            pytest.skip(f"Cannot authenticate perf user: {resp2.text}")
        token = resp2.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    return _admin_headers(client)


# ---- Auth endpoints ----

def test_login(benchmark, client):
    benchmark(lambda: client.post(f"{BASE_URL}/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}))


def test_auth_me(benchmark, client, auth_headers):
    benchmark(lambda: client.get(f"{BASE_URL}/auth/me", headers=auth_headers))


# ---- Project endpoints ----

def test_list_projects(benchmark, client, auth_headers):
    benchmark(lambda: client.get(f"{BASE_URL}/projects", headers=auth_headers))


def test_list_tasks(benchmark, client, auth_headers):
    benchmark(lambda: client.get(f"{BASE_URL}/projects/default/tasks", headers=auth_headers))


def test_list_task_edges(benchmark, client, auth_headers):
    benchmark(lambda: client.get(f"{BASE_URL}/projects/default/task-edges", headers=auth_headers))


# ---- File endpoints ----

def test_file_list(benchmark, client, auth_headers):
    benchmark(lambda: client.get(f"{BASE_URL}/files/list?environment_id=env-localhost&path=/", headers=auth_headers))


# ---- Session endpoints ----

def test_list_sessions(benchmark, client, auth_headers):
    benchmark(lambda: client.get(f"{BASE_URL}/sessions", headers=auth_headers))


# ---- Task creation (lightweight — no execution engine during bench) ----
# NOTE: This creates a real task record. Use a dedicated test project in CI.

def test_create_task_minimal(benchmark, client, auth_headers):
    payload = {
        "project_id": "default",
        "workspace_id": "workspace-default",
        "environment_id": "env-localhost",
        "task_profile": "claude-code",
        "task_input": "benchmark",
        "title": "perf-bench-task",
    }
    benchmark(lambda: client.post(f"{BASE_URL}/tasks", json=payload, headers=auth_headers))
```

- [ ] **Step 4: Run the benchmarks**

First ensure the server is running, then:

```bash
uv run pytest scripts/perf/backend/benchmark_api.py --benchmark-only --benchmark-json=.cache/perf-report/$(date +%Y-%m-%d)/api-benchmark.json --benchmark-min-rounds=10 --benchmark-max-time=0.5
```

Expected: JSON output at the specified path with p50/p95/p99 stats per test.

- [ ] **Step 5: Commit**

```bash
git add scripts/perf/backend/benchmark_api.py pyproject.toml uv.lock
git commit -m "feat(perf): add API latency benchmark suite with pytest-benchmark"
```

---

### Task 4: Hotspot Profiler (py-spy)

**Files:**
- Create: `scripts/perf/backend/profile_hot.py`

- [ ] **Step 1: Write `scripts/perf/backend/profile_hot.py`**

```python
"""py-spy hotspot profiler helper.

Attaches py-spy to the running AINRF server process and triggers a
representative workload, producing a flamegraph SVG.

Requires: py-spy (pip install py-spy)
Requires: A running AINRF server with a known PID.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = os.environ.get("AINRF_PERF_BASE_URL", "http://127.0.0.1:8000")
STATE_ROOT = Path(os.environ.get("AINRF_STATE_ROOT", Path.home() / ".ainrf"))
PID_FILE = STATE_ROOT / "server.pid"
DURATION = int(os.environ.get("AINRF_PERF_PROFILE_DURATION", "30"))

WORKLOAD_SCRIPT = '''
import httpx, os, sys, json
BASE = os.environ.get("AINRF_PERF_BASE_URL", "http://127.0.0.1:8000")

def get_token():
    r = httpx.post(f"{BASE}/auth/login", json={"username": "perf-admin", "password": "perf-test-pass"})
    if r.status_code != 200:
        r = httpx.post(f"{BASE}/auth/register", json={"username": "perf-admin", "display_name": "Perf Admin", "password": "perf-test-pass"})
        r = httpx.post(f"{BASE}/auth/login", json={"username": "perf-admin", "password": "perf-test-pass"})
    return r.json()["access_token"]

token = get_token()
h = {"Authorization": f"Bearer {token}"}

for i in range(10):
    httpx.get(f"{BASE}/projects/default/tasks", headers=h)
    httpx.get(f"{BASE}/files/list?environment_id=env-localhost&path=/", headers=h)
    httpx.post(f"{BASE}/tasks", json={
        "project_id": "default", "workspace_id": "workspace-default",
        "environment_id": "env-localhost", "task_profile": "claude-code",
        "task_input": "perf profile", "title": f"perf-profile-{i}",
    }, headers=h)
'''

WORKLOAD_SCRIPT_LINES = WORKLOAD_SCRIPT.strip().split('\n')


def find_pid() -> int:
    """Find the AINRF server PID from PID file or process search."""
    if PID_FILE.exists():
        return int(PID_FILE.read_text().strip())

    # Fallback: find the uvicorn process
    result = subprocess.run(
        ["pgrep", "-f", "ainrf serve"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return int(result.stdout.strip().split('\n')[0])

    print("ERROR: Cannot find AINRF server process. Start the server first or set AINRF_STATE_ROOT.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    from scripts.perf._common import today_dir

    report_dir = today_dir()

    # Check py-spy is available
    try:
        subprocess.run(["py-spy", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: py-spy not found. Install with: pip install py-spy")
        sys.exit(1)

    pid = find_pid()
    flamegraph_path = report_dir / "flamegraph.svg"

    print(f"Profiling PID {pid} for {DURATION}s...")

    # Start py-spy in background
    py_spy = subprocess.Popen([
        "py-spy", "record",
        "-o", str(flamegraph_path),
        "--pid", str(pid),
        "--duration", str(DURATION),
        "--native",  # include native C extensions
    ])

    # Give py-spy a moment to attach, then trigger workload
    time.sleep(1)
    print("Triggering workload...")
    subprocess.run(
        [sys.executable, "-c", WORKLOAD_SCRIPT],
        timeout=DURATION + 10,
    )

    # Wait for py-spy to finish
    py_spy.wait(timeout=DURATION + 15)
    print(f"Flamegraph written to {flamegraph_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Install py-spy**

```bash
uv pip install py-spy
```

- [ ] **Step 3: Test that py-spy works**

```bash
py-spy --version
```

Expected: version output, no error.

- [ ] **Step 4: Commit**

```bash
git add scripts/perf/backend/profile_hot.py
git commit -m "feat(perf): add py-spy hotspot profiler with workload trigger"
```

---

### Task 5: Frontend Bundle Analyzer

**Files:**
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/package.json`
- Create: `scripts/perf/frontend/bundle_report.mjs`

- [ ] **Step 1: Add `rollup-plugin-visualizer` to `frontend/package.json` devDependencies**

```bash
cd frontend && npm install --save-dev rollup-plugin-visualizer
```

- [ ] **Step 2: Modify `frontend/vite.config.ts` to optionally enable visualizer**

Add after the existing imports:

```typescript
import { visualizer } from 'rollup-plugin-visualizer'

const ANALYZE = process.env.VITE_BUNDLE_ANALYZE === 'true'
```

In the `plugins` array, add after `react()` and `tailwindcss()`:

```typescript
...(ANALYZE ? [visualizer({
  open: false,
  gzipSize: true,
  brotliSize: true,
  filename: '.cache/perf-report/bundle-treemap.html',
  template: 'treemap',
})] : []),
```

- [ ] **Step 3: Write `scripts/perf/frontend/bundle_report.mjs`**

```javascript
#!/usr/bin/env node
/**
 * Bundle report script — builds the frontend with the visualizer plugin
 * and scans output chunks for size anomalies.
 */
import { execSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = join(__dirname, '..', '..', '..', 'frontend');
const REPORT_DIR = join(__dirname, '..', '..', '..', '.cache', 'perf-report', new Date().toISOString().slice(0, 10));

const CHUNK_WARN_KB = 500;

function run(cmd, cwd = FRONTEND_DIR) {
  console.log(`> ${cmd}`);
  return execSync(cmd, { cwd, encoding: 'utf-8', stdio: 'inherit' });
}

// Step 1: Build with visualizer enabled
console.log('Building frontend with bundle analyzer...');
run('VITE_BUNDLE_ANALYZE=true npx vite build');

// Move the treemap to the report dir
const treemapSrc = join(FRONTEND_DIR, '.cache', 'perf-report', 'bundle-treemap.html');
const treemapDst = join(REPORT_DIR, 'bundle-treemap.html');
mkdirSync(REPORT_DIR, { recursive: true });
try {
  const treemapHtml = readFileSync(treemapSrc, 'utf-8');
  writeFileSync(treemapDst, treemapHtml);
  console.log(`Treemap written to ${treemapDst}`);
} catch {
  console.warn('Warning: treemap HTML not found.');
}

// Step 2: Collect chunk stats
const distDir = join(FRONTEND_DIR, 'dist');
const { readdirSync, statSync } = await import('node:fs');
const { gzipSync, brotliCompressSync } = await import('node:zlib');

function collectStats(dir) {
  const chunks = [];
  for (const entry of readdirSync(dir, { recursive: true, withFileTypes: true })) {
    const fp = join(entry.parentPath || entry.path, entry.name);
    if (entry.isFile() && (entry.name.endsWith('.js') || entry.name.endsWith('.css'))) {
      const raw = readFileSync(fp);
      chunks.push({
        file: fp.replace(distDir + '/', ''),
        rawBytes: raw.length,
        gzipBytes: gzipSync(raw).length,
        brotliBytes: brotliCompressSync(raw).length,
      });
    }
  }
  return chunks;
}

const chunks = collectStats(distDir);
chunks.sort((a, b) => b.rawBytes - a.rawBytes);

const statsPath = join(REPORT_DIR, 'bundle-stats.json');
writeFileSync(statsPath, JSON.stringify({ chunks, warnings: [] }, null, 2));

// Step 3: Scan for anomalies
const warnings = [];
for (const c of chunks) {
  if (c.gzipBytes > CHUNK_WARN_KB * 1024) {
    warnings.push(`LARGE CHUNK: ${c.file} — ${(c.gzipBytes / 1024).toFixed(1)}KB gzip`);
  }
}

// Check for duplicate module patterns (simple heuristic)
const filenames = chunks.map(c => c.file);
for (const f of filenames) {
  const base = f.split('/').pop();
  const dupes = filenames.filter(x => x.endsWith(base) && x !== f);
  for (const d of dupes) {
    warnings.push(`DUPLICATE MODULE: ${f} and ${d} may be the same module in different chunks`);
  }
}

if (warnings.length > 0) {
  console.log('\n=== Bundle Warnings ===');
  for (const w of warnings) console.log(`  ⚠  ${w}`);
  writeFileSync(statsPath, JSON.stringify({ chunks, warnings }, null, 2));
} else {
  console.log('\nNo bundle size warnings.');
}

console.log(`\nBundle stats written to ${statsPath}`);
```

- [ ] **Step 4: Test the bundle report**

```bash
cd frontend && node ../scripts/perf/frontend/bundle_report.mjs
```

Expected: builds frontend, produces `.cache/perf-report/YYYY-MM-DD/bundle-treemap.html` and `bundle-stats.json`.

- [ ] **Step 5: Commit**

```bash
cd frontend && git add package.json package-lock.json ../scripts/perf/frontend/bundle_report.mjs vite.config.ts && git commit -m "feat(perf): add frontend bundle analyzer with size anomaly scanner"
```

---

### Task 6: Lighthouse Audit

**Files:**
- Create: `scripts/perf/frontend/lighthouse.js`

- [ ] **Step 1: Add `@lhci/cli` to devDependencies**

```bash
cd frontend && npm install --save-dev @lhci/cli
```

- [ ] **Step 2: Write `scripts/perf/frontend/lighthouse.js`**

```javascript
#!/usr/bin/env node
/**
 * Lighthouse CI audit for key pages.
 *
 * Usage: node scripts/perf/frontend/lighthouse.js [--url=http://localhost:5173]
 *
 * Requires a running frontend dev server.
 */
import { execSync } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPORT_DIR = join(__dirname, '..', '..', '..', '.cache', 'perf-report', new Date().toISOString().slice(0, 10));

const BASE_URL = process.argv.find(a => a.startsWith('--url='))?.split('=')[1] || 'http://localhost:5173';
const PAGES = ['/login', '/projects', '/tasks'];

function run(cmd) {
  console.log(`> ${cmd}`);
  execSync(cmd, { encoding: 'utf-8', stdio: 'inherit' });
}

mkdirSync(REPORT_DIR, { recursive: true });

// Collect each page
for (const page of PAGES) {
  const url = `${BASE_URL}${page}`;
  console.log(`\n=== Auditing ${url} ===`);
  const slug = page.replace(/^\//, '').replace(/\//g, '-') || 'home';
  const reportFile = join(REPORT_DIR, `lighthouse-${slug}.json`);
  const htmlFile = join(REPORT_DIR, `lighthouse-${slug}.html`);

  try {
    run(`npx lhci collect --url="${url}" --numberOfRuns=3`);
    run(`npx lhci upload --target=filesystem --outputDir="${REPORT_DIR}" --reportFilenamePattern="lighthouse-${slug}-%%datetime%%.%%ext%%"`);
  } catch (e) {
    console.warn(`Warning: Lighthouse audit failed for ${url}: ${e.message}`);
  }
}

// Summary
console.log(`\nLighthouse reports saved to ${REPORT_DIR}`);
```

- [ ] **Step 3: Test with the dev server running**

```bash
cd frontend && node ../scripts/perf/frontend/lighthouse.js
```

- [ ] **Step 4: Commit**

```bash
cd frontend && git add package.json package-lock.json ../scripts/perf/frontend/lighthouse.js && git commit -m "feat(perf): add Lighthouse CI audit for key frontend pages"
```

---

### Task 7: React Profiler Integration

**Files:**
- Modify: `frontend/src/App.tsx`
- Create: `scripts/perf/react/profiler_report.py`

- [ ] **Step 1: Modify `frontend/src/App.tsx` to add conditional Profiler**

Add import at top (after existing imports):

```typescript
import { Profiler, type ProfilerOnRenderCallback } from 'react';
```

After the existing `queryClient` declaration and before `AppRoutes`, add:

```typescript
const PROFILER_ENABLED = import.meta.env.VITE_PROFILE === 'true';

const profilerData: Array<{
  id: string;
  phase: string;
  actualDuration: number;
  baseDuration: number;
  commitTime: number;
}> = [];

const onRender: ProfilerOnRenderCallback = (
  id, phase, actualDuration, baseDuration, startTime, commitTime,
) => {
  if (PROFILER_ENABLED) {
    profilerData.push({ id, phase, actualDuration, baseDuration, commitTime });
    if (profilerData.length >= 100) {
      profilerData.splice(0, profilerData.length - 50);
    }
  }
};

// Expose profiler data to window for the report script to collect
if (PROFILER_ENABLED && typeof window !== 'undefined') {
  (window as unknown as Record<string, unknown>).__perfProfilerData = profilerData;
}
```

Wrap the main content in `<Profiler>` — in the `AppRoutes` component, wrap the final JSX return in `<Profiler id="AppRoot" onRender={onRender}>...</Profiler>`.

- [ ] **Step 2: Write `scripts/perf/react/profiler_report.py`**

```python
"""React Profiler data collection and reporting.

Starts a tiny HTTP server that the frontend can POST profiler data to,
then generates a ranked component render-time report.

Usage:
  # Terminal 1: Start the collection server
  python scripts/perf/react/profiler_report.py --collect

  # Terminal 2: Browse the app with VITE_PROFILE=true, then POST
  curl -X POST http://localhost:9876/dump -d @- < /dev/null

  # Or: Generate report from saved data
  python scripts/perf/react/profiler_report.py --report .cache/perf-report/YYYY-MM-DD/react-render.json
"""

from __future__ import annotations

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse


COLLECTED: list[dict] = []


class CollectHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/collect":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            COLLECTED.extend(data if isinstance(data, list) else [data])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"received": len(COLLECTED)}).encode())
        elif path == "/dump":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(COLLECTED).encode())
        elif path == "/reset":
            COLLECTED.clear()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

    def do_GET(self):
        if urlparse(self.path).path == "/dump":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(COLLECTED).encode())


def start_collect_server(port: int = 9876) -> None:
    print(f"Profiler collection server listening on :{port}")
    server = HTTPServer(("127.0.0.1", port), CollectHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()


def generate_report(data: list[dict]) -> dict:
    """Aggregate profiler data by component id."""
    by_id: dict[str, dict] = {}
    for entry in data:
        cid = entry["id"]
        if cid not in by_id:
            by_id[cid] = {"id": cid, "calls": 0, "total_ms": 0.0, "max_ms": 0.0}
        by_id[cid]["calls"] += 1
        by_id[cid]["total_ms"] += entry["actualDuration"]
        by_id[cid]["max_ms"] = max(by_id[cid]["max_ms"], entry["actualDuration"])

    ranked = sorted(by_id.values(), key=lambda x: x["total_ms"], reverse=True)
    return {
        "components": ranked,
        "total_entries": len(data),
        "total_duration_ms": sum(d["actualDuration"] for d in data),
    }


def main() -> None:
    from scripts.perf._common import today_dir

    if "--collect" in sys.argv:
        start_collect_server()
        return

    if "--report" in sys.argv:
        idx = sys.argv.index("--report")
        path = Path(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else None
    else:
        path = today_dir() / "react-render.json"

    if path and path.exists():
        data = json.loads(path.read_text())
        report = generate_report(data)
    elif path:
        print(f"No data file at {path}. Run with --collect first and browse the app with VITE_PROFILE=true.")
        sys.exit(1)
    else:
        print("No data file specified.")
        sys.exit(1)

    # Write report
    out_path = path.parent / "react-render.json" if path.suffix != ".json" else path
    out_path.write_text(json.dumps(report, indent=2))

    # Print summary
    print(f"\nReact Render Performance (sorted by total render time)")
    print(f"{'Component':<40} {'Calls':>7} {'Total(ms)':>11} {'Max(ms)':>9}")
    print("-" * 68)
    for c in report["components"][:15]:
        print(f"{c['id']:<40} {c['calls']:>7} {c['total_ms']:>11.2f} {c['max_ms']:>9.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx scripts/perf/react/profiler_report.py
git commit -m "feat(perf): add React Profiler integration with collection server"
```

---

### Task 8: Main Orchestrator

**Files:**
- Create: `scripts/perf/run-all.py`

- [ ] **Step 1: Write `scripts/perf/run-all.py`**

```python
#!/usr/bin/env python3
"""Performance audit orchestrator — run all or selected subsystems."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts.perf._common import (
    today_dir, write_summary, read_summary, merge_json_files,
    delta_table, check_thresholds, fail, REPORT_BASE,
)

BACKEND_TOOLS = ["db", "api-benchmark", "profile-hot"]
FRONTEND_TOOLS = ["bundle-report", "lighthouse"]
REACT_TOOLS = ["profiler"]

PERF_DIR = Path(__file__).resolve().parent


def run_tool(name: str, report_dir: Path) -> bool:
    """Run a single tool. Returns True on success."""
    tool_map = {
        "db": [sys.executable, str(PERF_DIR / "backend" / "analyze_db.py")],
        "api-benchmark": [
            sys.executable, "-m", "pytest", str(PERF_DIR / "backend" / "benchmark_api.py"),
            "--benchmark-only", "--benchmark-min-rounds=10",
            f"--benchmark-json={report_dir}/api-benchmark.json",
        ],
        "profile-hot": [sys.executable, str(PERF_DIR / "backend" / "profile_hot.py")],
        "bundle-report": ["node", str(PERF_DIR / "frontend" / "bundle_report.mjs")],
        "lighthouse": ["node", str(PERF_DIR / "frontend" / "lighthouse.js")],
        "profiler": [sys.executable, str(PERF_DIR / "react" / "profiler_report.py"), "--report",
                     str(report_dir / "react-render.json")],
    }

    cmd = tool_map.get(name)
    if not cmd:
        print(f"Unknown tool: {name}")
        return False

    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*60}")
    try:
        subprocess.run(cmd, check=True, timeout=600)
        return True
    except subprocess.CalledProcessError:
        print(f"Tool {name} failed with non-zero exit code")
        return False
    except subprocess.TimeoutExpired:
        print(f"Tool {name} timed out")
        return False


def build_summary(report_dir: Path, results: dict) -> dict:
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
    # API metrics
    for key in curr.get("api", {}):
        for stat in ["p50", "p95", "p99"]:
            metrics.append((f"API {key} {stat}", f"api.{key}.{stat}"))
    # Bundle metrics
    for key in ["totalRawKB", "totalGzipKB"]:
        metrics.append((f"Bundle {key}", f"bundle.{key}"))

    table = delta_table(prev, curr, metrics)
    print(f"\nPerformance Delta: {prev_dir.name} → {curr_dir.name}")
    print(table)

    # Write diff to file
    diff_path = curr_dir / "delta.txt"
    diff_path.write_text(table)
    print(f"\nDiff saved to {diff_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scholar-Agent Performance Audit")
    parser.add_argument("--target", choices=["backend", "frontend", "db", "all"], default="all")
    parser.add_argument("--ci", action="store_true", help="JSON summary output, exit non-zero on threshold violation")
    parser.add_argument("--diff", action="store_true", help="Compare two most recent reports")
    parser.add_argument("--threshold", help="Comma-separated threshold rules, e.g. 'api.create_task_minimal.p95=800'")
    args = parser.parse_args()

    # Handle diff mode
    if args.diff:
        do_diff()
        return

    report_dir = today_dir()

    # Determine tools to run
    tools: list[str] = []
    if args.target == "all":
        tools = BACKEND_TOOLS + FRONTEND_TOOLS
    elif args.target == "backend":
        tools = BACKEND_TOOLS
    elif args.target == "frontend":
        tools = FRONTEND_TOOLS
    elif args.target == "db":
        tools = ["db"]

    # Run tools
    results: dict[str, bool] = {}
    for tool in tools:
        results[tool] = run_tool(tool, report_dir)

    # Build and write summary
    summary = build_summary(report_dir, results)
    write_summary(report_dir, summary)

    # Output
    if args.ci:
        print(json.dumps(summary, indent=2))
    else:
        success = sum(1 for v in results.values() if v)
        total = len(results)
        print(f"\n{'='*60}")
        print(f"Performance audit complete: {success}/{total} tools passed")
        print(f"Report directory: {report_dir}")

    # Threshold check (CI or manual)
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

    # Exit non-zero if any tool failed
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test the orchestrator**

```bash
uv run python scripts/perf/run-all.py --target db
```

Expected: runs the database analyzer and prints a success message.

- [ ] **Step 3: Commit**

```bash
git add scripts/perf/run-all.py
git commit -m "feat(perf): add main orchestrator with --target, --ci, --diff, --threshold"
```

---

### Task 9: CI Workflow

**Files:**
- Create: `.github/workflows/perf-check.yml`

- [ ] **Step 1: Write `.github/workflows/perf-check.yml`**

```yaml
name: Performance Check

on:
  workflow_dispatch:
    inputs:
      target:
        description: 'Subsystem to audit'
        required: false
        default: 'all'
        type: choice
        options:
          - all
          - backend
          - frontend
          - db

jobs:
  perf-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'

      - name: Install uv
        run: pip install uv

      - name: Install dependencies
        run: uv sync

      - name: Install py-spy
        run: pip install py-spy

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: '22'

      - name: Install frontend deps
        run: cd frontend && npm ci

      - name: Start server
        run: |
          uv run ainrf serve --host 127.0.0.1 --port 8000 --state-root /tmp/ainrf-ci &
          sleep 3

      - name: Run performance audit
        run: uv run python scripts/perf/run-all.py --target ${{ inputs.target }} --ci

      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: perf-report
          path: .cache/perf-report/
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/perf-check.yml
git commit -m "ci: add manual performance check workflow"
```

---

### Task 10: Integration Verification

- [ ] **Step 1: Full `--target db` run**

```bash
uv run python scripts/perf/run-all.py --target db
```

Verify: `.cache/perf-report/YYYY-MM-DD/db-index-report.md` and `db-summary.json` exist. No errors.

- [ ] **Step 2: Full `--target frontend` run**

```bash
cd frontend && node ../scripts/perf/frontend/bundle_report.mjs
```

Verify: `bundle-treemap.html` and `bundle-stats.json` exist.

- [ ] **Step 3: `--diff` mode with two reports**

```bash
# Create a second report by running db again (overwrites today's summary)
uv run python scripts/perf/run-all.py --target db
# Manually copy the first report to simulate having two days
# Then run diff
uv run python scripts/perf/run-all.py --diff
```

- [ ] **Step 4: Commit the .gitignore update**

Add to `.gitignore`:
```
.cache/perf-report/
```

```bash
git add .gitignore
git commit -m "chore: gitignore perf report cache directory"
```

---

## Verification Checklist

1. `uv run python scripts/perf/run-all.py --target db` produces index report
2. `uv run pytest scripts/perf/backend/benchmark_api.py --benchmark-only` runs API benchmarks (server must be running)
3. `uv run python scripts/perf/run-all.py --target frontend` produces bundle treemap + stats
4. `uv run python scripts/perf/run-all.py --diff` shows delta between two report dates
5. `uv run python scripts/perf/run-all.py --ci --threshold api.create_task_minimal.p95=9999` exits 0 (or 1 if above threshold)
6. GitHub Actions `perf-check` workflow appears in Actions tab (manual trigger only)
