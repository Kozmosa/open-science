#!/bin/bash
# claude-fleet default "Focus" shim (macOS).
#
# Activates the terminal tab/window that owns <tty>. Handles the common macOS
# setups out of the box:
#   - plain Terminal.app tabs        (matched by `tty of tab`)
#   - plain iTerm2 sessions           (matched by `tty of session`)  [best-effort]
#   - tmux: the <tty> is a pane tty -> resolve to the tmux session -> the
#           terminal tab the session's (most-recently-active) client is on.
#
# Only the Terminal.app + tmux path is tested by the author; iTerm2 and the
# non-tmux direct path are best-effort. Drop your own executable
# ~/.claude/focus-tty.sh to override this bundled default.
#
# Arg: <tty> as `ps -o tty=` reports it (e.g. "ttys010", no /dev/).
#
# Exit codes: 0 focused · 2 usage · 3 tmux session detached (no tab) ·
#             4 no matching Terminal/iTerm tab · 5 Automation permission denied ·
#             6 unsupported platform (no osascript).
#
# NB: `set -e` is intentionally omitted — the tmux pipelines below discard their
# exit status (a benign SIGPIPE/empty result under pipefail) and branch on the
# captured VALUE, never on $?. Adding `-e` would break that on purpose-built
# empty results.
set -uo pipefail

RAW="${1:-}"
[ -n "$RAW" ] || { echo "usage: focus-tty.sh <tty>" >&2; exit 2; }
case "$RAW" in
  /dev/*) TTY="$RAW" ;;
  *)      TTY="/dev/$RAW" ;;
esac

# This shim raises Terminal.app/iTerm2 windows via AppleScript — macOS only.
if ! command -v osascript >/dev/null 2>&1; then
  echo "focus-tty.sh: macOS only (osascript not found); cannot raise terminal windows here." >&2
  exit 6
fi

ERRFILE=$(mktemp 2>/dev/null || echo "/tmp/focus-tty.$$.err")
trap 'rm -f "$ERRFILE"' EXIT

# True iff the named app (AppleScript name) is RUNNING. The `is running` test
# never launches the app, so probing a closed/absent app cannot cold-launch it or
# steal focus — and it needs no `pgrep` (which a stripped host might lack).
_app_running() { [ "$(osascript -e "application \"$1\" is running" 2>/dev/null)" = "true" ]; }

# Activate the Terminal.app tab whose tty == $1. Echoes "ok" / "notfound" / ""(error).
# `activate` runs only AFTER the tab/window are selected, so an error before it
# leaves focus untouched. osascript stderr is captured (not muted) so a TCC
# permission denial can be distinguished from a genuine miss.
_focus_terminal_app() {
  osascript - "$1" 2>"$ERRFILE" <<'OSA'
on run argv
    set target to item 1 of argv
    tell application "Terminal"
        repeat with w in windows
            repeat with t in tabs of w
                try
                    if (tty of t) is target then
                        set selected of t to true
                        set index of w to 1
                        activate
                        return "ok"
                    end if
                end try
            end repeat
        end repeat
    end tell
    return "notfound"
end run
OSA
}

# Activate the iTerm2 session whose tty == $1 (best-effort; the hierarchy,
# `tty of session`, and the select verbs are valid in the modern iTerm2 suite).
_focus_iterm_app() {
  osascript - "$1" 2>>"$ERRFILE" <<'OSA'
on run argv
    set target to item 1 of argv
    tell application "iTerm"
        repeat with w in windows
            repeat with t in tabs of w
                repeat with s in sessions of t
                    try
                        if (tty of s) is target then
                            select w
                            select t
                            select s
                            activate
                            return "ok"
                        end if
                    end try
                end repeat
            end repeat
        end repeat
    end tell
    return "notfound"
end run
OSA
}

# Try the running terminal apps; activate whichever actually owns $1.
_focus_tab() {
  local r
  if _app_running Terminal; then
    r=$(_focus_terminal_app "$1"); [ "$r" = "ok" ] && return 0
  fi
  if _app_running iTerm; then
    r=$(_focus_iterm_app "$1"); [ "$r" = "ok" ] && return 0
  fi
  return 1
}

# --- resolve candidate tab ttys ---------------------------------------------
# Non-tmux: the tty itself. tmux pane: EVERY client attached to the pane's session,
# most-recently-active first — so a multi-client session tries each attached tab
# until one is actually focusable, rather than betting on a single client that may
# not be focusable. A TAB delimiter is used (session names may contain '|' or
# spaces); the opaque #{session_id} is carried for all -t args so special chars in
# a session name never reach tmux as a name.
CANDIDATES="$TTY"
if command -v tmux >/dev/null 2>&1; then
  SID=$({ tmux list-panes -a -F "#{pane_tty}$(printf '\t')#{session_id}" 2>/dev/null || true; } \
        | awk -F'\t' -v t="$TTY" '$1 == t {print $2; exit}')
  if [ -n "${SID:-}" ]; then
    CANDIDATES=$({ tmux list-clients -t "$SID" -F "#{client_activity}$(printf '\t')#{client_tty}" 2>/dev/null || true; } \
                 | sort -rn | cut -f2-)
    if [ -z "$CANDIDATES" ]; then
      SNAME=$({ tmux display-message -p -t "$SID" '#{session_name}' 2>/dev/null || true; })
      echo "tmux session '${SNAME:-$SID}' is detached (no terminal tab to focus); attach it first: tmux attach -t '${SNAME:-$SID}'" >&2
      exit 3
    fi
  fi
fi

# Try each candidate; the heredoc keeps the loop in the current shell so `exit`
# works. The first tab a running terminal app actually owns wins.
while IFS= read -r cand; do
  [ -n "$cand" ] || continue
  if _focus_tab "$cand"; then
    echo "focused $cand"
    exit 0
  fi
done <<EOF
$CANDIDATES
EOF

# Nothing focusable — distinguish a macOS Automation (TCC) denial from a real miss.
if grep -qiE '(-1743|not authoriz|not allowed|Automation)' "$ERRFILE" 2>/dev/null; then
  echo "focus-tty.sh: macOS Automation permission denied. Grant control of Terminal/iTerm in" >&2
  echo "  System Settings > Privacy & Security > Automation, then retry." >&2
  exit 5
fi
echo "no running Terminal.app/iTerm2 tab owns the target (from tty $TTY)" >&2
exit 4
