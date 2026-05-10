from __future__ import annotations

import json
import sys
from typing import Any


TOOL_NAMES = [
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

TOOLS = [
    {
        "name": name,
        "title": name.replace("_", " ").title(),
        "description": f"Return deterministic fixture data for {name}.",
        "inputSchema": {"type": "object", "additionalProperties": True},
    }
    for name in TOOL_NAMES
]

TOOL_RESULTS = {
    name: {
        "title": f"KR PC deals {name} fixture",
        "url": f"https://example.test/commerce/kr-pc-deals/{name}",
        "summary": (
            "Fixture-only kr-pc-deals-mcp result. "
            "No third-party package, external proxy, or retail site was called."
        ),
        "repository": "edward-kim-dev/kr-pc-deals-mcp",
        "tool_name": name,
        "fixture": True,
    }
    for name in TOOL_NAMES
}


def _response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    if method == "notifications/initialized":
        return None

    request_id = message.get("id")
    if method == "initialize":
        return _response(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-kr-pc-deals-mcp", "version": "0.0.0"},
            },
        )

    if method == "tools/list":
        return _response(request_id, {"tools": TOOLS})

    if method == "tools/call":
        params = message.get("params") or {}
        result = TOOL_RESULTS.get(str(params.get("name")))
        if result is None:
            return _error(request_id, -32602, "Unknown fixture tool")
        return _response(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, sort_keys=True),
                    }
                ],
                "structuredContent": result,
            },
        )

    return _error(request_id, -32601, "Unsupported fixture method")


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        response = handle(message)
        if response is None:
            continue
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
