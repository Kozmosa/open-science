# Container Operator Guardrails

These guardrails apply to ALL Claude Code sessions spawned by the OpenScience
platform (both `claude` CLI and Agent SDK engines). They are injected via
`~/.claude/CLAUDE.md` at container startup so they survive image rebuilds.

## File Reading

- When reading PDF files with the `Read` tool, prefer splitting into page
  ranges (e.g. `pages="1-10"`, `pages="11-20"`) rather than reading the
  entire PDF at once. A single PDF extraction easily exceeds 1 MB of text
  and will cause the SDK transport layer to fail.
- For PDFs larger than 100 pages, always read in chunks of at most 20 pages
  per `Read` call.
- If a `Read` tool call returns a JSON decode / buffer overflow error,
  reduce the page range and retry immediately — do not abandon the task.
- When encountering text with many formulas or tables (MinerU /
  pdfplumber), the extracted text can be much larger than the raw PDF byte
  size. Budget conservatively: a 2 MB PDF may become 5+ MB of extracted
  text.

## Large Outputs

- Tool outputs (especially from `Read` on PDFs, `Bash` commands producing
  large stdout, or `Grep` over large codebases) may be truncated at the
  transport layer. The JSON message buffer between the SDK and the CLI is
  30 MB (1 MB by default — raised by OpenScience).
- Prefer redirecting large `Bash` command output to a file, then reading
  the file in chunks with `Read` (using `limit` or page ranges).
- Use `--head` / `--tail` / `head` / `tail` to preview large files rather
  than reading the entire file at once.
- When running `python` or other scripts, write results to a JSON/text
  file on disk and then read that file with `Read`, rather than relying
  on stdout being captured in the tool result.

## Error Recovery

- A `Failed to decode JSON: JSON message exceeded maximum buffer size`
  error on stderr means the transport layer dropped a message. The
  underlying session is NOT dead — just the last tool output was too
  large. Reduce the scope of the last operation and retry.
- Do NOT treat a single large-output failure as a session-ending error.
  The session transcript prior to the failure is intact and the next
  prompt will resume normally.

## Claude Code CLI Behavior

- The OpenScience platform spawns the Claude Code CLI via the Agent SDK's
  `--input-format stream-json --output-format stream-json` protocol.
- Always produce valid JSON on stdout — non-JSON lines (e.g. raw
  stderr mixed into stdout) may be dropped by the SDK parser.
- If you see `[stderr] ...` lines in the conversation, they come from
  the CLI subprocess's stderr pipe and indicate a transport-level
  issue that needs attention.
