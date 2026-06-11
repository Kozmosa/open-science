"""
Helper module that extracts testable functions from feishu-bridge/server.py
without requiring lark-oapi to be installed or real Feishu credentials.

Only the pure-logic pieces (reply store management, HTTP handler helpers)
are reproduced here so tests can import them cleanly.
"""

import json
import threading

# --- Reply Store (mirrors server.py) ---
reply_store = {}
reply_lock = threading.Lock()
reply_events = {}


def receive_reply(message_id: str, text: str):
    """Called when a user replies. Sets the event so poll_reply can return."""
    with reply_lock:
        if message_id in reply_store:
            reply_store[message_id] = text
            reply_events[message_id].set()


def poll_reply(message_id: str, timeout: int = 300) -> dict:
    """Wait for a user reply to a specific message."""
    with reply_lock:
        event = reply_events.get(message_id)

    if not event:
        return {"error": "unknown message_id"}

    got_reply = event.wait(timeout=timeout)

    with reply_lock:
        reply = reply_store.pop(message_id, None)
        reply_events.pop(message_id, None)

    if got_reply and reply:
        return {"reply": reply}
    else:
        return {"timeout": True}


def register_message(message_id: str):
    """Register a message_id so poll_reply can wait for its reply."""
    with reply_lock:
        reply_events[message_id] = threading.Event()
        reply_store[message_id] = None


def reset_store():
    """Clear the reply store between tests."""
    with reply_lock:
        reply_store.clear()
        reply_events.clear()


def build_card_payload(title: str, body: str, color: str = "blue") -> dict:
    """Reproduce the card JSON structure from send_card()."""
    return {
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        },
        "elements": [
            {"tag": "markdown", "content": body}
        ],
    }


def parse_query_string(path: str) -> dict:
    """Parse query parameters from a URL path, as done in BridgeHandler.do_GET."""
    params = {}
    if "?" in path:
        query = path.split("?", 1)[1]
        for pair in query.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k] = v
    return params
