"""Tests for ainrf.security.redaction."""

from __future__ import annotations

from ainrf.security.redaction import REDACTED_KEYS, redact_dict, redact_headers, redact_query_string
import pytest

pytestmark = [pytest.mark.middleware]


class TestRedactHeaders:
    def test_masks_authorization(self) -> None:
        result = redact_headers({"Authorization": "Bearer xyz"})
        assert result == {"Authorization": "[REDACTED]"}

    def test_masks_api_key_case_insensitive(self) -> None:
        result = redact_headers({"x-api-key": "abc123"})
        assert result["x-api-key"] == "[REDACTED]"

    def test_passes_through_safe_headers(self) -> None:
        headers = {"Content-Type": "application/json", "Accept": "text/html"}
        assert redact_headers(headers) == headers

    def test_empty_dict(self) -> None:
        assert redact_headers({}) == {}

    def test_masks_cookie(self) -> None:
        result = redact_headers({"Cookie": "session=abc"})
        assert result["Cookie"] == "[REDACTED]"


class TestRedactQueryString:
    def test_masks_token(self) -> None:
        result = redact_query_string("token=secret&foo=bar")
        assert "%5BREDACTED%5D" in result or "[REDACTED]" in result
        assert "secret" not in result
        assert "foo=bar" in result

    def test_no_sensitive_params(self) -> None:
        qs = "page=1&limit=10"
        assert redact_query_string(qs) == qs

    def test_empty_string(self) -> None:
        assert redact_query_string("") == ""

    def test_masks_api_key(self) -> None:
        result = redact_query_string("api_key=mykey&action=list")
        assert "mykey" not in result
        assert "REDACTED" in result.upper() or "REDACTED" in result


class TestRedactDict:
    def test_masks_password(self) -> None:
        result = redact_dict({"username": "alice", "password": "hunter2"})
        assert result["username"] == "alice"
        assert result["password"] == "[REDACTED]"

    def test_nested_dict(self) -> None:
        result = redact_dict({"user": {"name": "bob", "api_key": "abc"}})
        assert result["user"]["name"] == "bob"
        assert result["user"]["api_key"] == "[REDACTED]"

    def test_custom_keys(self) -> None:
        result = redact_dict(
            {"secret": "abc", "name": "ok"},
            keys=frozenset({"secret"}),
        )
        assert result["secret"] == "[REDACTED]"
        assert result["name"] == "ok"

    def test_list_values(self) -> None:
        result = redact_dict({"items": [{"token": "x"}, {"safe": "y"}]})
        assert result["items"][0]["token"] == "[REDACTED]"
        assert result["items"][1]["safe"] == "y"

    def test_no_sensitive_keys(self) -> None:
        data = {"name": "alice", "age": 30}
        assert redact_dict(data) == data


class TestRedactedKeys:
    def test_includes_common_secrets(self) -> None:
        for key in ("authorization", "cookie", "password", "token", "api_key"):
            assert key in REDACTED_KEYS
