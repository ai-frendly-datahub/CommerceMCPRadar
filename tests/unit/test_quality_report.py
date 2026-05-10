from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from radar.config_loader import load_category_config, load_category_quality_config
from radar.models import Article
from radar.quality_report import build_quality_report, write_quality_report


def _category_name() -> str:
    configs = sorted(Path("config/categories").glob("*.yaml"))
    assert len(configs) == 1
    return configs[0].stem


def _env_required_names(source) -> list[str]:
    raw = source.config.get("env")
    if isinstance(raw, dict):
        return [str(name).strip() for name in raw if str(name).strip()]
    if isinstance(raw, list):
        return [str(name).strip() for name in raw if str(name).strip()]
    return []


def _env_resolved_values(source) -> dict[str, str]:
    raw = source.config.get("env")
    if isinstance(raw, list):
        return {str(name).strip(): os.environ.get(str(name).strip(), "") for name in raw if str(name).strip()}
    if not isinstance(raw, dict):
        return {}

    values: dict[str, str] = {}
    for key, raw_value in raw.items():
        env_name = str(key).strip()
        if not env_name:
            continue
        text_value = "" if raw_value is None else str(raw_value)
        if text_value.startswith("${") and text_value.endswith("}"):
            values[env_name] = os.environ.get(text_value[2:-1], "")
        else:
            values[env_name] = text_value
    return values


def _env_missing_names(source) -> list[str]:
    values = _env_resolved_values(source)
    return [name for name in _env_required_names(source) if not values.get(name, "").strip()]


def test_quality_report_tracks_directory_and_risk_scope_events() -> None:
    category = load_category_config(_category_name())
    source = category.sources[0]
    now = datetime(2026, 4, 13, tzinfo=UTC)
    article = Article(
        title="KIS_MCP_Server",
        link="https://github.com/example/KIS_MCP_Server",
        summary="KIS REST API stock lookup and order MCP server",
        published=now - timedelta(hours=3),
        source=source.name,
        category=category.category_name,
        matched_entities={
            "MCPDomain": ["finance", "tax"],
            "Provider": ["kis"],
            "Capability": ["lookup", "order"],
            "RiskScope": ["order", "api"],
            "ProjectHealth": ["mcp", "server"],
        },
        collected_at=now - timedelta(hours=3),
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config=load_category_quality_config(_category_name()),
        generated_at=now,
    )

    summary = report["summary"]
    mcp_sources = [source for source in category.sources if source.type == "mcp_server"]
    assert summary["total_sources"] == len(category.sources)
    assert summary["tracked_sources"] >= 1
    assert summary["fresh_sources"] >= 1
    assert summary["mcp_directory_entry_events"] == 1
    assert summary["linked_repository_metadata_events"] == len(mcp_sources)
    assert summary["risk_scope_signal_events"] == 1
    assert summary["mcp_signal_event_count"] >= 2 + len(mcp_sources)
    assert summary["directory_seed_source_count"] >= 1
    assert summary["mcp_server_candidate_count"] == len(mcp_sources)
    assert summary["blocked_mcp_server_source_count"] == sum(
        1 for source in mcp_sources if not source.enabled
    )
    assert summary["repository_metadata_complete_source_count"] == len(mcp_sources)
    assert (
        summary["repository_metadata_fresh_source_count"]
        + summary["repository_metadata_stale_source_count"]
        + summary["repository_metadata_incomplete_source_count"]
        + summary["repository_metadata_missing_checked_at_source_count"]
        == len(mcp_sources)
    )
    assert (
        summary["repository_docs_present_source_count"]
        + summary["repository_docs_missing_source_count"]
        == len(mcp_sources)
    )
    assert summary["repository_security_advisory_checked_source_count"] <= len(mcp_sources)
    assert summary["repository_security_advisory_total_count"] >= 0
    expected_activation_gates = [
        gate
        for source in mcp_sources
        for gate in source.config.get("activation_gates", [])
    ]
    expected_activation_gate_sets = [
        set(source.config.get("activation_gates", [])) for source in mcp_sources
    ]
    assert summary["activation_gate_total_count"] == len(expected_activation_gates)
    assert summary["activation_gate_source_count"] == sum(
        1 for gates in expected_activation_gate_sets if gates
    )
    assert summary["activation_command_unresolved_source_count"] == sum(
        1 for gates in expected_activation_gate_sets if "command_or_endpoint_unresolved" in gates
    )
    expected_command_discovery_statuses = [
        str(source.config.get("command_discovery_status") or "")
        for source in mcp_sources
        if source.config.get("command_discovery_status")
    ]
    expected_command_discovery_resolved = sum(
        1 for status in expected_command_discovery_statuses if status.startswith("resolved_")
    )
    assert summary["activation_command_discovery_checked_source_count"] == len(
        expected_command_discovery_statuses
    )
    assert (
        summary["activation_command_discovery_resolved_source_count"]
        == expected_command_discovery_resolved
    )
    assert summary["activation_command_discovery_unresolved_source_count"] == (
        len(expected_command_discovery_statuses) - expected_command_discovery_resolved
    )
    assert (
        summary["activation_command_discovery_multi_server_ambiguous_source_count"]
        == expected_command_discovery_statuses.count("multi_server_ambiguous")
    )
    assert summary["activation_command_discovery_status_counts"] == {
        status: expected_command_discovery_statuses.count(status)
        for status in sorted(set(expected_command_discovery_statuses))
    }
    assert summary["activation_env_secret_required_source_count"] == sum(
        1 for gates in expected_activation_gate_sets if "env_secret_documentation_required" in gates
    )
    assert summary["activation_tool_allowlist_required_source_count"] == sum(
        1 for gates in expected_activation_gate_sets if "tool_resource_allowlist_required" in gates
    )
    expected_env_sources = [source for source in mcp_sources if _env_required_names(source)]
    expected_env_missing_sources = [
        source for source in expected_env_sources if _env_missing_names(source)
    ]
    expected_env_missing_vars = sum(
        len(_env_missing_names(source)) for source in expected_env_sources
    )
    assert summary["env_preflight_required_source_count"] == len(expected_env_sources)
    assert summary["env_preflight_missing_source_count"] == len(expected_env_missing_sources)
    assert summary["env_preflight_missing_var_count"] == expected_env_missing_vars
    assert (
        summary["env_preflight_ready_source_count"]
        + summary["env_preflight_missing_source_count"]
        + summary["env_preflight_not_required_source_count"]
        == len(mcp_sources)
    )
    source_rows_by_name = {row["source"]: row for row in report["sources"]}
    for mcp_source in mcp_sources:
        mcp_row = source_rows_by_name[mcp_source.name]
        assert mcp_row["env_count"] == len(_env_required_names(mcp_source))
        assert mcp_row["env_required_names"] == _env_required_names(mcp_source)
        assert mcp_row["env_missing_names"] == _env_missing_names(mcp_source)
    assert "daily_review_item_count" in summary

    source_row = report["sources"][0]
    assert source_row["event_model"] == "mcp_directory_entry"
    assert source_row["activation_gate_count"] == 0
    assert source_row["activation_next_gate"] == ""
    assert source_row["status"] == "fresh"
    assert source_row["trust_tier"] == "T4_community"
    assert source_row["freshness_sla_days"] == 7.0
    assert source_row["latest_required_field_proxy"] == {
        "repository": True,
        "source_section": True,
        "source_url": True,
    }
    assert isinstance(report["daily_review_items"], list)

    metadata_events = [
        event for event in report["events"] if event["event_model"] == "linked_repository_metadata"
    ]
    assert len(metadata_events) == len(mcp_sources)
    assert {event["repository_metadata_status"] for event in metadata_events} <= {
        "fresh",
        "stale",
        "incomplete",
        "missing_checked_at",
    }
    for event in metadata_events:
        assert {"repository", "archived", "license", "docs", "security_advisory_check"} <= set(
            event["required_field_proxy"]
        )
        assert "github_docs_paths" in event
        assert "github_security_advisory_access_status" in event


