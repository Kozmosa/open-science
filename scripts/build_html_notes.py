#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


type FrontmatterValue = str | list[str]
type Frontmatter = dict[str, FrontmatterValue]


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DOCS = ROOT / "docs"
GENERATED_ROOT = ROOT / ".cache" / "html-notes"
GENERATED_DOCS = GENERATED_ROOT / "docs"
MKDOCS_CONFIG = ROOT / "mkdocs.yml"

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
CALLOUT_RE = re.compile(r"^>\s*\[!(?P<kind>[^\]]+)\](?:\s*(?P<title>.*))?$")
FENCE_RE = re.compile(r"^(```|~~~)")


@dataclass(frozen=True)
class Note:
    source_path: Path
    relative_path: Path
    canonical_key: str
    title: str
    aliases: tuple[str, ...]
    body: str


class LinkResolutionError(RuntimeError):
    pass


def parse_simple_frontmatter(block: list[str]) -> Frontmatter:
    meta: Frontmatter = {}
    current_list_key: str | None = None

    for raw_line in block:
        line = raw_line.rstrip()
        if not line.strip():
            continue

        if line.startswith("  - ") and current_list_key:
            existing = meta.get(current_list_key)
            if isinstance(existing, list):
                existing.append(line[4:].strip())
            else:
                meta[current_list_key] = [line[4:].strip()]
            continue

        current_list_key = None
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            meta[key] = []
            current_list_key = key
        else:
            meta[key] = value

    return meta


def normalize_frontmatter(meta: object) -> Frontmatter:
    if not isinstance(meta, dict):
        return {}

    normalized: Frontmatter = {}
    for key, value in meta.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, str):
            normalized[key] = value
            continue
        if isinstance(value, list):
            normalized[key] = [str(item) for item in value if item]

    return normalized


def parse_frontmatter(raw: str) -> tuple[Frontmatter, str]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw

    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            frontmatter_lines = lines[1:idx]
            # Keep a permissive fallback so legacy note metadata still builds when strict YAML parsing fails.
            try:
                meta = normalize_frontmatter(yaml.safe_load("\n".join(frontmatter_lines)))
            except yaml.YAMLError:
                meta = parse_simple_frontmatter(frontmatter_lines)
            body = "\n".join(lines[idx + 1 :])
            if raw.endswith("\n"):
                body += "\n"
            return meta, body

    return {}, raw


def extract_title(body: str, fallback: Path) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback.stem.replace("-", " ")


def load_notes() -> tuple[list[Note], dict[str, str]]:
    notes: list[Note] = []
    lookup: dict[str, str] = {}

    for path in sorted(SOURCE_DOCS.rglob("*.md")):
        rel = path.relative_to(SOURCE_DOCS)
        canonical_key = rel.with_suffix("").as_posix()
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)
        title = extract_title(body, rel)
        raw_aliases = meta.get("aliases", [])
        if isinstance(raw_aliases, str):
            aliases = (raw_aliases,)
        else:
            aliases = tuple(str(item) for item in raw_aliases if item)
        note = Note(
            source_path=path,
            relative_path=rel,
            canonical_key=canonical_key,
            title=title,
            aliases=aliases,
            body=body,
        )
        notes.append(note)
        lookup[canonical_key] = canonical_key
        for alias in aliases:
            lookup[alias] = canonical_key

    return notes, lookup


