#!/usr/bin/env python3
"""Unit tests for mcp-servers/feishu-bridge/server.py.

Tests cover the pure-Python logic in the bridge server:
- Reply store management (receive_reply, poll_reply)
- Card payload construction
- Query-string parsing used by the HTTP handler
- HTTP handler routing (via a lightweight fake handler)

No real Feishu credentials or lark-oapi installation is required.
"""

import io
import json
import os
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

from tests._feishu_bridge_helpers import (
    build_card_payload,
    parse_query_string,
    poll_reply,
    receive_reply,
    register_message,
    reset_store,
)


class TestReplyStore(unittest.TestCase):
    """Test the in-memory reply store used for long-polling."""

    def setUp(self):
        reset_store()

    def test_poll_unknown_message_returns_error(self):
        result = poll_reply("unknown-id", timeout=0)
        self.assertIn("error", result)
        self.assertIn("unknown message_id", result["error"])

    def test_receive_then_poll_returns_reply(self):
        register_message("msg-001")
        receive_reply("msg-001", "user said hello")
        result = poll_reply("msg-001", timeout=1)
        self.assertIn("reply", result)
        self.assertEqual(result["reply"], "user said hello")

    def test_poll_before_reply_with_zero_timeout_returns_timeout(self):
        register_message("msg-002")
        # Don't call receive_reply — should time out immediately
        result = poll_reply("msg-002", timeout=0)
        self.assertIn("timeout", result)
        self.assertTrue(result["timeout"])

    def test_receive_without_registration_is_safe(self):
        """receive_reply on an unregistered message_id should be a no-op."""
        receive_reply("ghost-id", "ignored")  # should not raise

    def test_poll_consumes_reply(self):
        """After poll_reply returns the reply, it is removed from the store."""
        register_message("msg-003")
        receive_reply("msg-003", "text")
        poll_reply("msg-003", timeout=1)
        # Second poll should return error (message already consumed)
        result = poll_reply("msg-003", timeout=0)
        self.assertIn("error", result)

    def test_concurrent_receive_and_poll(self):
        """A reply delivered from another thread should wake the polling thread."""
        register_message("msg-004")
        results = []

        def poller():
            results.append(poll_reply("msg-004", timeout=2))

        t = threading.Thread(target=poller)
        t.start()
        # Give the poller thread a moment to start waiting
        threading.Event().wait(0.05)
        receive_reply("msg-004", "async reply")
        t.join(timeout=3)
        self.assertEqual(len(results), 1)
        self.assertIn("reply", results[0])
        self.assertEqual(results[0]["reply"], "async reply")

    def test_multiple_independent_messages(self):
        """Multiple concurrent messages should not interfere with each other."""
        for mid in ("a", "b", "c"):
            register_message(mid)
        receive_reply("b", "reply-b")
        result_b = poll_reply("b", timeout=1)
        result_a = poll_reply("a", timeout=0)
        self.assertEqual(result_b["reply"], "reply-b")
        self.assertIn("timeout", result_a)

    def test_reset_clears_all_state(self):
        register_message("x")
        reset_store()
        result = poll_reply("x", timeout=0)
        self.assertIn("error", result)


class TestBuildCardPayload(unittest.TestCase):
    """Test the card JSON structure produced for Feishu interactive messages."""

    def test_card_has_header_and_elements(self):
        card = build_card_payload("My Title", "Some **body**")
        self.assertIn("header", card)
        self.assertIn("elements", card)

    def test_title_is_plain_text_tag(self):
        card = build_card_payload("Hello", "World")
        header_title = card["header"]["title"]
        self.assertEqual(header_title["tag"], "plain_text")
        self.assertEqual(header_title["content"], "Hello")

    def test_default_color_is_blue(self):
        card = build_card_payload("T", "B")
        self.assertEqual(card["header"]["template"], "blue")

    def test_custom_color_is_preserved(self):
        card = build_card_payload("T", "B", color="red")
        self.assertEqual(card["header"]["template"], "red")

    def test_body_is_markdown_element(self):
        card = build_card_payload("T", "**bold text**")
        elements = card["elements"]
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["tag"], "markdown")
        self.assertEqual(elements[0]["content"], "**bold text**")

    def test_card_is_json_serialisable(self):
        card = build_card_payload("Title", "Body content with unicode: 你好")
        serialised = json.dumps(card)
        self.assertIsInstance(serialised, str)

    def test_empty_body_is_allowed(self):
        card = build_card_payload("Title", "")
        self.assertEqual(card["elements"][0]["content"], "")