def test_quality_report_marks_missing_directory_source() -> None:
    category = load_category_config(_category_name())
    report = build_quality_report(
        category=category,
        articles=[],
        quality_config=load_category_quality_config(_category_name()),
        generated_at=datetime(2026, 4, 13, tzinfo=UTC),
    )

    summary = report["summary"]
    assert summary["tracked_sources"] >= 1
    assert summary["missing_sources"] >= 1
    assert summary["mcp_directory_entry_events"] == 0
    assert summary["daily_review_item_count"] >= 1
    assert report["sources"][0]["status"] == "missing"
    assert report["daily_review_items"][0]["reason"] == "source_status_missing"


def test_quality_report_exposes_controlled_rollout_guard_status() -> None:
    category = load_category_config(_category_name())
    daiso_source = next(source for source in category.sources if source.name == "hmmhmmhm/daiso-mcp")
    now = datetime(2026, 4, 29, tzinfo=UTC)
    articles = [
        Article(
            title=f"다이소 테스트 상품 {index}",
            link=f"https://github.com/hmmhmmhm/daiso-mcp#test-{index}",
            summary='{"productName": "다이소 테스트 상품", "currentPrice": 1000}',
            published=now,
            source=daiso_source.name,
            category=category.category_name,
            collected_at=now,
            matched_entities={"MCPDomain": ["다이소"], "Provider": ["다이소"]},
        )
        for index in range(3)
    ]

    report = build_quality_report(
        category=category,
        articles=articles,
        quality_config=load_category_quality_config(_category_name()),
        generated_at=now,
    )

    summary = report["summary"]
    assert summary["controlled_rollout_source_count"] == 1
    assert summary["controlled_rollout_passed_count"] == 1
    assert summary["controlled_rollout_warning_count"] == 0
    assert summary["controlled_rollout_failure_count"] == 0

    source_row = next(row for row in report["sources"] if row["source"] == daiso_source.name)
    assert source_row["controlled_rollout"]["status"] == "passed"
    assert source_row["controlled_rollout"]["article_count"] == 3
    assert source_row["controlled_rollout"]["exact_fallback_link_count"] == 0
    assert source_row["controlled_rollout"]["duplicate_link_count"] == 0


def test_write_quality_report_writes_latest_and_dated_files(tmp_path: Path) -> None:
    category_name = "finance_tax_mcp"
    report = {
        "category": category_name,
        "generated_at": "2026-04-13T00:00:00+00:00",
        "summary": {},
    }

    paths = write_quality_report(report, output_dir=tmp_path, category_name=category_name)

    assert paths["latest"] == tmp_path / "finance_tax_mcp_quality.json"
    assert paths["dated"] == tmp_path / "finance_tax_mcp_20260413_quality.json"
    assert paths["latest"].exists()
    assert paths["dated"].exists()
