from __future__ import annotations

import json
import sys
from copy import deepcopy

from radar.config_loader import load_category_config
from radar.mcp_source import collect_mcp_server_source, parse_mcp_source_config


FAKE_DAISO_MCP_SERVER = r"""
import json
import sys

for raw in sys.stdin:
    message = json.loads(raw)
    method = message.get("method")
    if method == "notifications/initialized":
        continue
    request_id = message.get("id")
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-daiso-mcp", "version": "0.0.0"},
        }
    elif method == "tools/call":
        tool_name = message["params"]["name"]
        arguments = message["params"].get("arguments", {})
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "title": f"{tool_name} fake transport smoke",
                            "url": f"https://example.com/daiso-mcp-smoke/{tool_name}",
                            "summary": json.dumps(
                                {"tool": tool_name, "arguments": arguments},
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        }
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)
"""


EXPECTED_DAISO_TOOLS = [
    "daiso_search_products",
    "daiso_find_stores",
    "daiso_get_price_info",
]


def _daiso_candidate():
    category = load_category_config("commerce_mcp")
    matches = [
        source
        for source in category.sources
        if source.type == "mcp_server" and source.config.get("repository") == "hmmhmmhm/daiso-mcp"
    ]
    assert len(matches) == 1
    return matches[0]


def test_daiso_candidate_keeps_real_transport_passed_contract() -> None:
    source = _daiso_candidate()

    assert source.enabled is True
    assert source.config["activation_status"] == "real_transport_smoke_test_passed"
    assert source.config["fake_transport_smoke_tested_at"] == "2026-04-29T07:14:18+00:00"
    assert source.config["stdio_transport_probe_failed_at"] == "2026-04-29T09:27:12+00:00"
    assert source.config["real_transport_smoke_tested_at"] == "2026-04-29T09:44:35+00:00"
    assert "runtime_node20_required" not in source.config["activation_gates"]
    assert "real_transport_smoke_test_required" not in source.config["activation_gates"]
    assert "remote_endpoint_registry_review_required" not in source.config["activation_gates"]
    assert "risk_scope_review_required" not in source.config["activation_gates"]
    assert "production_enablement_review_required" not in source.config["activation_gates"]
    assert source.config["activation_gates"] == []
    assert source.config["server_url"] == "https://mcp.aka.page/mcp"
    assert "fake_transport_smoke_test_required" not in source.config["activation_gates"]
    assert source.config["remote_endpoint_registry_review_status"] == "passed_with_scope_limits"
    assert source.config["remote_allowlist_drift_status"] == "passed"
    assert source.config["remote_allowlist_missing_tools"] == []
    assert source.config["remote_allowlist_prefix_mismatches"] == []
    assert source.config["remote_out_of_scope_tool_count"] == 29
    assert source.config["risk_review_status"] == "passed_with_scope_limits"
    assert source.config["production_enablement_status"] == "controlled_rollout_enabled"
    assert source.config["production_enablement_decision_status"] == "ready_for_controlled_enablement_review"
    assert source.config["production_enablement_recommended_option"] == "controlled_enablement"
    assert source.config["production_enablement_source_enabled_after_decision"] is True
    assert source.config["production_enablement_decision_failed_checks"] == []
    assert source.config["production_rollout_status"] == "active"
    assert source.config["production_rollout_enabled_at"] == "2026-04-29T10:37:07+00:00"
    assert (
        source.config["production_rollout_validation_artifact"]
        == "_workspace/2026-04-29_cycle43_daiso_controlled_rollout_validation.json"
    )
    assert source.config["production_rollout_monitored_at"] == "2026-04-29T11:32:49+00:00"
    assert (
        source.config["production_rollout_monitor_artifact"]
        == "_workspace/2026-04-29_cycle46_mcp_controlled_rollout_monitor.json"
    )
    assert source.config["production_deduplication_status"] == "active"
    assert source.config["production_deduplicated_at"] == "2026-04-29T11:32:49+00:00"
    assert source.config["production_canary_status"] == "passed_with_warnings"
    assert source.config["production_canary_article_count"] == 11
    assert source.config["production_canary_non_empty_summary_count"] == 11
    assert source.config["production_canary_exact_fallback_link_count"] == 0
    assert source.config["production_canary_duplicate_link_count"] == 1
    assert source.config["production_monitoring_metrics"]["max_duplicate_link_count"] == 0
    assert source.config["production_collection_cadence"] == "controlled_low_frequency_rollout"

    config = parse_mcp_source_config(source, timeout=10, limit=5)

    assert config.transport == "streamable_http"
    assert config.command == "npx"
    assert config.args == ("-y", "daiso")
    assert config.url == "https://mcp.aka.page/mcp"
    assert config.env == {}
    assert [tool.name for tool in config.tools] == EXPECTED_DAISO_TOOLS


def test_daiso_candidate_runs_against_fake_stdio_transport() -> None:
    source = deepcopy(_daiso_candidate())
    source.config["transport"] = "stdio"
    source.config["command"] = sys.executable
    source.config["args"] = ["-c", FAKE_DAISO_MCP_SERVER]
    source.config["timeout_seconds"] = 5

    articles = collect_mcp_server_source(
        source,
        category="commerce_mcp",
        limit=10,
        timeout=5,
    )

    assert len(articles) == len(EXPECTED_DAISO_TOOLS)
    assert {article.source for article in articles} == {"hmmhmmhm/daiso-mcp"}
    assert [article.title for article in articles] == [
        f"{tool_name} fake transport smoke" for tool_name in EXPECTED_DAISO_TOOLS
    ]
    assert {article.link for article in articles} == {
        f"https://example.com/daiso-mcp-smoke/{tool_name}" for tool_name in EXPECTED_DAISO_TOOLS
    }
    assert all(article.summary for article in articles)