def convert_callouts(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_fence = False
    idx = 0

    while idx < len(lines):
        line = lines[idx]
        if FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            out.append(line)
            idx += 1
            continue

        match = CALLOUT_RE.match(line) if not in_fence else None
        if not match:
            out.append(line)
            idx += 1
            continue

        kind = match.group("kind").strip().lower()
        title = (match.group("title") or "").strip()
        out.append(f'!!! {kind} "{title}"' if title else f'!!! {kind} ""')
        idx += 1

        body_lines: list[str] = []
        while idx < len(lines):
            current = lines[idx]
            if current.startswith("> "):
                body_lines.append(current[2:])
                idx += 1
                continue
            if current == ">":
                body_lines.append("")
                idx += 1
                continue
            break

        if not body_lines:
            out.append("    ")
        else:
            for body_line in body_lines:
                out.append(f"    {body_line}" if body_line else "")

    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def convert_markdown_link(match: re.Match[str], current_path: Path) -> str:
    label, href = match.groups()
    if href.startswith(("http://", "https://", "#", "mailto:")):
        return match.group(0)

    resolved = (current_path.parent / href).resolve()
    if resolved.is_relative_to(SOURCE_DOCS.resolve()):
        return match.group(0)

    # Links escaping docs are rendered as inline code because the generated site cannot resolve repo-only paths.
    return f"`{label}`"


def relative_markdown_href(source: Path, target: Path) -> str:
    source_dir = source.parent
    return Path(os.path.relpath(target, source_dir)).as_posix()


def convert_note_body(
    note: Note,
    note_by_key: dict[str, Note],
    alias_lookup: dict[str, str],
) -> tuple[str, list[str]]:
    converted_callouts = convert_callouts(note.body)
    note_with_converted_callouts = Note(
        source_path=note.source_path,
        relative_path=note.relative_path,
        canonical_key=note.canonical_key,
        title=note.title,
        aliases=note.aliases,
        body=converted_callouts,
    )
    return convert_wikilinks(note_with_converted_callouts, note_by_key, alias_lookup)


def convert_wikilinks(
    note: Note,
    note_by_key: dict[str, Note],
    alias_lookup: dict[str, str],
) -> tuple[str, list[str]]:
    lines = note.body.splitlines()
    out: list[str] = []
    outgoing: list[str] = []
    in_fence = False

    for line in lines:
        stripped = line.strip()
        if FENCE_RE.match(stripped):
            in_fence = not in_fence
            out.append(line)
            continue

        if in_fence:
            out.append(line)
            continue

        def replace_wikilink(match: re.Match[str]) -> str:
            raw_target, explicit_label = match.groups()
            target = raw_target.strip()
            canonical_key = alias_lookup.get(target, target)
            target_note = note_by_key.get(canonical_key)
            if target_note is None:
                raise LinkResolutionError(
                    f"Unresolved wikilink '{target}' in {note.relative_path.as_posix()}"
                )

            outgoing.append(target_note.canonical_key)
            label = explicit_label or target_note.title
            href = relative_markdown_href(
                note.relative_path,
                target_note.relative_path.with_suffix(".md"),
            )
            return f"[{label}]({href})"

        line = WIKILINK_RE.sub(replace_wikilink, line)
        line = MARKDOWN_LINK_RE.sub(
            lambda match: convert_markdown_link(
                match,
                SOURCE_DOCS / note.relative_path,
            ),
            line,
        )
        out.append(line)

    return "\n".join(out) + ("\n" if note.body.endswith("\n") else ""), outgoing


def append_backlinks(
    text: str,
    note: Note,
    backlinks: dict[str, set[str]],
    note_by_key: dict[str, Note],
) -> str:
    incoming = backlinks.get(note.canonical_key, set())
    if not incoming:
        return text

    # Backlinks are appended only in generated output so source notes stay untouched while the site gains navigation.
    lines = [text.rstrip(), "", "## 反向链接", ""]
    for key in sorted(incoming, key=lambda item: note_by_key[item].title):
        target_note = note_by_key[key]
        href_str = relative_markdown_href(
            note.relative_path,
            target_note.relative_path.with_suffix(".md"),
        )
        lines.append(f"- [{target_note.title}]({href_str})")

    return "\n".join(lines) + "\n"


def collect_processed_notes(
    notes: list[Note],
    alias_lookup: dict[str, str],
) -> tuple[dict[str, str], dict[str, set[str]]]:
    note_by_key = {note.canonical_key: note for note in notes}
    backlinks: dict[str, set[str]] = {}
    processed: dict[str, str] = {}

    for note in notes:
        converted, outgoing = convert_note_body(note, note_by_key, alias_lookup)
        processed[note.canonical_key] = converted
        for target in outgoing:
            backlinks.setdefault(target, set()).add(note.canonical_key)

    return processed, backlinks


def write_processed_markdown(
    notes: list[Note],
    processed: dict[str, str],
    backlinks: dict[str, set[str]],
) -> None:
    note_by_key = {note.canonical_key: note for note in notes}
    for note in notes:
        content = append_backlinks(processed[note.canonical_key], note, backlinks, note_by_key)
        destination = GENERATED_DOCS / note.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def copy_non_markdown_assets() -> None:
    for path in sorted(SOURCE_DOCS.rglob("*")):
        if not path.is_file() or path.suffix.lower() == ".md":
            continue
        destination = GENERATED_DOCS / path.relative_to(SOURCE_DOCS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def build_processed_docs() -> None:
    notes, alias_lookup = load_notes()
    processed, backlinks = collect_processed_notes(notes, alias_lookup)

    shutil.rmtree(GENERATED_ROOT, ignore_errors=True)
    GENERATED_DOCS.mkdir(parents=True, exist_ok=True)

    write_processed_markdown(notes, processed, backlinks)
    copy_non_markdown_assets()


def run_mkdocs(command: str) -> int:
    cmd = [
        sys.executable,
        "-m",
        "mkdocs",
        command,
        "--config-file",
        str(MKDOCS_CONFIG),
    ]
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Build HTML notes from Obsidian-style Markdown.")
    parser.add_argument(
        "command",
        choices=("build", "serve"),
        help="Build a static site or start a local preview server.",
    )
    args = parser.parse_args()

    try:
        build_processed_docs()
    except LinkResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return run_mkdocs(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
