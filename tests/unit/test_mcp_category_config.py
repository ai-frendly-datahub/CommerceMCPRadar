from __future__ import annotations

from pathlib import Path

from radar.analyzer import apply_entity_rules
from radar.collector import parse_markdown_section_items
from radar.config_loader import load_category_config, load_category_quality_config
from radar.models import Article


def _category_name() -> str:
    configs = sorted(Path("config/categories").glob("*.yaml"))
    assert len(configs) == 1
    return configs[0].stem


def _seed_source(category):
    seeds = [source for source in category.sources if source.type == "github_readme_section"]
    assert len(seeds) == 1
    return seeds[0]


def _mcp_source(category, repository: str):
    return next(
        source
        for source in category.sources
        if source.type == "mcp_server" and source.config.get("repository") == repository
    )


def test_mcp_category_config_uses_readme_section_source() -> None:
    category = load_category_config(_category_name())

    source = _seed_source(category)
    assert source.type == "github_readme_section"
    assert source.url == "https://raw.githubusercontent.com/darjeeling/awesome-mcp-korea/main/README.md"
    assert source.section
    assert source.trust_tier == "T4_community"
    assert source.collection_tier == "C1_static_list"
    assert source.content_type == "mcp_directory"
    assert {entity.name for entity in category.entities} >= {
        "MCPDomain",
        "Provider",
        "Capability",
        "RiskScope",
        "ProjectHealth",
    }


def test_mcp_category_config_matches_section_entries() -> None:
    category = load_category_config(_category_name())
    seed_source = _seed_source(category)
    section = seed_source.section
    markdown = f"""
### {section}

**[example-mcp](https://github.com/example/example-mcp)** - {section} MCP server with API search tools.

### Other Section

**[other-mcp](https://github.com/example/other-mcp)** - Another MCP server.
"""

    items = parse_markdown_section_items(markdown, section)
    assert len(items) == 1

    article = Article(
        title=items[0]["title"],
        link=items[0]["link"],
        summary=items[0]["summary"],
        source=seed_source.name,
        category=category.category_name,
    )
    analyzed = apply_entity_rules([article], category.entities)

    assert analyzed[0].matched_entities
    assert "MCPDomain" in analyzed[0].matched_entities
    assert "ProjectHealth" in analyzed[0].matched_entities


def test_daiso_tool_results_match_operational_entities() -> None:
    category = load_category_config(_category_name())
    articles = [
        Article(
            title="USB타입 모기유인퇴치기",
            link="https://github.com/hmmhmmhm/daiso-mcp#1062147",
            summary=(
                '{"id": "1062147", "imageUrl": '
                '"https://cdn.daisomall.co.kr/file/PD/sample.jpg", '
                '"name": "USB타입 모기유인퇴치기", "pickupAvailable": false, '
                '"price": 5000, "soldOut": false}'
            ),
            source="hmmhmmhm/daiso-mcp",
            category=category.category_name,
        ),
        Article(
            title="강남역점",
            link="https://github.com/hmmhmmhm/daiso-mcp#gangnam",
            summary=(
                '{"address": "서울특별시 강남구 강남대로 422", '
                '"closeTime": "22:00", "lat": 37.5003, "lng": 127.0269, '
                '"name": "강남역점", "openTime": "10:00"}'
            ),
            source="hmmhmmhm/daiso-mcp",
            category=category.category_name,
        ),
    ]

    analyzed = apply_entity_rules(articles, category.entities)

    assert "MCPDomain" in analyzed[0].matched_entities
    assert "Provider" in analyzed[0].matched_entities
    assert "MCPDomain" in analyzed[1].matched_entities
    assert "Capability" in analyzed[1].matched_entities
    assert "RiskScope" in analyzed[1].matched_entities


