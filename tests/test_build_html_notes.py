from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_html_notes.py"


@pytest.fixture(scope="module")
def build_html_notes() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("build_html_notes", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class NoteLike:
    source_path: Path
    relative_path: Path
    canonical_key: str
    title: str
    aliases: tuple[str, ...]
    body: str


def make_note(
    build_html_notes: types.ModuleType,
    *,
    relative_path: str = "notes/current.md",
    canonical_key: str = "notes/current",
    title: str = "Current Note",
    aliases: tuple[str, ...] = (),
    body: str,
) -> NoteLike:
    return build_html_notes.Note(
        source_path=Path("/tmp/source") / relative_path,
        relative_path=Path(relative_path),
        canonical_key=canonical_key,
        title=title,
        aliases=aliases,
        body=body,
    )


def test_parse_frontmatter_parses_valid_yaml_list_and_scalar(
    build_html_notes: types.ModuleType,
) -> None:
    raw = """---
aliases:
  - Alpha
  - Beta
tags:
  - docs
source_repo: scholar-agent
source_path: docs/example.md
---
# Example
"""

    meta, body = build_html_notes.parse_frontmatter(raw)

    assert meta == {
        "aliases": ["Alpha", "Beta"],
        "tags": ["docs"],
        "source_repo": "scholar-agent",
        "source_path": "docs/example.md",
    }
    assert body == "# Example\n"


def test_parse_frontmatter_falls_back_to_simple_parser_on_yaml_error(
    build_html_notes: types.ModuleType,
) -> None:
    raw = """---
aliases:
  - Alpha
source_repo: [unterminated
source_path: docs/example.md
---
Body\n"""

    meta, body = build_html_notes.parse_frontmatter(raw)

    assert meta == {
        "aliases": ["Alpha"],
        "source_repo": "[unterminated",
        "source_path": "docs/example.md",
    }
    assert body == "Body\n"


def test_convert_callouts_translates_obsidian_syntax(
    build_html_notes: types.ModuleType,
) -> None:
    source = "> [!TIP] Helpful title\n> first line\n> second line\n"

    converted = build_html_notes.convert_callouts(source)

    assert converted == '!!! tip "Helpful title"\n    first line\n    second line\n'


def test_convert_callouts_skips_fenced_code_blocks(
    build_html_notes: types.ModuleType,
) -> None:
    source = "```md\n> [!TIP] keep literal\n> body\n```\n"

    converted = build_html_notes.convert_callouts(source)

    assert converted == source


def test_convert_callouts_preserves_empty_callout_semantics(
    build_html_notes: types.ModuleType,
) -> None:
    source = "> [!NOTE]\n"

    converted = build_html_notes.convert_callouts(source)

    assert converted.startswith('!!! note ""\n')
    assert converted.endswith("\n")
    assert len(converted.splitlines()) == 2
    assert converted.splitlines()[1].strip() == ""


def test_convert_wikilinks_resolves_canonical_target(
    build_html_notes: types.ModuleType,
) -> None:
    note = make_note(build_html_notes, body="See [[notes/target]].\n")
    target = make_note(
        build_html_notes,
        relative_path="notes/target.md",
        canonical_key="notes/target",
        title="Target Title",
        body="# Target\n",
    )

    converted, outgoing = build_html_notes.convert_wikilinks(
        note,
        {note.canonical_key: note, target.canonical_key: target},
        {"notes/current": "notes/current", "notes/target": "notes/target"},
    )

    assert converted == "See [Target Title](target.md).\n"
    assert outgoing == ["notes/target"]


def test_convert_wikilinks_resolves_alias_targets(
    build_html_notes: types.ModuleType,
) -> None:
    note = make_note(build_html_notes, body="See [[Alias Name]].\n")
    target = make_note(
        build_html_notes,
        relative_path="notes/target.md",
        canonical_key="notes/target",
        title="Target Title",
        aliases=("Alias Name",),
        body="# Target\n",
    )

    converted, outgoing = build_html_notes.convert_wikilinks(
        note,
        {note.canonical_key: note, target.canonical_key: target},
        {
            "notes/current": "notes/current",
            "notes/target": "notes/target",
            "Alias Name": "notes/target",
        },
    )

    assert converted == "See [Target Title](target.md).\n"
    assert outgoing == ["notes/target"]


def test_convert_wikilinks_preserves_explicit_labels(
    build_html_notes: types.ModuleType,
) -> None:
    note = make_note(build_html_notes, body="See [[notes/target|Custom Label]].\n")
    target = make_note(
        build_html_notes,
        relative_path="notes/target.md",
        canonical_key="notes/target",
        title="Target Title",
        body="# Target\n",
    )

    converted, outgoing = build_html_notes.convert_wikilinks(
        note,
        {note.canonical_key: note, target.canonical_key: target},
        {"notes/current": "notes/current", "notes/target": "notes/target"},
    )

    assert converted == "See [Custom Label](target.md).\n"
    assert outgoing == ["notes/target"]


def test_convert_wikilinks_raises_for_unresolved_targets(
    build_html_notes: types.ModuleType,
) -> None:
    note = make_note(build_html_notes, body="Broken [[missing-note]].\n")

    with pytest.raises(
        build_html_notes.LinkResolutionError,
        match="Unresolved wikilink 'missing-note'",
    ):
        build_html_notes.convert_wikilinks(
            note,
            {note.canonical_key: note},
            {"notes/current": "notes/current"},
        )


def test_convert_wikilinks_skips_fenced_code_blocks(
    build_html_notes: types.ModuleType,
) -> None:
    note = make_note(build_html_notes, body="```md\n[[notes/target]]\n```\n")
    target = make_note(
        build_html_notes,
        relative_path="notes/target.md",
        canonical_key="notes/target",
        title="Target Title",
        body="# Target\n",
    )

    converted, outgoing = build_html_notes.convert_wikilinks(
        note,
        {note.canonical_key: note, target.canonical_key: target},
        {"notes/current": "notes/current", "notes/target": "notes/target"},
    )

    assert converted == note.body
    assert outgoing == []


def test_convert_wikilinks_preserves_docs_internal_markdown_links(
    build_html_notes: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_docs = tmp_path / "docs"
    monkeypatch.setattr(build_html_notes, "SOURCE_DOCS", source_docs)
    note = make_note(build_html_notes, body="See [Guide](../shared/guide.md).\n")

    converted, outgoing = build_html_notes.convert_wikilinks(
        note,
        {note.canonical_key: note},
        {"notes/current": "notes/current"},
    )

    assert converted == note.body
    assert outgoing == []


def test_convert_wikilinks_downgrades_repo_relative_links_outside_docs(
    build_html_notes: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_docs = tmp_path / "docs"
    monkeypatch.setattr(build_html_notes, "SOURCE_DOCS", source_docs)
    note = make_note(build_html_notes, body="See [Project Root](../../README.md).\n")

    converted, outgoing = build_html_notes.convert_wikilinks(
        note,
        {note.canonical_key: note},
        {"notes/current": "notes/current"},
    )

    assert converted == "See `Project Root`.\n"
    assert outgoing == []


@pytest.mark.parametrize(
    ("href", "label"),
    [
        ("http://example.com", "HTTP"),
        ("https://example.com", "HTTPS"),
        ("#section", "Anchor"),
        ("mailto:test@example.com", "Mail"),
    ],
)
def test_convert_wikilinks_preserves_external_anchor_and_mailto_links(
    build_html_notes: types.ModuleType, href: str, label: str
) -> None:
    note = make_note(build_html_notes, body=f"Keep [{label}]({href}).\\n")

    converted, outgoing = build_html_notes.convert_wikilinks(
        note,
        {note.canonical_key: note},
        {"notes/current": "notes/current"},
    )

    assert converted == note.body
    assert outgoing == []


def test_append_backlinks_omits_section_without_incoming_links(
    build_html_notes: types.ModuleType,
) -> None:
    note = make_note(build_html_notes, body="# Current\n")

    appended = build_html_notes.append_backlinks(
        "# Current\n",
        note,
        {},
        {note.canonical_key: note},
    )

    assert appended == "# Current\n"


def test_append_backlinks_adds_section_for_incoming_links_in_stable_order(
    build_html_notes: types.ModuleType,
) -> None:
    note = make_note(build_html_notes, body="# Current\n")
    zeta = make_note(
        build_html_notes,
        relative_path="notes/zeta.md",
        canonical_key="notes/zeta",
        title="Zeta Note",
        body="# Zeta\n",
    )
    alpha = make_note(
        build_html_notes,
        relative_path="notes/alpha.md",
        canonical_key="notes/alpha",
        title="Alpha Note",
        body="# Alpha\n",
    )
    note_by_key = {
        note.canonical_key: note,
        zeta.canonical_key: zeta,
        alpha.canonical_key: alpha,
    }

    appended = build_html_notes.append_backlinks(
        "# Current\n",
        note,
        {note.canonical_key: {zeta.canonical_key, alpha.canonical_key}},
        note_by_key,
    )

    assert appended == (
        "# Current\n\n## 反向链接\n\n- [Alpha Note](alpha.md)\n- [Zeta Note](zeta.md)\n"
    )


def test_build_processed_docs_writes_processed_markdown_and_copies_assets(
    build_html_notes: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_docs = tmp_path / "docs"
    generated_root = tmp_path / ".cache" / "html-notes"
    generated_docs = generated_root / "docs"
    notes_dir = source_docs / "notes"
    assets_dir = source_docs / "assets"
    notes_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)

    (notes_dir / "target.md").write_text("# Target\n", encoding="utf-8")
    (notes_dir / "current.md").write_text(
        "# Current\n\n> [!TIP] Helpful title\n> first line\n\nSee [[notes/target]].\n",
        encoding="utf-8",
    )
    asset_bytes = b"\x89PNG\r\n\x1a\ncontract-test"
    (assets_dir / "diagram.png").write_bytes(asset_bytes)

    monkeypatch.setattr(build_html_notes, "SOURCE_DOCS", source_docs)
    monkeypatch.setattr(build_html_notes, "GENERATED_ROOT", generated_root)
    monkeypatch.setattr(build_html_notes, "GENERATED_DOCS", generated_docs)

    build_html_notes.build_processed_docs()

    generated_current = (generated_docs / "notes" / "current.md").read_text(encoding="utf-8")
    generated_target = (generated_docs / "notes" / "target.md").read_text(encoding="utf-8")

    assert '!!! tip "Helpful title"' in generated_current
    assert "    first line" in generated_current
    assert "See [Target](target.md)." in generated_current
    assert generated_current.endswith("\n")
    assert generated_target == "# Target\n\n## 反向链接\n\n- [Current](current.md)\n"
    assert (generated_docs / "assets" / "diagram.png").read_bytes() == asset_bytes
