"""Regression coverage for viewer-safe durable Task output projections."""

from __future__ import annotations

import json

import pytest

from ainrf.domain.output_redaction import (
    redact_task_item_payload_for_viewer,
    redact_task_output_for_viewer,
)

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


def test_item_payload_redaction_recurses_through_dicts_lists_and_strings() -> None:
    payload = {
        "message": "shared dialogue",
        "credential": "credential-secret",
        "nested": [
            {"token": "token-secret"},
            "Authorization: Bearer authorization-secret",
            "/home/ainrf_tenants/alice/workspace/output.txt",
        ],
    }

    redacted = redact_task_item_payload_for_viewer(payload)

    assert redacted == {
        "message": "shared dialogue",
        "credential": "[REDACTED]",
        "nested": [
            {"token": "[REDACTED]"},
            "Authorization: [REDACTED]",
            "[REDACTED_PATH]",
        ],
    }
    assert payload["credential"] == "credential-secret"


def test_authorization_redaction_is_idempotent_for_plain_and_nested_strings() -> None:
    authorization = "Authorization: Bearer authorization-secret"
    assert redact_task_output_for_viewer(authorization) == "Authorization: [REDACTED]"
    assert redact_task_output_for_viewer(redact_task_output_for_viewer(authorization)) == (
        "Authorization: [REDACTED]"
    )

    payload = {
        "headers": {"Authorization": "Bearer authorization-secret"},
        "nested": [authorization, {"content": authorization}],
    }
    redacted_once = redact_task_item_payload_for_viewer(payload)
    redacted_twice = redact_task_item_payload_for_viewer(redacted_once)

    assert "authorization-secret" not in json.dumps(redacted_once)
    assert redacted_twice == redacted_once