def test_mcp_server_sources_are_disabled_metadata_candidates() -> None:
    category = load_category_config(_category_name())
    candidates = [source for source in category.sources if source.type == "mcp_server"]
    if category.category_name != "misc_mcp":
        assert candidates

    allowed_statuses = {
        "metadata_only",
        "blocked_command_unresolved",
        "blocked_env_required",
        "blocked_runtime_error",
        "blocked_tool_allowlist_unresolved",
        "blocked_runtime_config_unresolved",
        "candidate_ready_for_fake_transport_test",
        "fake_transport_smoke_test_passed",
        "real_transport_smoke_test_passed",
    }
    for source in candidates:
        controlled_rollout_enabled = (
            source.config.get("production_enablement_status") == "controlled_rollout_enabled"
        )
        assert source.enabled is controlled_rollout_enabled
        assert source.collection_tier == "C4_mcp_tool"
        assert source.content_type == "mcp_tool_result"
        assert source.config["activation_status"] in allowed_statuses
        assert source.config["repository"]
        assert isinstance(source.config.get("tools", []), list)
        assert isinstance(source.config.get("resources", []), list)
        assert source.config["docs_advisory_audit_status"] == "passed"
        assert (
            source.config["docs_advisory_audit_artifact"]
            == "_workspace/2026-04-30_cycle69_mcp_docs_advisory_audit.json"
        )
        assert source.config["github_readme_present"] is True
        assert source.config["github_docs_present"] is True
        assert source.config["github_docs_paths"]
        assert source.config["github_security_advisory_access_status"].startswith("checked")
        assert source.config["github_security_advisory_count"] >= 0
        if source.config.get("command_discovery_status"):
            assert source.config["command_discovery_checked_at"]
            assert (
                source.config["command_discovery_artifact"]
                == "_workspace/2026-04-30_cycle71_mcp_command_discovery_audit.json"
            )
        if "command_or_endpoint_unresolved" in source.config.get("activation_gates", []):
            assert source.config["command_discovery_status"]
        if source.config["activation_status"] != "metadata_only":
            assert source.config["activation_audited_at"]
            if controlled_rollout_enabled:
                assert source.config["activation_gates"] == []
            else:
                assert source.config["activation_gates"]


def test_mcp_category_quality_config_tracks_mcp_event_models() -> None:
    quality_config = load_category_quality_config(_category_name())
    data_quality = quality_config["data_quality"]
    assert isinstance(data_quality, dict)
    outputs = data_quality["quality_outputs"]
    assert isinstance(outputs, dict)
    assert outputs["tracked_event_models"] == [
        "mcp_directory_entry",
        "mcp_tool_result",
        "linked_repository_metadata",
        "risk_scope_signal",
    ]


def test_daiso_candidate_has_read_only_tool_allowlist() -> None:
    category = load_category_config(_category_name())
    source = _mcp_source(category, "hmmhmmhm/daiso-mcp")

    assert source.enabled is True
    assert source.config["activation_status"] == "real_transport_smoke_test_passed"
    assert source.config["fake_transport_smoke_tested_at"] == "2026-04-29T07:14:18+00:00"
    assert source.config["stdio_transport_probe_failed_at"] == "2026-04-29T09:27:12+00:00"
    assert source.config["real_transport_smoke_tested_at"] == "2026-04-29T09:44:35+00:00"
    assert source.config["transport"] == "streamable_http"
    assert source.config["server_url"] == "https://mcp.aka.page/mcp"
    assert source.config["remote_transport_hint"] == "sse"
    assert source.config["remote_health_status"] == "ok"
    assert source.config["command_semantics"] == "package_cli_discovery_not_stdio_server"
    assert "not a stdio MCP server" in source.config["transport_mode_summary"]
    assert source.config["package_registry_crosscheck_status"] == "passed"
    assert source.config["package_registry_crosschecked_at"] == "2026-04-29T09:03:07+00:00"
    assert source.config["package_name"] == "daiso"
    assert source.config["package_version"] == "1.0.4"
    assert source.config["package_bin"] == {"daiso": "dist/bin.js"}
    assert source.config["package_engines"] == {"node": ">=20 <21"}
    assert source.config["package_repository"] == "https://github.com/hmmhmmhm/daiso-mcp"
    assert source.config["package_license"] == "MIT"
    assert source.config["env"] == []
    assert source.config["event_model"] == "mcp_tool_result"
    assert "tool_resource_allowlist_required" not in source.config["activation_gates"]
    assert "fake_transport_smoke_test_required" not in source.config["activation_gates"]
    assert "runtime_node20_required" not in source.config["activation_gates"]
    assert "real_transport_smoke_test_required" not in source.config["activation_gates"]
    assert "remote_endpoint_registry_review_required" not in source.config["activation_gates"]
    assert "risk_scope_review_required" not in source.config["activation_gates"]
    assert "production_enablement_review_required" not in source.config["activation_gates"]
    assert source.config["activation_gates"] == []
    assert "tool_allowlist_unresolved" not in source.config["risk_scope"]
    assert source.config["risk_scope"] == ["network_read"]
    assert source.config["remote_endpoint_registry_review_status"] == "passed_with_scope_limits"
    assert source.config["remote_endpoint_registry_reviewed_at"] == "2026-04-29T09:51:12+00:00"
    assert source.config["remote_server_info"] == {"name": "multi-service-mcp", "version": "1.0.0"}
    assert source.config["remote_tool_count"] == 32
    assert source.config["remote_allowlist_drift_status"] == "passed"
    assert source.config["remote_allowlist_missing_tools"] == []
    assert source.config["remote_allowlist_prefix_mismatches"] == []
    assert source.config["remote_out_of_scope_tool_count"] == 29
    assert source.config["remote_out_of_scope_prefixes"]["daiso"] == 2
    assert source.config["risk_review_status"] == "passed_with_scope_limits"
    assert source.config["production_enablement_status"] == "controlled_rollout_enabled"
    assert source.config["production_enablement_decision_status"] == "ready_for_controlled_enablement_review"
    assert source.config["production_enablement_decision_at"] == "2026-04-29T10:20:43+00:00"
    assert source.config["production_enablement_recommended_option"] == "controlled_enablement"
    assert source.config["production_enablement_source_enabled_after_decision"] is True
    assert source.config["production_enablement_decision_failed_checks"] == []
    assert (
        source.config["production_enablement_decision_artifact"]
        == "_workspace/2026-04-29_cycle42_daiso_enablement_decision.json"
    )
    assert [option["name"] for option in source.config["production_rollout_options"]] == [
        "stay_disabled",
        "manual_canary_only",
        "controlled_enablement",
    ]
    assert source.config["production_rollout_options"][0]["status"] == "rollback_available"
    assert source.config["production_rollout_options"][1]["status"] == "rollback_available"
    assert source.config["production_rollout_options"][2]["status"] == "active"
    assert source.config["production_rollout_status"] == "active"
    assert source.config["production_rollout_enabled_at"] == "2026-04-29T10:37:07+00:00"
    assert (
        source.config["production_rollout_preflight_artifact"]
        == "_workspace/2026-04-29_cycle43_daiso_rollout_preflight_canary.json"
    )
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
    assert source.config["production_canary_tested_at"] == "2026-04-29T10:07:04+00:00"
    assert source.config["production_canary_article_count"] == 11
    assert source.config["production_canary_non_empty_summary_count"] == 11
    assert source.config["production_canary_exact_fallback_link_count"] == 0
    assert source.config["production_canary_duplicate_link_count"] == 1
    assert source.config["production_canary_duplicate_title_count"] == 1
    assert source.config["production_canary_source_names"] == ["hmmhmmhm/daiso-mcp"]
    assert source.config["production_canary_categories"] == ["commerce_mcp"]
    assert source.config["production_monitoring_metrics"] == {
        "min_article_count": 3,
        "require_non_empty_summary_count_equals_article_count": True,
        "max_exact_fallback_link_count": 0,
        "max_duplicate_link_count": 0,
        "expected_source_name": "hmmhmmhm/daiso-mcp",
        "expected_category": "commerce_mcp",
    }
    assert "duplicate_link_count_above_zero" in source.config["production_rollback_criteria"]
    assert source.config["production_collection_cadence"] == "controlled_low_frequency_rollout"
    assert [tool["name"] for tool in source.config["unsupported_tools"]] == [
        "daiso_check_inventory",
        "daiso_get_display_location",
    ]
    assert source.config["remote_out_of_scope_daiso_tools"] == [
        "daiso_check_inventory",
        "daiso_get_display_location",
    ]
    assert [tool["name"] for tool in source.config["tools"]] == [
        "daiso_search_products",
        "daiso_find_stores",
        "daiso_get_price_info",
    ]


