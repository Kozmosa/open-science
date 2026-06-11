import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "exa_search.py"


def load_module():
    spec = importlib.util.spec_from_file_location("exa_search", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_get_client_raises_when_exa_py_not_installed(monkeypatch):
    exa_search = load_module()
    monkeypatch.setenv("EXA_API_KEY", "test-key")

    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "exa_py":
            raise ImportError("No module named 'exa_py'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    with pytest.raises(RuntimeError, match="exa-py not found"):
        exa_search._get_client()


def test_get_client_raises_when_api_key_missing(monkeypatch):
    exa_search = load_module()
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="EXA_API_KEY"):
        exa_search._get_client()


def test_parse_list_returns_none_for_empty():
    exa_search = load_module()
    assert exa_search._parse_list(None) is None
    assert exa_search._parse_list("") is None


def test_parse_list_splits_comma_separated():
    exa_search = load_module()
    result = exa_search._parse_list("arxiv.org, huggingface.co, github.com")
    assert result == ["arxiv.org", "huggingface.co", "github.com"]


def test_build_content_kwargs_highlights():
    exa_search = load_module()
    result = exa_search._build_content_kwargs("highlights", 4000)
    assert result == {"highlights": {"max_characters": 4000}}


def test_build_content_kwargs_text():
    exa_search = load_module()
    result = exa_search._build_content_kwargs("text", 8000)
    assert result == {"text": {"max_characters": 8000}}


def test_build_content_kwargs_summary():
    exa_search = load_module()
    result = exa_search._build_content_kwargs("summary", 4000)
    assert result == {"summary": True}


def test_build_content_kwargs_none():
    exa_search = load_module()
    result = exa_search._build_content_kwargs("none", 4000)
    assert result == {}


def test_process_result_highlights():
    exa_search = load_module()
    mock_result = SimpleNamespace(
        title="Test Paper",
        url="https://example.com/paper",
        published_date="2025-01-15",
        author="John Doe",
        highlights=["Key finding 1", "Key finding 2"],
    )
    entry = exa_search._process_result(mock_result, "highlights")

    assert entry["title"] == "Test Paper"
    assert entry["url"] == "https://example.com/paper"
    assert entry["published_date"] == "2025-01-15"
    assert entry["author"] == "John Doe"
    assert entry["highlights"] == ["Key finding 1", "Key finding 2"]


def test_process_result_text():
    exa_search = load_module()
    mock_result = SimpleNamespace(
        title="Test Page",
        url="https://example.com",
        text="Full page text content here.",
    )
    entry = exa_search._process_result(mock_result, "text")

    assert entry["title"] == "Test Page"
    assert entry["text"] == "Full page text content here."


def test_process_result_summary():
    exa_search = load_module()
    mock_result = SimpleNamespace(
        title="Test Page",
        url="https://example.com",
        summary="A concise summary of the page.",
    )
    entry = exa_search._process_result(mock_result, "summary")

    assert entry["summary"] == "A concise summary of the page."


def test_process_result_missing_optional_fields():
    exa_search = load_module()
    mock_result = SimpleNamespace(
        title=None,
        url=None,
    )
    entry = exa_search._process_result(mock_result, "none")

    assert entry["title"] == "No Title"
    assert entry["url"] == ""
    assert "published_date" not in entry
    assert "author" not in entry


def test_cli_parser_builds_help_without_traceback():
    exa_search = load_module()
    parser = exa_search._build_parser()
    help_text = parser.format_help()

    assert "search" in help_text
    assert "find-similar" in help_text
    assert "get-contents" in help_text


def test_search_calls_client_with_correct_kwargs(monkeypatch):
    exa_search = load_module()

    captured = {}
    mock_results = [
        SimpleNamespace(
            title="Result 1",
            url="https://example.com/1",
            highlights=["highlight 1"],
        ),
    ]

    class MockResponse:
        results = mock_results

    class MockClient:
        headers = {}

        def search_and_contents(self, **kwargs):
            captured["kwargs"] = kwargs
            return MockResponse()

    monkeypatch.setattr(exa_search, "_get_client", MockClient)

    result = exa_search.search(
        query="test query",
        max_results=5,
        search_type="auto",
        content_mode="highlights",
        max_chars=4000,
        category="research paper",
        include_domains=["arxiv.org"],
    )

    assert captured["kwargs"]["query"] == "test query"
    assert captured["kwargs"]["num_results"] == 5
    assert captured["kwargs"]["type"] == "auto"
    assert captured["kwargs"]["category"] == "research paper"
    assert captured["kwargs"]["include_domains"] == ["arxiv.org"]
    assert result["mode"] == "search"
    assert result["returned"] == 1


def test_main_search_outputs_json(monkeypatch, capsys):
    exa_search = load_module()

    mock_results = [
        SimpleNamespace(
            title="Result 1",
            url="https://example.com/1",
            highlights=["highlight 1"],
        ),
    ]

    class MockResponse:
        results = mock_results

    class MockClient:
        headers = {}

        def search_and_contents(self, **kwargs):
            return MockResponse()

    monkeypatch.setattr(exa_search, "_get_client", MockClient)

    exit_code = exa_search.main(["search", "test query", "--max", "5"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "search"
    assert len(output["data"]) == 1
