from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import requests

from radar.collector import _collect_single, collect_sources
from radar.config_loader import load_category_config
from radar.exceptions import NetworkError, SourceError
from radar.mcp_source import _jsonrpc_result, _response_json, collect_mcp_server_source
from radar.models import Source


HANGING_MCP_SERVER = "import time; time.sleep(30)"


def _mcp_source(repository: str) -> Source:
    category = load_category_config("commerce_mcp")
    matches = [
        source
        for source in category.sources
        if source.type == "mcp_server" and source.config.get("repository") == repository
    ]
    assert len(matches) == 1
    return matches[0]


def test_mcp_server_source_invokes_allowlisted_tool(monkeypatch) -> None:
    source = Source(
        name="Example MCP",
        type="mcp_server",
        url="mcp://example",
        config={
            "transport": "stdio",
            "command": "example-mcp",
            "tools": [{"name": "search", "arguments": {"query": "radar"}}],
            "timeout_seconds": 3,
            "max_items": 5,
        },
    )
    observed = {}

    def fake_payloads(_source, config):
        observed["transport"] = config.transport
        observed["tool"] = config.tools[0].name
        observed["arguments"] = config.tools[0].arguments
        return [
            {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            '{"title": "Example MCP result", '
                            '"url": "https://example.com/result", '
                            '"summary": "normalized from MCP tool"}'
                        ),
                    }
                ]
            }
        ]

    monkeypatch.setattr("radar.mcp_source.collect_mcp_payloads", fake_payloads)

    articles = _collect_single(source, category="mcp", limit=5, timeout=10)

    assert observed == {
        "transport": "stdio",
        "tool": "search",
        "arguments": {"query": "radar"},
    }
    assert len(articles) == 1
    assert articles[0].title == "Example MCP result"
    assert articles[0].link == "https://example.com/result"
    assert articles[0].summary == "normalized from MCP tool"
    assert articles[0].source == "Example MCP"
    assert articles[0].category == "mcp"


def test_disabled_mcp_server_source_is_not_executed(monkeypatch) -> None:
    source = Source(
        name="Disabled MCP",
        type="mcp_server",
        url="mcp://disabled",
        enabled=False,
        config={"transport": "stdio", "command": "should-not-run", "tools": ["search"]},
    )

    def fail_if_called(_source, _config):
        raise AssertionError("disabled MCP source should not be invoked")

    monkeypatch.setattr("radar.mcp_source.collect_mcp_payloads", fail_if_called)

    articles, errors = collect_sources(
        [source],
        category="mcp",
        min_interval_per_host=0.0,
        max_workers=1,
    )

    assert articles == []
    assert errors == []


def test_required_env_missing_fails_before_process_launch(monkeypatch) -> None:
    monkeypatch.delenv("MCP_RADAR_TEST_API_KEY", raising=False)
    source = Source(
        name="Env-gated MCP",
        type="mcp_server",
        url="mcp://env-gated",
        config={
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-c", "raise SystemExit(99)"],
            "tools": ["search"],
            "env": ["MCP_RADAR_TEST_API_KEY"],
            "timeout_seconds": 1,
        },
    )

    with pytest.raises(SourceError, match="Missing required MCP env var"):
        collect_mcp_server_source(source, category="mcp", limit=5, timeout=1)


def test_mcp_payload_without_url_uses_safe_fallback(monkeypatch) -> None:
    source = Source(
        name="Fallback MCP",
        type="mcp_stdio",
        url="",
        id="fallback-mcp",
        config={"command": "example-mcp", "tools": ["list_items"], "max_items": 1},
    )

    def fake_payloads(_source, _config):
        return [{"content": [{"type": "text", "text": "plain text result"}]}]

    monkeypatch.setattr("radar.mcp_source.collect_mcp_payloads", fake_payloads)

    articles = _collect_single(source, category="mcp", limit=5, timeout=10)

    assert len(articles) == 1
    assert articles[0].title == "plain text result"
    assert articles[0].link == "mcp://fallback-mcp#plain%20text%20result"


