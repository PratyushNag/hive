"""Centralized MCP manager routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import web

from framework.mcp.manager import (
    MCPManagerNotFoundError,
    MCPManagerService,
    MCPManagerValidationError,
    MCPSecretResolutionError,
)

logger = logging.getLogger(__name__)


def _get_manager(request: web.Request) -> MCPManagerService:
    return request.app["mcp_manager"]


async def handle_list_servers(request: web.Request) -> web.Response:
    manager = _get_manager(request)
    return web.json_response({"servers": manager.list_servers()})


async def handle_create_server(request: web.Request) -> web.Response:
    manager = _get_manager(request)
    body = await request.json()
    try:
        record = manager.create_server(body)
    except MCPManagerValidationError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Failed to create MCP server: %s", exc)
        return web.json_response({"error": "Internal server error"}, status=500)

    return web.json_response(record, status=201)


async def handle_patch_server(request: web.Request) -> web.Response:
    manager = _get_manager(request)
    server_id = request.match_info["server_id"]
    body = await request.json()
    try:
        record = manager.update_server(server_id, body)
    except MCPManagerNotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except MCPManagerValidationError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Failed to update MCP server '%s': %s", server_id, exc)
        return web.json_response({"error": "Internal server error"}, status=500)

    return web.json_response(record)


async def handle_delete_server(request: web.Request) -> web.Response:
    manager = _get_manager(request)
    server_id = request.match_info["server_id"]
    deleted = manager.delete_server(server_id)
    if not deleted:
        return web.json_response({"error": f"MCP server not found: {server_id}"}, status=404)
    return web.json_response({"deleted": True})


async def handle_test_server(request: web.Request) -> web.Response:
    manager = _get_manager(request)
    server_id = request.match_info["server_id"]
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, lambda: manager.test_server(server_id))
    except MCPManagerNotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except (MCPSecretResolutionError, MCPManagerValidationError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Failed to test MCP server '%s': %s", server_id, exc)
        return web.json_response({"error": "Internal server error"}, status=500)
    return web.json_response(result)


async def handle_server_tools(request: web.Request) -> web.Response:
    manager = _get_manager(request)
    server_id = request.match_info["server_id"]
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, lambda: manager.list_server_tools(server_id))
    except MCPManagerNotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except (MCPSecretResolutionError, MCPManagerValidationError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Failed to list tools for MCP server '%s': %s", server_id, exc)
        return web.json_response({"error": "Internal server error"}, status=500)
    return web.json_response(result)


async def _invoke(
    manager: MCPManagerService,
    *,
    server_id: str | None,
    server_name: str | None,
    tool_name: Any,
    tool_arguments: Any,
    timeout_ms: Any,
) -> tuple[dict[str, Any], int]:
    if timeout_ms is not None:
        if not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise MCPManagerValidationError("timeout_ms must be a positive integer")

    loop = asyncio.get_running_loop()
    invoke_task = loop.run_in_executor(
        None,
        lambda: manager.invoke_tool(
            server_id=server_id,
            server_name=server_name,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        ),
    )

    if isinstance(timeout_ms, int) and timeout_ms > 0:
        try:
            result = await asyncio.wait_for(invoke_task, timeout=timeout_ms / 1000)
        except TimeoutError:
            result = {
                "ok": False,
                "status": "error",
                "message": "Tool invocation timed out",
                "server_id": server_id,
                "server_name": server_name,
                "raw": {"error": "timeout"},
            }
        return result, 200

    result = await invoke_task
    return result, 200


async def handle_invoke_by_id(request: web.Request) -> web.Response:
    manager = _get_manager(request)
    server_id = request.match_info["server_id"]
    body = await request.json()

    tool_name = body.get("tool_name")
    tool_arguments = body.get("tool_arguments", {})
    timeout_ms = body.get("timeout_ms")

    try:
        result, status = await _invoke(
            manager,
            server_id=server_id,
            server_name=None,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            timeout_ms=timeout_ms,
        )
    except MCPManagerNotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except (MCPSecretResolutionError, MCPManagerValidationError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Failed to invoke tool on MCP server '%s': %s", server_id, exc)
        return web.json_response({"error": "Internal server error"}, status=500)

    return web.json_response(result, status=status)


async def handle_invoke_generic(request: web.Request) -> web.Response:
    manager = _get_manager(request)
    body = await request.json()

    server_id = body.get("server_id")
    server_name = body.get("server_name")
    tool_name = body.get("tool_name")
    tool_arguments = body.get("tool_arguments", {})
    timeout_ms = body.get("timeout_ms")

    try:
        result, status = await _invoke(
            manager,
            server_id=server_id,
            server_name=server_name,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            timeout_ms=timeout_ms,
        )
    except MCPManagerNotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except (MCPSecretResolutionError, MCPManagerValidationError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Failed to invoke MCP tool: %s", exc)
        return web.json_response({"error": "Internal server error"}, status=500)

    return web.json_response(result, status=status)


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/mcp/servers", handle_list_servers)
    app.router.add_post("/api/mcp/servers", handle_create_server)
    app.router.add_patch("/api/mcp/servers/{server_id}", handle_patch_server)
    app.router.add_delete("/api/mcp/servers/{server_id}", handle_delete_server)

    app.router.add_post("/api/mcp/servers/{server_id}/test", handle_test_server)
    app.router.add_get("/api/mcp/servers/{server_id}/tools", handle_server_tools)
    app.router.add_post("/api/mcp/servers/{server_id}/invoke", handle_invoke_by_id)

    app.router.add_post("/api/mcp/invoke", handle_invoke_generic)
