"""Unit tests for MCP transport adapters (stdio and SSE)."""

import json
import pytest

from fpe.mcp.tools import ToolRegistry, create_all_handlers


@pytest.fixture
def registry():
    r = ToolRegistry()
    for h in create_all_handlers():
        r.register(h)
    return r


class TestStdioTransport:
    """Test stdio transport message handling."""

    @pytest.mark.asyncio
    async def test_list_tools(self, registry):
        from fpe.mcp.server import _handle_stdio_message

        response = await _handle_stdio_message(
            {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}, registry
        )
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "1"
        assert len(response["result"]["tools"]) >= 1
        tool_names = [t["name"] for t in response["result"]["tools"]]
        assert "fpe_analyze_flow" in tool_names
        assert "fpe_resolve_next_hop" not in tool_names

        # Verify inputSchema is populated for each tool
        for tool in response["result"]["tools"]:
            assert "inputSchema" in tool, f"Missing inputSchema for {tool['name']}"
            schema = tool["inputSchema"]
            assert schema["type"] == "object"
            assert isinstance(schema["properties"], dict)
            assert isinstance(schema["required"], list)

        # Verify specific tool has expected parameters
        analyze = next(t for t in response["result"]["tools"] if t["name"] == "fpe_analyze_flow")
        assert "packet" in analyze["inputSchema"]["properties"]
        assert "packet" in analyze["inputSchema"]["required"]
        assert "exec_ctx" in analyze["inputSchema"]["properties"]

        iface_tool = next(t for t in response["result"]["tools"] if t["name"] == "fpe_get_interface_context")
        assert "iface" in iface_tool["inputSchema"]["properties"]
        assert "namespace" in iface_tool["inputSchema"]["properties"]
        assert "vrf" in iface_tool["inputSchema"]["properties"]
        assert "if_type" in iface_tool["inputSchema"]["properties"]
        assert iface_tool["inputSchema"]["required"] == []

    @pytest.mark.asyncio
    async def test_call_tool_unknown(self, registry):
        from fpe.mcp.server import _handle_stdio_message

        response = await _handle_stdio_message(
            {
                "jsonrpc": "2.0",
                "id": "2",
                "method": "tools/call",
                "params": {"name": "nonexistent", "arguments": {}},
            },
            registry,
        )
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "2"
        assert response["error"]["code"] == -32603
        assert "Unknown tool" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_unknown_message_type(self, registry):
        from fpe.mcp.server import _handle_stdio_message

        response = await _handle_stdio_message(
            {"jsonrpc": "2.0", "id": "3", "method": "unknown/method"}, registry
        )
        assert response["jsonrpc"] == "2.0"
        assert response["error"]["code"] == -32601


class TestSseSimplifiedMode:
    """Test simplified mode (POST /message without session_id)."""

    def _make_app(self, registry):
        """Build a Starlette app matching the SSE server layout."""
        from starlette.applications import Starlette
        from starlette.routing import Route
        from fpe.mcp.server import _AsgiEndpoint, _handle_simplified_post

        # Simplified test app with just the POST /message handler
        from fpe.mcp.tools import create_all_handlers
        from mcp.types import Tool

        tools = [
            Tool(name=entry["name"], description=entry["description"], inputSchema=entry["inputSchema"])
            for entry in registry.list_tools()
        ]

        async def handle_message(scope, receive, send):
            from urllib.parse import parse_qs
            query_string = scope.get("query_string", b"").decode()
            params = parse_qs(query_string)
            if "session_id" in params and params["session_id"][0]:
                # Skip SSE in test — return 404
                from starlette.responses import Response
                response = Response("", status_code=404)
                return await response(scope, receive, send)
            await _handle_simplified_post(registry, tools, scope, receive, send)

        app = Starlette(routes=[
            Route("/message", endpoint=_AsgiEndpoint(handle_message), methods=["POST"]),
        ])
        return app

    def test_simplified_initialize(self, registry):
        """Simplified POST /message returns initialize response."""
        from starlette.testclient import TestClient

        app = self._make_app(registry)
        with TestClient(app) as client:
            resp = client.post(
                "/message",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["jsonrpc"] == "2.0"
            assert data["id"] == 1
            assert data["result"]["serverInfo"]["name"] == "fpe"

    def test_simplified_tools_list(self, registry):
        """Simplified POST /message returns tools/list response."""
        from starlette.testclient import TestClient

        app = self._make_app(registry)
        with TestClient(app) as client:
            resp = client.post(
                "/message",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["jsonrpc"] == "2.0"
            assert len(data["result"]["tools"]) >= 1
            names = [t["name"] for t in data["result"]["tools"]]
            assert "fpe_analyze_flow" in names

    def test_simplified_tools_call(self, registry):
        """Simplified POST /message returns tools/call response."""
        from starlette.testclient import TestClient

        app = self._make_app(registry)
        with TestClient(app) as client:
            resp = client.post(
                "/message",
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "fpe_analyze_flow",
                        "arguments": {
                            "packet": {"src_ip": "10.0.0.2", "dst_ip": "8.8.8.8"},
                        },
                    },
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["jsonrpc"] == "2.0"
            assert "result" in data
            assert "content" in data["result"]

    def test_simplified_notification_initialized(self, registry):
        """Simplified POST returns empty 200 for notifications/initialized."""
        from starlette.testclient import TestClient

        app = self._make_app(registry)
        with TestClient(app) as client:
            resp = client.post(
                "/message",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            assert resp.status_code == 200

    def test_simplified_notification_cancelled(self, registry):
        """Simplified POST returns empty 200 for notifications/cancelled."""
        from starlette.testclient import TestClient

        app = self._make_app(registry)
        with TestClient(app) as client:
            resp = client.post(
                "/message",
                json={"jsonrpc": "2.0", "method": "notifications/cancelled"},
            )
            assert resp.status_code == 200

    def test_simplified_unknown_method(self, registry):
        """Simplified POST returns -32601 for unknown method."""
        from starlette.testclient import TestClient

        app = self._make_app(registry)
        with TestClient(app) as client:
            resp = client.post(
                "/message",
                json={"jsonrpc": "2.0", "id": 4, "method": "unknown/method"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "error" in data
            assert data["error"]["code"] == -32601

    def test_simplified_invalid_json(self, registry):
        """Simplified POST returns 400 for invalid JSON body."""
        from starlette.testclient import TestClient

        app = self._make_app(registry)
        with TestClient(app) as client:
            resp = client.post(
                "/message",
                content=b"not json",
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code == 400
