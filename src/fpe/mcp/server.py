"""MCP server entry point — supports stdio and SSE transport modes.

Usage:
  # stdio mode (default)
  python -m fpe.mcp.server

  # SSE mode
  python -m fpe.mcp.server --mode sse --port 8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from fpe.mcp.tools import ToolRegistry, create_all_handlers

logger = logging.getLogger(__name__)

MCP_JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-11-25"


# ── Common helpers ───────────────────────────────────────────────────

def create_registry() -> ToolRegistry:
    """Create and populate the MCP tool registry."""
    registry = ToolRegistry()
    for handler in create_all_handlers():
        registry.register(handler)
    return registry


def _tools_list(registry: ToolRegistry) -> list[dict[str, Any]]:
    return [
        {
            "name": entry["name"],
            "description": entry.get("description", ""),
            "inputSchema": entry.get("inputSchema", {"type": "object", "properties": {}, "required": []}),
        }
        for entry in registry.list_tools()
    ]


def _create_sdk_server(registry: ToolRegistry) -> Any:
    """Build an MCP SDK server around the registered tools."""
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    tools = [Tool(**entry) for entry in _tools_list(registry)]
    mcp_server = Server("fpe", version="0.1.0")

    @mcp_server.list_tools()
    async def list_tools() -> list[Tool]:
        return tools

    @mcp_server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        handler = registry.get(name)
        result = await handler.handle(arguments or {})
        return [TextContent(type="text", text=json.dumps(result.model_dump(), indent=2))]

    return mcp_server


# ── stdio transport ──────────────────────────────────────────────────

async def _run_stdio(registry: ToolRegistry) -> None:
    """Run MCP stdio mode through the official SDK transport."""
    from mcp.server.stdio import stdio_server

    mcp_server = _create_sdk_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())


async def _handle_stdio_message(
    msg: dict[str, Any], registry: ToolRegistry,
) -> dict[str, Any] | None:
    """Handle a JSON-RPC 2.0 message and return a response dict, or None for notifications."""
    method = msg.get("method", "")
    params = msg.get("params", {}) or {}
    request_id = msg.get("id")

    # Notifications have no id — no response sent
    if request_id is None:
        return None

    try:
        if method == "initialize":
            client_info = params.get("clientInfo", {})
            logger.info("Initialize from %s %s", client_info.get("name", "unknown"), client_info.get("version", ""))
            return {
                "jsonrpc": MCP_JSONRPC_VERSION,
                "id": request_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fpe", "version": "0.1.0"},
                },
            }

        if method == "tools/list":
            tools = [
                {"name": entry["name"], "description": entry.get("description", ""), "inputSchema": entry.get("inputSchema", {"type": "object", "properties": {}})}
                for entry in registry.list_tools()
            ]
            return {"jsonrpc": MCP_JSONRPC_VERSION, "id": request_id, "result": {"tools": tools}}

        if method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            handler = registry.get(tool_name)
            tr = await handler.handle(tool_args)
            return {
                "jsonrpc": MCP_JSONRPC_VERSION,
                "id": request_id,
                "result": {"content": [{"type": "text", "text": json.dumps(tr.model_dump(), indent=2)}]},
            }

        return {
            "jsonrpc": MCP_JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not supported: {method}"},
        }
    except Exception as e:
        logger.exception("Method error: %s", method)
        return {
            "jsonrpc": MCP_JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": -32603, "message": f"Internal error: {e}"},
        }


def run_stdio(registry: ToolRegistry) -> None:
    """Run MCP server in stdio mode (blocking)."""
    logger.info("MCP stdio server starting")
    asyncio.run(_run_stdio(registry))


# ── SSE transport (uses official MCP SDK) ────────────────────────────

class _AsgiEndpoint:
    """Wrap an ASGI handler for use with Starlette ``Route``.

    Starlette 1.0 treats function/method endpoints as request-response
    ``func(request) -> response``.  This wrapper forces ASGI detection.
    """

    def __init__(self, handler: Any) -> None:
        self._handler = handler

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self._handler(scope, receive, send)


def run_sse(
    registry: ToolRegistry,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    """Run MCP server in SSE mode via Starlette + uvicorn."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    from mcp.server.sse import SseServerTransport
    from mcp.types import Tool

    tools = [Tool(**entry) for entry in _tools_list(registry)]
    mcp_server = _create_sdk_server(registry)

    sse_transport = SseServerTransport("/message")

    async def handle_sse(scope: Any, receive: Any, send: Any) -> None:
        async with sse_transport.connect_sse(scope, receive, send) as (read, write):
            await mcp_server.run(read, write, mcp_server.create_initialization_options())

    async def handle_message(scope: Any, receive: Any, send: Any) -> None:
        from urllib.parse import parse_qs

        query_string = scope.get("query_string", b"").decode()
        params = parse_qs(query_string)

        if "session_id" in params and params["session_id"][0]:
            await sse_transport.handle_post_message(scope, receive, send)
        else:
            await _handle_simplified_post(registry, tools, scope, receive, send)

    app = Starlette(routes=[
        Route("/sse", endpoint=_AsgiEndpoint(handle_sse), methods=["GET"]),
        Route("/message", endpoint=_AsgiEndpoint(handle_message), methods=["POST"]),
    ])

    logger.info("MCP SSE server starting on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port)


async def _handle_simplified_post(
    registry: ToolRegistry,
    tools: list[Any],
    scope: Any,
    receive: Any,
    send: Any,
) -> None:
    """Simplified POST mode — synchronous JSON-RPC, no SSE required."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

    request = Request(scope, receive)
    body = await request.body()

    try:
        json_rpc_request = json.loads(body.decode())
    except json.JSONDecodeError:
        response = Response("Invalid JSON", status_code=400)
        return await response(scope, receive, send)

    method = json_rpc_request.get("method", "")
    params = json_rpc_request.get("params", {}) or {}
    request_id = json_rpc_request.get("id")

    try:
        if method == "initialize":
            result = {
                "jsonrpc": MCP_JSONRPC_VERSION,
                "id": request_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fpe", "version": "0.1.0"},
                },
            }
        elif method in ("notifications/initialized", "notifications/cancelled"):
            response = Response("", status_code=200)
            return await response(scope, receive, send)
        elif method == "tools/list":
            tools_dict = [
                {"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema}
                for t in tools
            ]
            result = {"jsonrpc": MCP_JSONRPC_VERSION, "id": request_id, "result": {"tools": tools_dict}}
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            handler = registry.get(tool_name)
            tr = await handler.handle(tool_args)
            result = {
                "jsonrpc": MCP_JSONRPC_VERSION,
                "id": request_id,
                "result": {"content": [{"type": "text", "text": json.dumps(tr.model_dump(), indent=2)}]},
            }
        else:
            result = {
                "jsonrpc": MCP_JSONRPC_VERSION,
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not supported: {method}"},
            }

        response = JSONResponse(result)
        return await response(scope, receive, send)

    except Exception as e:
        logger.exception("Simplified POST error: %s", e)
        error_result = {
            "jsonrpc": MCP_JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": -32603, "message": f"Internal error: {e}"},
        }
        response = JSONResponse(error_result)
        return await response(scope, receive, send)


# ── Entry point ──────────────────────────────────────────────────────

def main() -> None:
    """Parse args and start the appropriate transport."""
    parser = argparse.ArgumentParser(description="FPE MCP Server")
    parser.add_argument("--mode", choices=["stdio", "sse"], default="stdio", help="Transport mode")
    parser.add_argument("--host", default="0.0.0.0", help="SSE listen host")
    parser.add_argument("--port", type=int, default=8000, help="SSE listen port")
    args = parser.parse_args()

    from fpe.settings import settings

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    registry = create_registry()

    if args.mode == "stdio":
        run_stdio(registry)
    elif args.mode == "sse":
        run_sse(registry, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
