"""Regression coverage for viewer-safe durable Task output projections."""

from __future__ import annotations

import json

import pytest

from ainrf.domain.output_redaction import redact_task_output_for_viewer

pytestmark = [pytest.mark.unit]


def test_redaction_recursively_inspects_json_serialized_inside_content() -> None:
    nested_secret = "nested-viewer-secret"
    content = json.dumps(
        {
            "role": "tool",
            "content": json.dumps({"keyValue": nested_secret}),
        },
        separators=(",", ":"),
    )

    rendered = redact_task_output_for_viewer(content)

    assert nested_secret not in rendered
    assert "[REDACTED]" in rendered
    decoded = json.loads(rendered)
    assert json.loads(decoded["content"])["keyValue"] == "[REDACTED]"


def test_redaction_treats_camel_case_sensitive_assignments_as_plain_text() -> None:
    rendered = redact_task_output_for_viewer("keyValue: plain-viewer-secret")

    assert "plain-viewer-secret" not in rendered
    assert rendered == "keyValue: [REDACTED]"


def test_redaction_fails_closed_for_deeply_nested_embedded_json() -> None:
    nested_secret = "deeply-nested-viewer-secret"
    embedded: object = nested_secret
    for _ in range(10):
        embedded = json.dumps({"payload": embedded}, separators=(",", ":"))

    rendered = redact_task_output_for_viewer(
        json.dumps({"role": "tool", "content": embedded}, separators=(",", ":"))
    )

    assert nested_secret not in rendered
    assert "[REDACTED]" in rendered