def test_mcp_collection_payloads_expand_to_stable_items(monkeypatch) -> None:
    source = Source(
        name="Daiso MCP",
        type="mcp_server",
        url="https://github.com/hmmhmmhm/daiso-mcp",
        config={
            "transport": "streamable_http",
            "server_url": "https://mcp.aka.page/mcp",
            "tools": ["daiso_search_products", "daiso_find_stores", "daiso_get_price_info"],
            "max_items": 10,
        },
    )

    def fake_payloads(_source, _config):
        return [
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "products": [
                                    {"id": "1062147", "name": "USB타입 모기유인퇴치기", "price": 5000}
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            },
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "stores": [
                                    {"name": "강남구청역점", "address": "서울특별시 강남구 학동로"}
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            },
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "productId": "1062147",
                                "productName": "USB타입 모기유인퇴치기",
                                "currentPrice": 5000,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            },
        ]

    monkeypatch.setattr("radar.mcp_source.collect_mcp_payloads", fake_payloads)

    articles = collect_mcp_server_source(source, category="commerce_mcp", limit=10, timeout=5)

    assert len(articles) == 2
    assert [article.title for article in articles] == [
        "USB타입 모기유인퇴치기",
        "강남구청역점",
    ]
    assert len({article.link for article in articles}) == len(articles)
    assert all(article.link.startswith("https://github.com/hmmhmmhm/daiso-mcp#") for article in articles)
    assert all(article.summary for article in articles)


def test_stdio_runtime_timeout_reports_request_context() -> None:
    source = Source(
        name="Hanging MCP",
        type="mcp_server",
        url="mcp://hanging",
        config={
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-c", HANGING_MCP_SERVER],
            "tools": ["search"],
            "timeout_seconds": 1,
        },
    )

    with pytest.raises(NetworkError, match="response 1 after 1s"):
        collect_mcp_server_source(source, category="mcp", limit=5, timeout=1)


def test_event_stream_response_forces_utf8_before_json_parsing() -> None:
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "text/event-stream"
    response.encoding = "ISO-8859-1"
    response._content = (
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"강남"}]}}\n'
        '\n'
    ).encode("utf-8")

    assert _response_json(response)["result"]["content"][0]["text"] == "강남"


def test_jsonrpc_result_rejects_mcp_tool_error_payload() -> None:
    with pytest.raises(RuntimeError, match="MCP tool result error"):
        _jsonrpc_result(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "API 요청 실패: 403 Forbidden"}],
                },
            }
        )


def test_kr_pc_deals_fake_stdio_fixture_collects_tool_results(monkeypatch) -> None:
    monkeypatch.setenv("ZYTE_API_KEY", "fixture-only")
    source = deepcopy(_mcp_source("edward-kim-dev/kr-pc-deals-mcp"))
    source.config["command"] = sys.executable
    source.config["args"] = [str(Path("fixtures/mcp/fake_kr_pc_deals_mcp.py"))]
    source.config["timeout_seconds"] = 5

    articles = collect_mcp_server_source(
        source,
        category="commerce_mcp",
        limit=20,
        timeout=5,
    )

    expected_tools = [
        "build_add",
        "build_check_compatibility",
        "build_remove",
        "build_status",
        "compare_prices",
        "find_lowest_price",
        "get_price_history",
        "get_product_detail",
        "list_by_category",
        "proxy_status",
        "search_parts",
    ]
    assert len(articles) == len(expected_tools)
    assert {article.source for article in articles} == {"edward-kim-dev/kr-pc-deals-mcp"}
    assert [article.title for article in articles] == [
        f"KR PC deals {tool_name} fixture" for tool_name in expected_tools
    ]
    assert {article.link for article in articles} == {
        f"https://example.test/commerce/kr-pc-deals/{tool_name}" for tool_name in expected_tools
    }
    assert all(article.summary for article in articles)
