from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from framework.mcp.errors import MCPAuthRequiredError
from framework.mcp.models import MCPTool
from framework.server.app import create_app


class _FakeMCPClient:
    mode = "ok"

    def __init__(self, config):
        self._config = config

    def connect(self):
        return None

    def disconnect(self):
        return None

    def list_tools(self):
        if self.mode == "auth_required":
            raise MCPAuthRequiredError(
                self._config.name,
                {
                    "message": "Authorization required",
                    "auth_url": "https://example.com/oauth",
                },
            )
        if self.mode == "dataclass":
            return [
                MCPTool(
                    name="ping",
                    description="Ping",
                    input_schema={"type": "object"},
                    server_name=self._config.name,
                )
            ]
        return [{"name": "ping", "description": "Ping", "inputSchema": {"type": "object"}}]

    def call_tool(self, tool_name, arguments):
        return [{"text": f"{tool_name}:{arguments}"}]


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr("framework.mcp.manager.MCPClient", _FakeMCPClient)
    return create_app()


@pytest.mark.asyncio
async def test_mcp_manager_crud_and_operations(app):
    async with TestClient(TestServer(app)) as client:
        create_resp = await client.post(
            "/api/mcp/servers",
            json={
                "name": "fastmcp",
                "description": "FastMCP public server",
                "transport": "http",
                "url": "https://example.com/mcp",
                "headers": {"Accept": "application/json, text/event-stream"},
            },
        )
        assert create_resp.status == 201
        created = await create_resp.json()
        server_id = created["id"]

        list_resp = await client.get("/api/mcp/servers")
        assert list_resp.status == 200
        listed = await list_resp.json()
        assert len(listed["servers"]) == 1

        test_resp = await client.post(f"/api/mcp/servers/{server_id}/test")
        assert test_resp.status == 200
        test_data = await test_resp.json()
        assert test_data["status"] == "connected"

        tools_resp = await client.get(f"/api/mcp/servers/{server_id}/tools")
        assert tools_resp.status == 200
        tools_data = await tools_resp.json()
        assert tools_data["status"] == "connected"
        assert tools_data["tools"][0]["name"] == "ping"

        invoke_id_resp = await client.post(
            f"/api/mcp/servers/{server_id}/invoke",
            json={"tool_name": "ping", "tool_arguments": {"value": "x"}},
        )
        assert invoke_id_resp.status == 200
        invoke_id_data = await invoke_id_resp.json()
        assert invoke_id_data["status"] == "ok"

        invoke_name_resp = await client.post(
            "/api/mcp/invoke",
            json={
                "server_name": "fastmcp",
                "tool_name": "ping",
                "tool_arguments": {"value": "y"},
            },
        )
        assert invoke_name_resp.status == 200
        invoke_name_data = await invoke_name_resp.json()
        assert invoke_name_data["status"] == "ok"

        patch_resp = await client.patch(
            f"/api/mcp/servers/{server_id}",
            json={"name": "fastmcp-v2"},
        )
        assert patch_resp.status == 200
        patched = await patch_resp.json()
        assert patched["name"] == "fastmcp-v2"

        transport_patch = await client.patch(
            f"/api/mcp/servers/{server_id}",
            json={
                "transport": "stdio",
                "command": "uv",
                "args": ["run", "python", "server.py", "--stdio"],
                "cwd": ".",
                "env": {},
            },
        )
        assert transport_patch.status == 200
        transport_data = await transport_patch.json()
        assert transport_data["transport"] == "stdio"
        assert transport_data["url"] is None

        delete_resp = await client.delete(f"/api/mcp/servers/{server_id}")
        assert delete_resp.status == 200
        deleted = await delete_resp.json()
        assert deleted["deleted"] is True


@pytest.mark.asyncio
async def test_sensitive_plaintext_rejected(app):
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/mcp/servers",
            json={
                "name": "local-tools",
                "transport": "stdio",
                "command": "uv",
                "args": ["run", "python", "mcp_server.py", "--stdio"],
                "cwd": "../tools",
                "env": {"API_KEY": "raw-secret"},
            },
        )
        assert response.status == 400
        body = await response.json()
        assert "Use credential ref" in body["error"]


@pytest.mark.asyncio
async def test_auth_required_surface(app):
    async with TestClient(TestServer(app)) as client:
        create_resp = await client.post(
            "/api/mcp/servers",
            json={
                "name": "authy",
                "transport": "http",
                "url": "https://example.com/mcp",
                "headers": {"Accept": "application/json"},
            },
        )
        created = await create_resp.json()

        _FakeMCPClient.mode = "auth_required"
        test_resp = await client.post(f"/api/mcp/servers/{created['id']}/test")
        _FakeMCPClient.mode = "ok"

        assert test_resp.status == 200
        payload = await test_resp.json()
        assert payload["status"] == "auth_required"
        assert payload["raw"]["auth_url"] == "https://example.com/oauth"


@pytest.mark.asyncio
async def test_tools_endpoint_serializes_dataclass_tools(app):
    async with TestClient(TestServer(app)) as client:
        create_resp = await client.post(
            "/api/mcp/servers",
            json={
                "name": "dataclassy",
                "transport": "http",
                "url": "https://example.com/mcp",
                "headers": {"Accept": "application/json"},
            },
        )
        created = await create_resp.json()

        _FakeMCPClient.mode = "dataclass"
        tools_resp = await client.get(f"/api/mcp/servers/{created['id']}/tools")
        _FakeMCPClient.mode = "ok"

        assert tools_resp.status == 200
        payload = await tools_resp.json()
        assert payload["status"] == "connected"
        assert payload["tools"][0]["name"] == "ping"
