"""SQLite index analyzer — scans all project databases for missing indexes."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

STATE_ROOT = Path.home() / ".ainrf" / "runtime"

# Column names frequently used in WHERE / JOIN / ORDER BY clauses that should be indexed
WATCH_COLUMNS: dict[str, list[str]] = {
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
        ("list_collaborators", "SELECT user_id, role FROM project_collaborators WHERE project_id = ?"),
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
        for row in conn.execute(f"PRAGMA table_info('{tbl}')"):
            if row[5]:  # pk flag
                cols.add(row[1])
        # Index columns
        for idx_row in conn.execute(f"PRAGMA index_list('{tbl}')"):
            for info_row in conn.execute(f"PRAGMA index_info('{idx_row[1]}')"):
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
                    placeholders = query.count("?")
                    params = ("?",) * placeholders if placeholders else ()
                    plan_rows = conn.execute(f"EXPLAIN QUERY PLAN {query}", params).fetchall()
                    plan_text = "\n".join(
                        f"  {r[0]}|{r[1]}|{r[2]}|{r[3]}"
                        for r in plan_rows
                    )
                    if "SCAN TABLE" in plan_text:
                        findings["full_scans"].append(f"{db_key}:{label}\n{plan_text}")
                except Exception as exc:
                    findings["full_scans"].append(f"{db_key}:{label} (EXPLAIN failed: {exc})")

    finally:
        conn.close()

    return findings


def render_report(all_findings: dict[str, dict]) -> str:
    """Render findings as a Markdown report."""
    lines = ["# Database Index Analysis Report", "", f"**State root:** `{STATE_ROOT}`", ""]
    for db_key in sorted(all_findings.keys()):
        findings = all_findings[db_key]
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
                parts = m.split(":")
                lines.append(f"- `{parts[0]}` — `{parts[1]}` (missing index on `{parts[1].split('.')[1]}`)")
            lines.append("")

        scans = findings.get("full_scans", [])
        if scans:
            lines.append("### Full Table Scans Detected")
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
    (report_dir / "db-summary.json").write_text(json.dumps({
        db: {
            "missing_index_count": len(f.get("missing_indexes", [])),
            "full_scan_count": len(f.get("full_scans", [])),
        }
        for db, f in all_findings.items()
    }, indent=2))


if __name__ == "__main__":
    main()
