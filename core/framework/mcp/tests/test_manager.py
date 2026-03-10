from __future__ import annotations

from pathlib import Path

import pytest

from framework.mcp.errors import MCPAuthRequiredError, MCPAuthRequiredExternalError
from framework.mcp.manager import MCPManagerService, MCPManagerStore, MCPManagerValidationError
from framework.mcp.models import MCPTool


class _Credential:
    def __init__(self, keys: dict[str, str]):
        self._keys = keys

    def get_key(self, name: str):
        return self._keys.get(name)


class _CredentialStore:
    def __init__(self, credentials: dict[str, _Credential] | None = None):
        self._credentials = credentials or {}

    def get_credential(self, credential_id: str, refresh_if_needed: bool = False):
        _ = refresh_if_needed
        return self._credentials.get(credential_id)


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
        if self.mode == "auth_external":
            raise MCPAuthRequiredExternalError(
                self._config.name,
                {
                    "message": "Authorize via Aden",
                    "action": "authorize_via_aden",
                },
            )
        if self.mode == "error":
            raise RuntimeError("boom")
        if self.mode == "dataclass":
            return [
                MCPTool(
                    name="ping",
                    description="Ping",
                    input_schema={"type": "object"},
                    server_name=self._config.name,
                )
            ]
        return [{"name": "ping"}]

    def call_tool(self, tool_name, arguments):
        if self.mode == "error":
            raise RuntimeError("invoke failed")
        return [{"text": f"{tool_name}:{arguments}"}]


@pytest.fixture
def service(tmp_path: Path):
    store = MCPManagerStore(path=tmp_path / "servers.json")
    return MCPManagerService(store=store, credential_store=_CredentialStore())


def _stdio_payload(name: str = "local-tools") -> dict:
    return {
        "name": name,
        "description": "Local tools",
        "transport": "stdio",
        "command": "uv",
        "args": ["run", "python", "mcp_server.py", "--stdio"],
        "cwd": "../tools",
        "env": {"MCP_TOKEN": {"credential_id": "token_store", "key_name": "access_token"}},
        "oauth_credential_id": "token_store",
    }


def _http_payload(name: str = "http-tools") -> dict:
    return {
        "name": name,
        "description": "HTTP tools",
        "transport": "http",
        "url": "https://example.com/mcp",
        "headers": {"Accept": "application/json, text/event-stream"},
    }


def test_crud_roundtrip(service: MCPManagerService):
    created = service.create_server(_stdio_payload())
    assert created["id"]
    assert created["name"] == "local-tools"

    listed = service.list_servers()
    assert len(listed) == 1

    updated = service.update_server(created["id"], {"name": "local-tools-v2"})
    assert updated["name"] == "local-tools-v2"

    assert service.delete_server(created["id"]) is True
    assert service.list_servers() == []


def test_name_must_be_unique(service: MCPManagerService):
    service.create_server(_stdio_payload("dupe"))
    with pytest.raises(MCPManagerValidationError):
        service.create_server(_stdio_payload("dupe"))


def test_sensitive_literal_value_is_rejected(service: MCPManagerService):
    payload = _stdio_payload("bad-secret")
    payload["env"] = {"API_KEY": "raw-secret"}
    with pytest.raises(MCPManagerValidationError):
        service.create_server(payload)


def test_test_server_connected(monkeypatch: pytest.MonkeyPatch, service: MCPManagerService):
    created = service.create_server(_http_payload())
    monkeypatch.setattr("framework.mcp.manager.MCPClient", _FakeMCPClient)
    _FakeMCPClient.mode = "ok"

    result = service.test_server(created["id"])

    assert result["ok"] is True
    assert result["status"] == "connected"
    assert result["raw"]["tool_count"] == 1


def test_test_server_auth_required(monkeypatch: pytest.MonkeyPatch, service: MCPManagerService):
    created = service.create_server(_http_payload("auth"))
    monkeypatch.setattr("framework.mcp.manager.MCPClient", _FakeMCPClient)
    _FakeMCPClient.mode = "auth_required"

    result = service.test_server(created["id"])

    assert result["ok"] is False
    assert result["status"] == "auth_required"


def test_test_server_external_auth(monkeypatch: pytest.MonkeyPatch, service: MCPManagerService):
    created = service.create_server(_http_payload("external"))
    monkeypatch.setattr("framework.mcp.manager.MCPClient", _FakeMCPClient)
    _FakeMCPClient.mode = "auth_external"

    result = service.test_server(created["id"])

    assert result["ok"] is False
    assert result["status"] == "integration_not_supported"


def test_list_tools_serializes_dataclass_tools(
    monkeypatch: pytest.MonkeyPatch, service: MCPManagerService
):
    created = service.create_server(_http_payload("dataclass-tools"))
    monkeypatch.setattr("framework.mcp.manager.MCPClient", _FakeMCPClient)
    _FakeMCPClient.mode = "dataclass"

    result = service.list_server_tools(created["id"])

    assert result["ok"] is True
    assert result["status"] == "connected"
    assert isinstance(result["tools"], list)
    assert result["tools"][0]["name"] == "ping"


def test_invoke_by_name(monkeypatch: pytest.MonkeyPatch, service: MCPManagerService):
    service.create_server(_http_payload("named-server"))
    monkeypatch.setattr("framework.mcp.manager.MCPClient", _FakeMCPClient)
    _FakeMCPClient.mode = "ok"

    result = service.invoke_tool(
        server_name="named-server",
        tool_name="echo",
        tool_arguments={"x": 1},
    )

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["server_name"] == "named-server"


def test_update_transport_http_to_stdio(service: MCPManagerService):
    created = service.create_server(_http_payload("flip"))
    updated = service.update_server(
        created["id"],
        {
            "transport": "stdio",
            "command": "uv",
            "args": ["run", "python", "server.py", "--stdio"],
            "cwd": ".",
            "env": {},
        },
    )

    assert updated["transport"] == "stdio"
    assert updated["command"] == "uv"
    assert updated["url"] is None
    assert updated["headers"] == {}
