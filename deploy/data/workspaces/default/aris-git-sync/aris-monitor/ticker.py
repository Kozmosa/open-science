#!/usr/bin/env python3
"""ARIS-Monitor: headless terminal ticker (fallback UI).

If Tkinter is unavailable (a minimal custom Python lacking the Tk module),
this prints the SAME 3-bucket triage to stdout on the SAME ~2s loop, driven by
the IDENTICAL read-only scanner.py -- zero new dependencies, zero detection
changes.

STRICTLY READ-ONLY: it only reads files via scanner.scan(). It NEVER writes,
kills, signals, spawns, polls processes, runs subprocess, or touches the
network. It self-loops (no `watch`, no external sleep beyond time.sleep on its
own process) and re-clears the screen each tick.

Run:
    python3 ticker.py
Stop with Ctrl-C.
"""
from __future__ import annotations

import sys
import time

import scanner

REFRESH_S = 2.0

_DOT = {
    scanner.NEEDS_APPROVAL:  "\033[91m●\033[0m",  # red
    scanner.NEEDS_ATTENTION: "\033[93m◐\033[0m",  # amber
    scanner.WORKING:         "\033[93m◐\033[0m",  # amber
    scanner.IDLE_DONE:       "\033[92m○\033[0m",  # green
}
_LABEL = {
    scanner.NEEDS_APPROVAL:  "NEEDS YOU",
    scanner.NEEDS_ATTENTION: "stalled",
    scanner.WORKING:         "working",
    scanner.IDLE_DONE:       "done",
}


def _render_once() -> None:
    sessions = scanner.scan()
    s = scanner.summary(sessions)
    visible = [x for x in sessions if x.triage != scanner.STALE_HIDDEN]

    sys.stdout.write("\033[2J\033[H")  # clear + home
    if s["needs_approval"]:
        head = f"\033[91mARIS-Monitor — ATTENTION  {s['needs_approval']} ●\033[0m"
    else:
        head = f"\033[92mARIS-Monitor — all clear  ○ 0\033[0m"
    print(head)
    print("-" * 40)

    if not visible:
        print("  no active Claude sessions")
    for x in visible:
        dot = _DOT.get(x.triage, "?")
        label = _LABEL.get(x.triage, x.triage)
        reason = f"  {x.reason}" if (x.triage == scanner.NEEDS_APPROVAL and x.reason) else ""
        print(f"  {dot} {x.name[:24]:<24} {label:<10} {scanner.fmt_age(x.idle_seconds):>5}{reason}")
    if s["stale"]:
        print(f"  +{s['stale']} stale (hidden)")
    print()
    print("(read-only · refresh 2s · Ctrl-C to quit)")
    sys.stdout.flush()


def main() -> None:
    try:
        while True:
            try:
                _render_once()
            except Exception:
                pass  # a bad scan must never kill the ticker
            time.sleep(REFRESH_S)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
