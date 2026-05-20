"""React Profiler data collection and reporting.

Starts a tiny HTTP server that the frontend can POST profiler data to,
then generates a ranked component render-time report.

Usage:
  # Start the collection server
  python scripts/perf/react/profiler_report.py --collect

  # Generate report from collected data
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

    def log_message(self, format, *args):
        pass  # Suppress request logs


def start_collect_server(port: int = 9876) -> None:
    print(f"Profiler collection server listening on http://127.0.0.1:{port}")
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
        cid = entry.get("id", "unknown")
        if cid not in by_id:
            by_id[cid] = {"id": cid, "calls": 0, "total_ms": 0.0, "max_ms": 0.0}
        by_id[cid]["calls"] += 1
        by_id[cid]["total_ms"] += entry.get("actualDuration", 0)
        by_id[cid]["max_ms"] = max(by_id[cid]["max_ms"], entry.get("actualDuration", 0))

    ranked = sorted(by_id.values(), key=lambda x: x["total_ms"], reverse=True)
    return {
        "components": ranked,
        "total_entries": len(data),
        "total_duration_ms": sum(d.get("actualDuration", 0) for d in data),
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

    out_path = path.parent / "react-render.json" if path.suffix != ".json" else path
    out_path.write_text(json.dumps(report, indent=2))

    print(f"\nReact Render Performance (sorted by total render time)")
    print(f"{'Component':<40} {'Calls':>7} {'Total(ms)':>11} {'Max(ms)':>9}")
    print("-" * 68)
    for c in report["components"][:15]:
        print(f"{c['id']:<40} {c['calls']:>7} {c['total_ms']:>11.2f} {c['max_ms']:>9.2f}")


if __name__ == "__main__":
    main()