def test_kr_pc_deals_candidate_has_fake_transport_evidence() -> None:
    category = load_category_config(_category_name())
    source = _mcp_source(category, "edward-kim-dev/kr-pc-deals-mcp")

    assert source.enabled is False
    assert source.config["activation_status"] == "blocked_env_required"
    assert source.config["fake_transport_smoke_tested_at"] == "2026-05-01T04:00:00+00:00"
    assert source.config["fake_transport_smoke_test_status"] == "passed"
    assert (
        source.config["fake_transport_smoke_test_artifact"]
        == "_workspace/2026-05-01_cycle80_commerce_kr_pc_deals_fake_probe.json"
    )
    assert source.config["fake_transport_fixture"] == "fixtures/mcp/fake_kr_pc_deals_mcp.py"
    assert source.config["env"] == ["ZYTE_API_KEY"]
    assert source.config["event_model"] == "mcp_tool_result"
    assert "fake_transport_smoke_test_required" not in source.config["activation_gates"]
    assert "real_transport_smoke_test_required" in source.config["activation_gates"]
    assert "env_secret_documentation_required" not in source.config["activation_gates"]
    assert source.config["env_documentation_status"] == "documented_no_secret_placeholder"
    assert (
        source.config["env_documentation_artifact"]
        == "_workspace/2026-05-07_mcp_env_documentation_manifest.json"
    )
    assert "risk_scope_review_required" not in source.config["activation_gates"]
    assert source.config["risk_scope_review_status"] == "reviewed_static_allowlist"
    assert (
        source.config["risk_scope_review_artifact"]
        == "_workspace/2026-05-07_mcp_risk_scope_gate_closure.json"
    )
    assert "write_or_mutation_possible" in source.config["risk_scope"]
    assert [tool["name"] if isinstance(tool, dict) else tool for tool in source.config["tools"]] == [
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