class TestParseQueryString(unittest.TestCase):
    """Test query-string parsing used in the HTTP handler's /poll route."""

    def test_no_query_string_returns_empty(self):
        self.assertEqual(parse_query_string("/poll"), {})

    def test_single_param(self):
        params = parse_query_string("/poll?message_id=abc123")
        self.assertEqual(params["message_id"], "abc123")

    def test_multiple_params(self):
        params = parse_query_string("/poll?message_id=abc&timeout=60")
        self.assertEqual(params["message_id"], "abc")
        self.assertEqual(params["timeout"], "60")

    def test_param_without_value_is_skipped(self):
        params = parse_query_string("/poll?message_id=abc&broken")
        self.assertIn("message_id", params)
        self.assertNotIn("broken", params)

    def test_value_can_contain_equals(self):
        """Values with embedded '=' (e.g. base64) should not be truncated."""
        params = parse_query_string("/poll?token=abc=def")
        self.assertEqual(params["token"], "abc=def")

    def test_health_path_returns_empty(self):
        self.assertEqual(parse_query_string("/health"), {})


class TestHttpHandlerRouting(unittest.TestCase):
    """
    Smoke-test the BridgeHandler routing logic via a mock server.

    Rather than spinning up a real HTTPServer (which would require lark-oapi
    and real credentials), we instantiate BridgeHandler with a mock request
    and verify that it returns the expected JSON for each route.
    """

    def _make_handler(self, method, path, body=None):
        """
        Create a BridgeHandler-like object that routes without real I/O.

        We import the handler class directly but stub out any Feishu client
        calls and the binary write calls.
        """
        # We must mock lark_oapi before the server module is imported
        lark_mock = MagicMock()
        lark_mock.Client.builder.return_value.app_id.return_value\
            .app_secret.return_value.build.return_value = MagicMock()

        modules_to_patch = {
            "lark_oapi": lark_mock,
            "lark_oapi.api.im.v1": MagicMock(),
        }

        with patch.dict("sys.modules", modules_to_patch):
            # Patch env vars so the module-level checks don't sys.exit
            env_patch = {
                "FEISHU_APP_ID": "test-app-id",
                "FEISHU_APP_SECRET": "test-secret",
                "FEISHU_USER_ID": "test-user-id",
            }
            with patch.dict(os.environ, env_patch):
                # Force re-import
                import importlib
                import importlib.util
                server_path = os.path.join(
                    os.path.dirname(__file__), "..", "mcp-servers",
                    "feishu-bridge", "server.py"
                )
                spec = importlib.util.spec_from_file_location("feishu_server", server_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

        handler_cls = mod.BridgeHandler
        responses = []

        # Create a handler with mocked request infrastructure
        handler = handler_cls.__new__(handler_cls)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body.encode()) if body else 0)}

        raw_body = (body or "").encode()
        handler.rfile = io.BytesIO(raw_body)

        written = []

        def fake_json_response(data, status=200):
            responses.append((status, data))

        handler._json_response = fake_json_response

        if method == "GET":
            handler.do_GET()
        elif method == "POST":
            handler.do_POST()

        return responses

    def test_health_endpoint_returns_ok(self):
        responses = self._make_handler("GET", "/health")
        self.assertEqual(len(responses), 1)
        status, data = responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")

    def test_unknown_get_returns_404(self):
        responses = self._make_handler("GET", "/unknown")
        self.assertEqual(len(responses), 1)
        status, data = responses[0]
        self.assertEqual(status, 404)

    def test_poll_without_message_id_returns_400(self):
        responses = self._make_handler("GET", "/poll")
        self.assertEqual(len(responses), 1)
        status, _ = responses[0]
        self.assertEqual(status, 400)

    def test_unknown_post_returns_404(self):
        responses = self._make_handler("POST", "/unknown", body="{}")
        self.assertEqual(len(responses), 1)
        status, data = responses[0]
        self.assertEqual(status, 404)

    def test_reply_without_message_id_returns_400(self):
        responses = self._make_handler(
            "POST", "/reply", body=json.dumps({"text": "hi"})
        )
        self.assertEqual(len(responses), 1)
        status, data = responses[0]
        self.assertEqual(status, 400)

    def test_reply_with_message_id_returns_ok(self):
        # Pre-register a message_id in the global reply store
        reset_store()
        register_message("handler-msg-01")

        body = json.dumps({"message_id": "handler-msg-01", "text": "confirmed"})
        responses = self._make_handler("POST", "/reply", body=body)
        self.assertEqual(len(responses), 1)
        status, data = responses[0]
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))


if __name__ == "__main__":
    unittest.main()
